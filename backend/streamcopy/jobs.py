from __future__ import annotations

import errno
import os
import queue
import threading
import time
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.files.service import FileWriteBlocked
from backend.files.write_authorization import file_writes_allowed


MEDIA_TYPES = {"hdd", "ssd", "flash"}
TRANSPORT_TYPES = {"internal", "usb2", "usb3", "usb4", "unknown"}
USB_TOPOLOGIES = {"unknown", "shared", "separate"}
TERMINAL_STATES = {"completed", "completed_with_warnings", "failed", "cancelled"}

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}


class StreamCopyCancelled(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def stream_profile(
    source_media: str,
    destination_media: str,
    source_transport: str = "unknown",
    destination_transport: str = "unknown",
    usb_topology: str = "unknown",
    source_cache_mib: int | float | str | None = None,
    destination_cache_mib: int | float | str | None = None,
) -> dict[str, Any]:
    src = str(source_media).casefold()
    dst = str(destination_media).casefold()
    src_transport = str(source_transport).casefold()
    dst_transport = str(destination_transport).casefold()
    topology = str(usb_topology).casefold()
    source_cache = max(0, min(1024, int(float(source_cache_mib or 0))))
    destination_cache = max(0, min(1024, int(float(destination_cache_mib or 0))))
    if src not in MEDIA_TYPES or dst not in MEDIA_TYPES:
        raise ValueError("media type must be hdd, ssd or flash")
    if src_transport not in TRANSPORT_TYPES or dst_transport not in TRANSPORT_TYPES:
        raise ValueError("transport must be internal, usb2, usb3, usb4 or unknown")
    if topology not in USB_TOPOLOGIES:
        raise ValueError("usb_topology must be unknown, shared or separate")

    if "flash" in {src, dst}:
        chunk_mib, depth = 4, 4
        strategy = "flash-adaptive-stream"
    elif src == "hdd" and dst == "hdd":
        chunk_mib = 8
        depth = 6 if topology == "separate" else 3 if topology == "shared" else 4
        if source_cache and destination_cache:
            # Hardware drive cache is not our RAM queue, but it is useful as a
            # conservative hint. Use the geometric mean so a 32/128 MiB pair
            # does not blindly allocate either extreme.
            hinted_depth = max(
                3,
                min(8, round(((source_cache * destination_cache) ** 0.5) / chunk_mib)),
            )
            topology_cap = 4 if topology == "shared" else 8 if topology == "separate" else 6
            depth = min(hinted_depth, topology_cap)
        strategy = "hdd-hdd-sequential-pipeline"
    elif src == "hdd" and dst == "ssd":
        chunk_mib, depth = 8, 6
        strategy = "source-locality-stream"
    elif src == "ssd" and dst == "hdd":
        chunk_mib, depth = 16, 6
        strategy = "destination-sequential-stream"
    else:
        chunk_mib, depth = 8, 10
        strategy = "ssd-ssd-buffered-stream"

    both_usb3 = src_transport == "usb3" and dst_transport == "usb3"
    if both_usb3 and src == "hdd" and dst == "hdd":
        if topology == "shared":
            transport_note = (
                "Both endpoints are HDD over USB 3.x on a shared hub/controller. "
                "The HDDs remain the scheduling profile; queue depth is reduced to avoid "
                "building a large backlog on the shared USB path."
            )
        elif topology == "separate":
            transport_note = (
                "Both endpoints are HDD over USB 3.x on separate controllers/paths. "
                "The HDDs remain the scheduling profile; USB 3.x is treated as transport headroom."
            )
        else:
            transport_note = (
                "Both endpoints are HDD over USB 3.x. HDD→HDD sequential scheduling is used. "
                "USB topology is unknown, so a conservative queue depth is selected."
            )
    else:
        transport_note = "Media type controls scheduling; transport is a secondary constraint."

    return {
        "strategy": strategy,
        "chunk_bytes": chunk_mib * 1024 * 1024,
        "chunk_mib": chunk_mib,
        "queue_depth": depth,
        "max_buffer_mib": chunk_mib * depth,
        "source_media": src,
        "destination_media": dst,
        "source_transport": src_transport,
        "destination_transport": dst_transport,
        "usb_topology": topology,
        "source_cache_mib": source_cache or None,
        "destination_cache_mib": destination_cache or None,
        "cache_note": (
            "Drive cache sizes are hints only; StreamCopy keeps a separate bounded RAM ring buffer."
            if source_cache or destination_cache
            else "Drive cache sizes were not provided."
        ),
        "transport_note": transport_note,
        "ordering": "single manifest / directory order / one producer + one consumer",
        "experimental": True,
    }


def _set_job(job_id: str, **changes: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(changes)
            _jobs[job_id]["updated_at"] = _now()


def _record_warning(job_id: str, path: str, message: str) -> None:
    with _lock:
        job = _jobs[job_id]
        job["skipped"] += 1
        job["warnings"].append({"path": path, "message": message})
        if len(job["warnings"]) > 200:
            job["warnings"] = job["warnings"][-200:]
        job["updated_at"] = _now()


def _progress(job_id: str, byte_count: int, current_path: str, file_completed: bool = False) -> None:
    with _lock:
        job = _jobs[job_id]
        job["bytes"] += int(byte_count)
        if file_completed:
            job["files"] += 1
        job["current_path"] = current_path
        total = int(job["total_bytes"] or 0)
        job["progress_percent"] = round(job["bytes"] * 100 / total, 2) if total else 100.0
        elapsed = max(0.001, time.monotonic() - float(job["_started_monotonic"]))
        job["average_mib_s"] = round(job["bytes"] / (1024 * 1024) / elapsed, 2)
        job["updated_at"] = _now()


def _manifest(source: Path, destination_root: Path, job_id: str) -> tuple[Path, list[Path], list[tuple[Path, Path, int]]]:
    if source.is_file():
        target_root = destination_root
        return target_root, [], [(source, destination_root / source.name, int(source.stat().st_size))]
    if not source.is_dir():
        raise FileNotFoundError(source)

    target_root = destination_root / source.name
    directories: list[Path] = [target_root]
    files: list[tuple[Path, Path, int]] = []
    for root, dirs, names in os.walk(source, followlinks=False):
        root_path = Path(root)
        relative_root = root_path.relative_to(source)
        target_dir = target_root if str(relative_root) == "." else target_root / relative_root
        directories.append(target_dir)

        kept: list[str] = []
        for name in dirs:
            child = root_path / name
            try:
                if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                    _record_warning(job_id, str(child), "link/junction skipped")
                    continue
            except OSError as exc:
                _record_warning(job_id, str(child), f"{type(exc).__name__}: {exc}")
                continue
            kept.append(name)
        dirs[:] = kept

        for name in names:
            child = root_path / name
            try:
                if child.is_symlink():
                    _record_warning(job_id, str(child), "symlink skipped")
                    continue
                size = int(child.stat().st_size)
            except (OSError, PermissionError) as exc:
                _record_warning(job_id, str(child), f"{type(exc).__name__}: {exc}")
                continue
            relative = child.relative_to(source)
            files.append((child, target_root / relative, size))
    return target_root, directories, files


def _same_path_or_nested(source: Path, destination_root: Path) -> bool:
    source_resolved = source.resolve(strict=True)
    destination_resolved = destination_root.resolve(strict=False)
    if os.name == "nt":
        src = str(source_resolved).casefold()
        dst = str(destination_resolved).casefold()
        return dst == src or dst.startswith(src.rstrip("\\/") + os.sep.casefold())
    try:
        destination_resolved.relative_to(source_resolved)
        return True
    except ValueError:
        return destination_resolved == source_resolved


def _is_fatal_destination_error(exc: BaseException) -> bool:
    if isinstance(exc, OSError) and exc.errno in {
        errno.ENOSPC,
        errno.EROFS,
        errno.EIO,
        errno.ENODEV,
    }:
        return True
    return False


def _run_job(job_id: str, source: Path, destination_root: Path, profile: dict[str, Any]) -> None:
    cancel = _cancel_events[job_id]
    stream_queue: queue.Queue[tuple] = queue.Queue(maxsize=int(profile["queue_depth"]))
    producer_error: list[BaseException] = []
    producer_done = threading.Event()
    consumer_fatal = threading.Event()
    chunk_size = int(profile["chunk_bytes"])

    try:
        target_root, directories, files = _manifest(source, destination_root, job_id)
        if cancel.is_set():
            raise StreamCopyCancelled("Operation cancelled by operator")

        active_files: list[tuple[Path, Path, int]] = []
        skipped_bytes = 0
        for src, dst, size in files:
            try:
                if dst.exists():
                    _record_warning(job_id, str(dst), "destination exists; skipped")
                    skipped_bytes += size
                    continue
            except OSError as exc:
                _record_warning(job_id, str(dst), f"{type(exc).__name__}: {exc}")
                skipped_bytes += size
                continue
            active_files.append((src, dst, size))

        total_bytes = sum(size for _src, _dst, size in active_files)
        with _lock:
            job = _jobs[job_id]
            job.update(
                {
                    "status": "running",
                    "target_root": str(target_root),
                    "total_files": len(active_files),
                    "total_bytes": total_bytes,
                    "skipped_bytes": skipped_bytes,
                    "manifest_files": len(files),
                    "manifest_directories": len(set(directories)),
                    "progress_percent": 0.0 if total_bytes else 100.0,
                    "updated_at": _now(),
                }
            )

        for directory in sorted(set(directories), key=lambda p: len(p.parts)):
            if cancel.is_set():
                raise StreamCopyCancelled("Operation cancelled by operator")
            try:
                directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                if _is_fatal_destination_error(exc):
                    raise
                _record_warning(job_id, str(directory), f"{type(exc).__name__}: {exc}")

        def put(message: tuple) -> None:
            while True:
                if cancel.is_set():
                    raise StreamCopyCancelled("Operation cancelled by operator")
                if consumer_fatal.is_set():
                    raise RuntimeError("destination stream stopped")
                try:
                    stream_queue.put(message, timeout=0.2)
                    return
                except queue.Full:
                    continue

        def producer() -> None:
            try:
                for index, (src, dst, size) in enumerate(active_files):
                    if cancel.is_set() or consumer_fatal.is_set():
                        break
                    put(("begin", index, str(src), str(dst), size))
                    sent = 0
                    try:
                        with src.open("rb", buffering=0) as source_stream:
                            while sent < size:
                                if cancel.is_set() or consumer_fatal.is_set():
                                    break
                                data = source_stream.read(min(chunk_size, size - sent))
                                if not data:
                                    raise OSError(
                                        f"Unexpected EOF after {sent} of {size} bytes"
                                    )
                                put(("data", index, data))
                                sent += len(data)
                    except (OSError, PermissionError) as exc:
                        put(("source_error", index, str(src), f"{type(exc).__name__}: {exc}"))
                        continue
                    put(("end", index, str(src), str(dst), size))
            except BaseException as exc:  # noqa: BLE001
                producer_error.append(exc)
            finally:
                producer_done.set()
                while not consumer_fatal.is_set():
                    try:
                        stream_queue.put(("done",), timeout=0.2)
                        break
                    except queue.Full:
                        if cancel.is_set():
                            break

        producer_thread = threading.Thread(
            target=producer,
            name=f"streamcopy-producer-{job_id[:8]}",
            daemon=True,
        )
        producer_thread.start()

        current_index: int | None = None
        current_source = ""
        current_target: Path | None = None
        destination_stream = None
        sink_disabled = False
        current_written = 0

        while True:
            if cancel.is_set():
                raise StreamCopyCancelled("Operation cancelled by operator")
            try:
                message = stream_queue.get(timeout=0.25)
            except queue.Empty:
                if producer_done.is_set():
                    break
                continue

            kind = message[0]
            if kind == "done":
                break

            if kind == "begin":
                _, current_index, current_source, target_text, _size = message
                current_target = Path(target_text)
                sink_disabled = False
                current_written = 0
                try:
                    current_target.parent.mkdir(parents=True, exist_ok=True)
                    destination_stream = current_target.open("xb", buffering=0)
                except (OSError, PermissionError) as exc:
                    destination_stream = None
                    sink_disabled = True
                    if _is_fatal_destination_error(exc):
                        consumer_fatal.set()
                        raise
                    _record_warning(job_id, str(current_target), f"{type(exc).__name__}: {exc}")
                _set_job(job_id, current_path=current_source)
                continue

            if kind == "data":
                _, index, data = message
                if index != current_index:
                    consumer_fatal.set()
                    raise RuntimeError("stream framing error")
                if not sink_disabled and destination_stream is not None:
                    try:
                        destination_stream.write(data)
                    except (OSError, PermissionError) as exc:
                        if _is_fatal_destination_error(exc):
                            consumer_fatal.set()
                            raise
                        sink_disabled = True
                        _record_warning(
                            job_id,
                            str(current_target or ""),
                            f"{type(exc).__name__}: {exc}",
                        )
                if not sink_disabled:
                    current_written += len(data)
                    _progress(job_id, len(data), current_source)
                continue

            if kind == "source_error":
                _, index, source_text, error_text = message
                if index == current_index and destination_stream is not None:
                    destination_stream.close()
                    destination_stream = None
                if current_written:
                    _progress(job_id, -current_written, source_text)
                    current_written = 0
                if current_target is not None:
                    try:
                        current_target.unlink(missing_ok=True)
                    except OSError:
                        pass
                sink_disabled = True
                _record_warning(job_id, source_text, error_text)
                continue

            if kind == "end":
                _, index, source_text, target_text, expected_size = message
                if index != current_index:
                    consumer_fatal.set()
                    raise RuntimeError("stream framing error")
                if destination_stream is not None:
                    destination_stream.close()
                    destination_stream = None
                target = Path(target_text)
                if sink_disabled:
                    if current_written:
                        _progress(job_id, -current_written, source_text)
                        current_written = 0
                    try:
                        target.unlink(missing_ok=True)
                    except OSError:
                        pass
                else:
                    try:
                        actual = int(target.stat().st_size)
                        if actual != int(expected_size):
                            raise OSError(
                                f"Size verification failed: expected {expected_size}, got {actual}"
                            )
                    except OSError as exc:
                        _record_warning(job_id, target_text, f"{type(exc).__name__}: {exc}")
                        try:
                            target.unlink(missing_ok=True)
                        except OSError:
                            pass
                    else:
                        _progress(job_id, 0, source_text, file_completed=True)
                current_index = None
                current_target = None
                current_source = ""
                sink_disabled = False
                current_written = 0

        if destination_stream is not None:
            destination_stream.close()
        producer_thread.join(timeout=2)
        if producer_error:
            raise producer_error[0]
        if cancel.is_set():
            raise StreamCopyCancelled("Operation cancelled by operator")

        with _lock:
            job = _jobs[job_id]
            status = "completed_with_warnings" if job["skipped"] else "completed"
            job["status"] = status
            job["current_path"] = ""
            job["progress_percent"] = 100.0
            job["finished_at"] = _now()
            job["updated_at"] = _now()
    except StreamCopyCancelled as exc:
        consumer_fatal.set()
        _set_job(
            job_id,
            status="cancelled",
            error=str(exc),
            finished_at=_now(),
            current_path="",
        )
    except BaseException as exc:  # noqa: BLE001
        consumer_fatal.set()
        _set_job(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=_now(),
        )


def start_streamcopy_job(
    source_path: str,
    destination_path: str,
    source_media: str,
    destination_media: str,
    source_transport: str = "unknown",
    destination_transport: str = "unknown",
    usb_topology: str = "unknown",
    source_cache_mib: int | float | str | None = None,
    destination_cache_mib: int | float | str | None = None,
) -> dict[str, Any]:
    if not file_writes_allowed():
        raise FileWriteBlocked("File writes are locked")

    source = Path(str(source_path)).expanduser()
    destination = Path(str(destination_path)).expanduser()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_symlink():
        raise ValueError("source root cannot be a symlink")
    if _same_path_or_nested(source, destination):
        raise ValueError("destination cannot be the source or be nested inside it")

    profile = stream_profile(
        source_media,
        destination_media,
        source_transport,
        destination_transport,
        usb_topology,
        source_cache_mib,
        destination_cache_mib,
    )
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise NotADirectoryError(destination)

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": "streamcopy_experimental",
        "status": "planning",
        "source_path": str(source),
        "destination_path": str(destination),
        "target_root": None,
        "profile": profile,
        "bytes": 0,
        "total_bytes": 0,
        "files": 0,
        "total_files": 0,
        "manifest_files": 0,
        "manifest_directories": 0,
        "skipped": 0,
        "skipped_bytes": 0,
        "warnings": [],
        "error": None,
        "current_path": "",
        "average_mib_s": 0.0,
        "progress_percent": 0.0,
        "created_at": _now(),
        "updated_at": _now(),
        "finished_at": None,
        "_started_monotonic": time.monotonic(),
    }
    cancel = threading.Event()
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = cancel

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, source, destination, profile),
        name=f"streamcopy-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return get_streamcopy_job(job_id)


def get_streamcopy_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = deepcopy(_jobs[job_id])
    job.pop("_started_monotonic", None)
    return job


def cancel_streamcopy_job(job_id: str) -> dict[str, Any]:
    with _lock:
        event = _cancel_events[job_id]
        job = _jobs[job_id]
        if job["status"] not in TERMINAL_STATES:
            event.set()
            job["cancel_requested"] = True
            job["updated_at"] = _now()
    return get_streamcopy_job(job_id)
