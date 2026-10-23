from __future__ import annotations

import hashlib
import os
import queue
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.events import emit_event
from backend.core.logging_setup import log_error, log_event, log_warning
from backend.files.endpoint_availability import bind_local_volume, local_endpoint_state
from backend.files.service import FileWriteBlocked
from backend.files.write_authorization import file_writes_allowed
from backend.streamcopy import journal


MEDIA_TYPES = {"hdd", "ssd", "flash"}
TRANSPORT_TYPES = {"internal", "usb2", "usb3", "usb4", "unknown"}
USB_TOPOLOGIES = {"unknown", "shared", "separate"}
TERMINAL_STATES = journal.TERMINAL_STATES

CHECKPOINT_BYTES = 128 * 1024 * 1024
ENDPOINT_RECHECK_SECONDS = 3.0
LEASE_SECONDS = 15.0
LEASE_HEARTBEAT_SECONDS = 3.0
RECOVERY_POLL_SECONDS = 3.0

_INSTANCE_ID = uuid.uuid4().hex
_lock = threading.RLock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}
_threads: dict[str, threading.Thread] = {}
_recovery_started = False
_event_last_emit: dict[str, float] = {}


class StreamCopyCancelled(RuntimeError):
    pass


class StreamCopyLeaseLost(RuntimeError):
    pass


class StreamCopySourceChanged(RuntimeError):
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
                "The HDDs remain the scheduling profile; queue depth is reduced."
            )
        elif topology == "separate":
            transport_note = (
                "Both endpoints are HDD over USB 3.x on separate paths/controllers. "
                "USB 3.x is transport headroom; HDD scheduling remains active."
            )
        else:
            transport_note = (
                "Both endpoints are HDD over USB 3.x. HDD→HDD sequential scheduling is used "
                "with conservative queue depth because USB topology is unknown."
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
        "ordering": "persistent manifest / sequential items / one producer + one consumer",
        "checkpoint_mib": CHECKPOINT_BYTES // (1024 * 1024),
        "experimental": True,
    }


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    value = dict(job)
    value.pop("lease_owner", None)
    value.pop("lease_expires_at", None)
    value.pop("source_endpoint", None)
    value.pop("destination_endpoint", None)
    value["checkpoint_mib"] = CHECKPOINT_BYTES // (1024 * 1024)
    value["recovery_mode"] = "rollback_to_verified_checkpoint"
    value["operation"] = "copy_then_delete" if value.get("delete_source_after_verify") else "copy"
    return value


def _cache_job(job: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = _jobs.get(job["id"], {})
        started = current.get("_started_monotonic", time.monotonic())
        session_start_bytes = current.get("_session_start_bytes", int(job.get("bytes") or 0))
        cached = dict(job)
        cached["_started_monotonic"] = started
        cached["_session_start_bytes"] = session_start_bytes
        _jobs[job["id"]] = cached
        return cached


def _load_job(job_id: str) -> dict[str, Any]:
    job = journal.get_job(job_id)
    _cache_job(job)
    return job


def _persist_job(job_id: str, **changes: Any) -> None:
    with _lock:
        cached = _jobs.get(job_id)
        if cached is not None:
            if "warnings_json" in changes:
                cached["warnings"] = changes["warnings_json"]
            for key, value in changes.items():
                if key != "warnings_json":
                    cached[key] = value
            cached["updated_at"] = changes.get("updated_at", _now())
    journal.update_job(job_id, **changes)
    event_payload = {"job_id": job_id, **{k: v for k, v in changes.items() if k != "warnings_json"}}
    emit_event("streamcopy.changed", event_payload)


def _append_warning(job_id: str, path: str, message: str) -> None:
    job = _load_job(job_id)
    warnings = list(job.get("warnings") or [])
    warnings.append({"path": path, "message": message})
    if len(warnings) > 200:
        warnings = warnings[-200:]
    skipped = max(int(job.get("skipped") or 0), len(warnings))
    _persist_job(job_id, warnings_json=warnings, skipped=skipped)


def _control_check(cancel: threading.Event, lease_lost: threading.Event) -> None:
    if lease_lost.is_set():
        raise StreamCopyLeaseLost("StreamCopy lease was lost to another backend")
    if cancel.is_set():
        raise StreamCopyCancelled("Operation cancelled by operator")


def _endpoint_states(job: dict[str, Any]) -> list[dict[str, Any]]:
    states = []
    for role, endpoint in (
        ("source", job.get("source_endpoint") or {}),
        ("destination", job.get("destination_endpoint") or {}),
    ):
        state = local_endpoint_state(endpoint)
        states.append({"role": role, **state})
    return states


def _wait_for_endpoints(
    job_id: str,
    cancel: threading.Event,
    lease_lost: threading.Event,
) -> None:
    was_waiting = False
    while True:
        _control_check(cancel, lease_lost)
        job = _load_job(job_id)
        states = _endpoint_states(job)
        unavailable = [state for state in states if not state.get("available")]
        if not unavailable:
            if was_waiting or job.get("status") == "waiting_endpoint":
                _persist_job(
                    job_id,
                    status="recovering",
                    waiting_since=None,
                    auto_resumes=int(job.get("auto_resumes") or 0) + 1,
                    error=None,
                )
                log_event("streamcopy.endpoint_resumed", job_id=job_id)
            return

        if not was_waiting and job.get("status") != "waiting_endpoint":
            _persist_job(
                job_id,
                status="waiting_endpoint",
                waiting_since=_now(),
                wait_cycles=int(job.get("wait_cycles") or 0) + 1,
                error="; ".join(
                    f"{state['role']}:{state.get('reason')}" for state in unavailable
                ),
            )
            log_warning(
                "streamcopy.endpoint_waiting",
                job_id=job_id,
                reason=";".join(
                    f"{state['role']}:{state.get('reason')}" for state in unavailable
                ),
            )
        was_waiting = True
        time.sleep(ENDPOINT_RECHECK_SECONDS)


def _source_stat_matches(item: dict[str, Any]) -> bool:
    try:
        stat = Path(item["source_path"]).stat()
    except OSError:
        return False
    if int(stat.st_size) != int(item["size"]):
        return False
    expected_mtime = item.get("source_mtime_ns")
    return expected_mtime is None or int(stat.st_mtime_ns) == int(expected_mtime)


def _hash_range(path: Path, start: int, size: int) -> str:
    digest = hashlib.sha256()
    remaining = int(size)
    with path.open("rb", buffering=0) as stream:
        stream.seek(int(start))
        while remaining > 0:
            data = stream.read(min(8 * 1024 * 1024, remaining))
            if not data:
                raise OSError(f"Unexpected EOF while hashing {path}")
            digest.update(data)
            remaining -= len(data)
    return digest.hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        while True:
            data = stream.read(8 * 1024 * 1024)
            if not data:
                return digest.hexdigest()
            digest.update(data)


def _partial_path(target: Path, job_id: str) -> Path:
    return target.with_name(f"{target.name}.dspart-{job_id[:12]}")


def _build_manifest(job_id: str, source: Path, destination_root: Path) -> None:
    if source.is_file():
        stat = source.stat()
        target_root = destination_root
        target = destination_root / source.name
        items = [
            {
                "item_index": 0,
                "source_path": str(source),
                "target_path": str(target),
                "partial_path": str(_partial_path(target, job_id)),
                "size": int(stat.st_size),
                "source_mtime_ns": int(stat.st_mtime_ns),
            }
        ]
        directory_count = 0
    else:
        target_root = destination_root / source.name
        items: list[dict[str, Any]] = []
        directories: set[str] = {str(target_root)}
        for root, dirs, names in os.walk(source, followlinks=False):
            root_path = Path(root)
            relative_root = root_path.relative_to(source)
            target_dir = target_root if str(relative_root) == "." else target_root / relative_root
            directories.add(str(target_dir))

            kept: list[str] = []
            for name in dirs:
                child = root_path / name
                try:
                    if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                        _append_warning(job_id, str(child), "link/junction skipped during manifest")
                        continue
                except OSError as exc:
                    _append_warning(job_id, str(child), f"{type(exc).__name__}: {exc}")
                    continue
                kept.append(name)
            dirs[:] = kept

            for name in names:
                child = root_path / name
                try:
                    if child.is_symlink():
                        _append_warning(job_id, str(child), "symlink skipped during manifest")
                        continue
                    stat = child.stat()
                except (OSError, PermissionError) as exc:
                    _append_warning(job_id, str(child), f"{type(exc).__name__}: {exc}")
                    continue
                relative = child.relative_to(source)
                target = target_root / relative
                items.append(
                    {
                        "item_index": len(items),
                        "source_path": str(child),
                        "target_path": str(target),
                        "partial_path": str(_partial_path(target, job_id)),
                        "size": int(stat.st_size),
                        "source_mtime_ns": int(stat.st_mtime_ns),
                    }
                )
        directory_count = len(directories)
        for directory in sorted(directories, key=lambda value: len(Path(value).parts)):
            Path(directory).mkdir(parents=True, exist_ok=True)

    journal.replace_manifest(
        job_id,
        target_root=str(target_root),
        items=items,
        directory_count=directory_count,
    )
    _load_job(job_id)


def _safe_resume_offset(
    job_id: str,
    item: dict[str, Any],
    *,
    cancel: threading.Event,
    lease_lost: threading.Event,
) -> int:
    _control_check(cancel, lease_lost)
    source = Path(item["source_path"])
    partial = Path(item["partial_path"])

    if not _source_stat_matches(item):
        raise StreamCopySourceChanged(
            f"Source identity changed: {item['source_path']}"
        )
    if not partial.exists():
        journal.discard_checkpoints_after(job_id, int(item["item_index"]), 0)
        return 0

    partial_size = int(partial.stat().st_size)
    for checkpoint in journal.list_checkpoints(job_id, int(item["item_index"])):
        _control_check(cancel, lease_lost)
        offset = int(checkpoint["offset"])
        block_start = int(checkpoint["block_start"])
        block_size = int(checkpoint["block_size"])
        expected = str(checkpoint["digest"])
        if offset > partial_size or block_start + block_size != offset:
            continue
        try:
            source_digest = _hash_range(source, block_start, block_size)
            partial_digest = _hash_range(partial, block_start, block_size)
        except OSError:
            raise
        if source_digest == expected and partial_digest == expected:
            journal.discard_checkpoints_after(job_id, int(item["item_index"]), offset)
            with partial.open("r+b", buffering=0) as stream:
                stream.truncate(offset)
            return offset

    journal.discard_checkpoints_after(job_id, int(item["item_index"]), 0)
    with partial.open("r+b", buffering=0) as stream:
        stream.truncate(0)
    return 0


def _verify_pair(source: Path, target: Path, mode: str) -> None:
    if int(source.stat().st_size) != int(target.stat().st_size):
        raise OSError(
            f"Size verification failed: source={source.stat().st_size}, target={target.stat().st_size}"
        )
    if mode == "sha256" and _hash_file(source) != _hash_file(target):
        raise OSError(f"SHA-256 verification failed: {target}")


def _sync_durable_progress(job_id: str, current_offset: int = 0) -> dict[str, Any]:
    summary = journal.summarize_items(job_id)
    job = _load_job(job_id)
    durable_bytes = int(summary["completed_bytes"]) + int(current_offset)
    total = int(job.get("total_bytes") or 0)
    progress = round(durable_bytes * 100 / total, 2) if total else 100.0
    skipped = max(int(job.get("skipped") or 0), int(summary["skipped_files"]))
    _persist_job(
        job_id,
        bytes=durable_bytes,
        files=int(summary["completed_files"]),
        skipped=skipped,
        skipped_bytes=int(summary["skipped_bytes"]),
        progress_percent=progress,
    )
    return summary


def _progress_ram(job_id: str, base_bytes: int, offset: int, current_path: str) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["bytes"] = int(base_bytes) + int(offset)
        job["current_path"] = current_path
        total = int(job.get("total_bytes") or 0)
        job["progress_percent"] = round(job["bytes"] * 100 / total, 2) if total else 100.0
        elapsed = max(0.001, time.monotonic() - float(job["_started_monotonic"]))
        session_bytes = max(0, job["bytes"] - int(job.get("_session_start_bytes") or 0))
        job["average_mib_s"] = round(session_bytes / (1024 * 1024) / elapsed, 2)
        job["updated_at"] = _now()
        now = time.monotonic()
        last = _event_last_emit.get(job_id, 0.0)
        if now - last >= 0.5:
            _event_last_emit[job_id] = now
            emit_event(
                "streamcopy.progress",
                {
                    "job_id": job_id,
                    "bytes": job["bytes"],
                    "total_bytes": total,
                    "progress_percent": job["progress_percent"],
                    "average_mib_s": job["average_mib_s"],
                    "current_path": current_path,
                },
            )


def _mark_skipped(job_id: str, item: dict[str, Any], message: str) -> None:
    partial = Path(item["partial_path"])
    try:
        partial.unlink(missing_ok=True)
    except OSError:
        pass
    journal.discard_checkpoints_after(job_id, int(item["item_index"]), 0)
    journal.update_item(
        job_id,
        int(item["item_index"]),
        status="skipped",
        confirmed_offset=0,
        error=message,
    )
    _append_warning(job_id, str(item["source_path"]), message)
    _sync_durable_progress(job_id)


def _publish_completed_item(
    job_id: str,
    item: dict[str, Any],
    job: dict[str, Any],
    *,
    source: Path,
    target: Path,
    partial: Path | None,
) -> None:
    verify_mode = str(job.get("verify_mode") or "size")
    verification_target = partial if partial is not None else target
    _verify_pair(source, verification_target, verify_mode)

    if partial is not None:
        if target.exists():
            raise FileExistsError(target)
        journal.update_item(job_id, int(item["item_index"]), status="publishing", error=None)
        partial.rename(target)

    journal.update_item(
        job_id,
        int(item["item_index"]),
        status="completed",
        confirmed_offset=int(item["size"]),
        error=None,
    )
    _sync_durable_progress(job_id)

    if job.get("delete_source_after_verify"):
        try:
            source.unlink()
        except FileNotFoundError:
            pass


def _copy_item(
    job_id: str,
    item: dict[str, Any],
    cancel: threading.Event,
    lease_lost: threading.Event,
) -> None:
    item_index = int(item["item_index"])
    source = Path(item["source_path"])
    target = Path(item["target_path"])
    partial = Path(item["partial_path"])

    while True:
        _control_check(cancel, lease_lost)
        _wait_for_endpoints(job_id, cancel, lease_lost)
        job = _load_job(job_id)
        item = journal.get_item(job_id, item_index)

        if item["status"] == "skipped":
            return

        if item["status"] == "completed":
            if not target.exists():
                if source.exists():
                    journal.update_item(
                        job_id,
                        item_index,
                        status="pending",
                        confirmed_offset=0,
                        error="published target disappeared; recopying",
                    )
                    journal.discard_checkpoints_after(job_id, item_index, 0)
                    continue
                raise FileNotFoundError(
                    f"Completed target disappeared and source is unavailable: {target}"
                )
            if source.exists():
                try:
                    _verify_pair(
                        source,
                        target,
                        "sha256" if job.get("delete_source_after_verify") else "size",
                    )
                    if job.get("delete_source_after_verify"):
                        source.unlink()
                except OSError:
                    if any(not state["available"] for state in _endpoint_states(job)):
                        continue
                    if not job.get("delete_source_after_verify"):
                        journal.update_item(
                            job_id,
                            item_index,
                            status="pending",
                            confirmed_offset=0,
                            error="published target no longer matches; recopying",
                        )
                        continue
                    raise
            return

        if item["status"] == "publishing" and target.exists():
            try:
                _publish_completed_item(
                    job_id,
                    item,
                    job,
                    source=source,
                    target=target,
                    partial=None,
                )
                return
            except OSError as exc:
                if any(not state["available"] for state in _endpoint_states(job)):
                    continue
                raise exc

        if target.exists():
            _mark_skipped(job_id, item, f"destination exists; skipped: {target}")
            return

        try:
            resume_offset = _safe_resume_offset(
                job_id,
                item,
                cancel=cancel,
                lease_lost=lease_lost,
            )
        except OSError:
            if any(not state["available"] for state in _endpoint_states(job)):
                continue
            raise

        if not _source_stat_matches(item):
            raise StreamCopySourceChanged(f"Source changed: {source}")

        target.parent.mkdir(parents=True, exist_ok=True)
        journal.update_item(job_id, item_index, status="in_progress", error=None)
        _persist_job(
            job_id,
            status="running",
            current_item_index=item_index,
            current_path=str(source),
            error=None,
        )

        summary = journal.summarize_items(job_id)
        base_bytes = int(summary["completed_bytes"])
        _progress_ram(job_id, base_bytes, resume_offset, str(source))

        stream_queue: queue.Queue[tuple[str, Any]] = queue.Queue(
            maxsize=int(job["profile"]["queue_depth"])
        )
        producer_stop = threading.Event()
        producer_error: list[BaseException] = []
        chunk_size = int(job["profile"]["chunk_bytes"])

        def producer() -> None:
            try:
                with source.open("rb", buffering=0) as source_stream:
                    source_stream.seek(resume_offset)
                    remaining = int(item["size"]) - resume_offset
                    while remaining > 0 and not producer_stop.is_set():
                        _control_check(cancel, lease_lost)
                        data = source_stream.read(min(chunk_size, remaining))
                        if not data:
                            raise OSError(
                                f"Unexpected EOF after {int(item['size']) - remaining} bytes"
                            )
                        while not producer_stop.is_set():
                            try:
                                stream_queue.put(("data", data), timeout=0.2)
                                break
                            except queue.Full:
                                _control_check(cancel, lease_lost)
                        remaining -= len(data)
            except BaseException as exc:  # noqa: BLE001
                producer_error.append(exc)
            finally:
                while not producer_stop.is_set():
                    try:
                        stream_queue.put(("done", None), timeout=0.2)
                        break
                    except queue.Full:
                        continue

        producer_thread = threading.Thread(
            target=producer,
            daemon=True,
            name=f"streamcopy-producer-{job_id[:8]}-{item_index}",
        )
        producer_thread.start()

        offset = resume_offset
        block_start = resume_offset
        block_digest = hashlib.sha256()
        copy_error: BaseException | None = None

        try:
            mode = "r+b" if partial.exists() else "w+b"
            with partial.open(mode, buffering=0) as destination_stream:
                destination_stream.truncate(resume_offset)
                destination_stream.seek(resume_offset)

                while True:
                    _control_check(cancel, lease_lost)
                    try:
                        kind, payload = stream_queue.get(timeout=0.5)
                    except queue.Empty:
                        if producer_thread.is_alive():
                            continue
                        kind, payload = ("done", None)
                    if kind == "done":
                        break
                    data = payload
                    written = destination_stream.write(data)
                    if written != len(data):
                        raise OSError(
                            f"Short write: expected {len(data)} bytes, wrote {written}"
                        )
                    block_digest.update(data)
                    offset += len(data)
                    _progress_ram(job_id, base_bytes, offset, str(source))

                    if offset - block_start == CHECKPOINT_BYTES:
                        destination_stream.flush()
                        os.fsync(destination_stream.fileno())
                        digest = block_digest.hexdigest()
                        journal.add_checkpoint(
                            job_id,
                            item_index,
                            offset=offset,
                            block_start=block_start,
                            block_size=offset - block_start,
                            digest=digest,
                        )
                        _sync_durable_progress(job_id, offset)
                        block_start = offset
                        block_digest = hashlib.sha256()
                    elif offset - block_start > CHECKPOINT_BYTES:
                        raise RuntimeError("StreamCopy checkpoint alignment invariant failed")

                destination_stream.flush()
                os.fsync(destination_stream.fileno())
        except BaseException as exc:  # noqa: BLE001
            copy_error = exc
        finally:
            producer_stop.set()
            producer_thread.join(timeout=3)

        if copy_error is None and producer_error:
            copy_error = producer_error[0]

        if copy_error is not None:
            if isinstance(copy_error, (StreamCopyCancelled, StreamCopyLeaseLost)):
                raise copy_error
            current_job = _load_job(job_id)
            if any(not state["available"] for state in _endpoint_states(current_job)):
                log_warning(
                    "streamcopy.flow_interrupted",
                    job_id=job_id,
                    item_index=item_index,
                    path=source,
                    error=f"{type(copy_error).__name__}: {copy_error}",
                )
                continue
            if isinstance(copy_error, (OSError, PermissionError)) and not target.exists():
                if not _source_stat_matches(item):
                    _mark_skipped(
                        job_id,
                        item,
                        f"{type(copy_error).__name__}: {copy_error}",
                    )
                    return
            raise copy_error

        if offset != int(item["size"]):
            raise OSError(
                f"Stream length mismatch for {source}: expected {item['size']}, got {offset}"
            )

        try:
            _publish_completed_item(
                job_id,
                item,
                _load_job(job_id),
                source=source,
                target=target,
                partial=partial,
            )
            return
        except OSError:
            current_job = _load_job(job_id)
            if any(not state["available"] for state in _endpoint_states(current_job)):
                continue
            raise


def _cleanup_deleted_source_tree(job: dict[str, Any]) -> None:
    if not job.get("delete_source_after_verify"):
        return
    source = Path(job["source_path"])
    if not source.exists() or not source.is_dir():
        return
    for root, dirs, _files in os.walk(source, topdown=False):
        for name in dirs:
            try:
                (Path(root) / name).rmdir()
            except OSError:
                pass
    try:
        source.rmdir()
    except OSError:
        pass


def _heartbeat(
    job_id: str,
    stop: threading.Event,
    lease_lost: threading.Event,
) -> None:
    while not stop.wait(LEASE_HEARTBEAT_SECONDS):
        try:
            if not journal.renew_lease(job_id, _INSTANCE_ID, LEASE_SECONDS):
                lease_lost.set()
                return
        except Exception:  # noqa: BLE001
            lease_lost.set()
            return


def _run_job(job_id: str) -> None:
    cancel = _cancel_events[job_id]
    lease_lost = threading.Event()
    heartbeat_stop = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat,
        args=(job_id, heartbeat_stop, lease_lost),
        daemon=True,
        name=f"streamcopy-heartbeat-{job_id[:8]}",
    )
    heartbeat_thread.start()

    try:
        job = _load_job(job_id)
        _wait_for_endpoints(job_id, cancel, lease_lost)

        items = journal.list_items(job_id)
        if not items:
            source = Path(job["source_path"])
            destination = Path(job["destination_path"])
            _persist_job(job_id, status="planning", error=None)
            while not items:
                _control_check(cancel, lease_lost)
                _wait_for_endpoints(job_id, cancel, lease_lost)
                try:
                    _build_manifest(job_id, source, destination)
                    items = journal.list_items(job_id)
                    break
                except OSError:
                    current_job = _load_job(job_id)
                    if any(
                        not state["available"]
                        for state in _endpoint_states(current_job)
                    ):
                        continue
                    raise

        _persist_job(job_id, status="recovering", error=None)
        for item in items:
            _control_check(cancel, lease_lost)
            _copy_item(job_id, item, cancel, lease_lost)

        job = _load_job(job_id)
        _cleanup_deleted_source_tree(job)
        summary = journal.summarize_items(job_id)
        warnings = list(job.get("warnings") or [])
        status = (
            "completed_with_warnings"
            if warnings or summary["skipped_files"]
            else "completed"
        )
        _persist_job(
            job_id,
            status=status,
            bytes=int(summary["completed_bytes"]),
            files=int(summary["completed_files"]),
            skipped=max(int(job.get("skipped") or 0), int(summary["skipped_files"])),
            skipped_bytes=int(summary["skipped_bytes"]),
            progress_percent=100.0,
            current_item_index=None,
            current_path="",
            error=None,
            finished_at=_now(),
        )
        completion_logger = log_warning if status == "completed_with_warnings" else log_event
        completion_logger(
            f"streamcopy.{status}",
            job_id=job_id,
            files=summary["completed_files"],
            bytes=summary["completed_bytes"],
            skipped=summary["skipped_files"],
        )
    except StreamCopyCancelled as exc:
        _persist_job(
            job_id,
            status="cancelled",
            error=str(exc),
            finished_at=_now(),
            current_path="",
        )
        log_event("streamcopy.cancelled", job_id=job_id)
    except StreamCopyLeaseLost as exc:
        log_error("streamcopy.lease_lost", job_id=job_id, error=str(exc))
    except BaseException as exc:  # noqa: BLE001
        _persist_job(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=_now(),
        )
        log_error(
            "streamcopy.failed",
            job_id=job_id,
            error=f"{type(exc).__name__}: {exc}",
        )
    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1)
        journal.release_lease(job_id, _INSTANCE_ID)
        with _lock:
            _cancel_events.pop(job_id, None)
            _threads.pop(job_id, None)
            _event_last_emit.pop(job_id, None)


def _spawn_claimed_job(job_id: str) -> bool:
    with _lock:
        existing = _threads.get(job_id)
        if existing is not None and existing.is_alive():
            return False
        event = threading.Event()
        _cancel_events[job_id] = event
        job = journal.get_job(job_id)
        _cache_job(job)
        thread = threading.Thread(
            target=_run_job,
            args=(job_id,),
            daemon=True,
            name=f"streamcopy-{job_id[:8]}",
        )
        _threads[job_id] = thread
        thread.start()
        return True


def recover_streamcopy_jobs_once() -> int:
    recovered = 0
    for job in journal.list_jobs(active_only=True, limit=100):
        job_id = str(job["id"])
        with _lock:
            thread = _threads.get(job_id)
            if thread is not None and thread.is_alive():
                continue
        if journal.claim_job(job_id, _INSTANCE_ID, LEASE_SECONDS):
            _persist_job(job_id, status="recovering", error=None)
            if _spawn_claimed_job(job_id):
                recovered += 1
                log_event("streamcopy.recovered", job_id=job_id)
    return recovered


def start_streamcopy_recovery_manager() -> None:
    global _recovery_started
    with _lock:
        if _recovery_started:
            return
        _recovery_started = True

    def manager() -> None:
        while True:
            try:
                recover_streamcopy_jobs_once()
            except Exception as exc:  # noqa: BLE001
                log_error(
                    "streamcopy.recovery_manager_error",
                    error=f"{type(exc).__name__}: {exc}",
                )
            time.sleep(RECOVERY_POLL_SECONDS)

    threading.Thread(
        target=manager,
        daemon=True,
        name="streamcopy-recovery-manager",
    ).start()


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
    verify_mode: str = "size",
    delete_source_after_verify: bool = False,
) -> dict[str, Any]:
    if not file_writes_allowed():
        raise FileWriteBlocked("File writes are locked")

    source = Path(str(source_path)).expanduser()
    destination = Path(str(destination_path)).expanduser()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.is_symlink():
        raise ValueError("source root cannot be a symlink")

    source_resolved = source.resolve(strict=True)
    destination_resolved = destination.resolve(strict=False)
    if destination_resolved == source_resolved:
        raise ValueError("destination cannot be the source")
    if source.is_dir():
        try:
            destination_resolved.relative_to(source_resolved)
        except ValueError:
            pass
        else:
            raise ValueError("destination cannot be nested inside source")
        target_resolved = (destination_resolved / source.name).resolve(strict=False)
        if (
            str(target_resolved).casefold() == str(source_resolved).casefold()
            if os.name == "nt"
            else target_resolved == source_resolved
        ):
            raise ValueError("destination folder would resolve to the source itself")

    mode = str(verify_mode or "size").casefold()
    if mode not in {"size", "sha256"}:
        raise ValueError("verify_mode must be size or sha256")
    delete_after = bool(delete_source_after_verify)
    if delete_after:
        mode = "sha256"

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

    source_endpoint = bind_local_volume({"kind": "local", "path": str(source)})
    destination_endpoint = bind_local_volume({"kind": "local", "path": str(destination)})

    job_id = uuid.uuid4().hex
    created = _now()
    job = {
        "id": job_id,
        "type": "streamcopy_experimental",
        "status": "planning",
        "source_path": str(source),
        "destination_path": str(destination),
        "source_endpoint": source_endpoint,
        "destination_endpoint": destination_endpoint,
        "profile": profile,
        "verify_mode": mode,
        "delete_source_after_verify": delete_after,
        "target_root": None,
        "current_item_index": None,
        "current_path": "",
        "bytes": 0,
        "total_bytes": 0,
        "files": 0,
        "total_files": 0,
        "skipped": 0,
        "skipped_bytes": 0,
        "manifest_files": 0,
        "manifest_directories": 0,
        "warnings": [],
        "error": None,
        "progress_percent": 0.0,
        "average_mib_s": 0.0,
        "wait_cycles": 0,
        "auto_resumes": 0,
        "waiting_since": None,
        "lease_owner": _INSTANCE_ID,
        "lease_expires_at": time.time() + LEASE_SECONDS,
        "created_at": created,
        "updated_at": created,
        "finished_at": None,
        "persistent": True,
    }
    journal.create_job(job)
    _cache_job(job)
    if not journal.claim_job(job_id, _INSTANCE_ID, LEASE_SECONDS):
        raise RuntimeError("could not claim new StreamCopy job")
    _spawn_claimed_job(job_id)
    log_event(
        "streamcopy.started",
        job_id=job_id,
        source=source,
        destination=destination,
        strategy=profile["strategy"],
        verify_mode=mode,
        delete_source_after_verify=delete_after,
        checkpoint_mib=CHECKPOINT_BYTES // (1024 * 1024),
    )
    return get_streamcopy_job(job_id)


def get_streamcopy_job(job_id: str) -> dict[str, Any]:
    job = journal.get_job(job_id)
    with _lock:
        live = _jobs.get(job_id)
        if live is not None:
            for key in (
                "bytes",
                "progress_percent",
                "average_mib_s",
                "current_path",
                "status",
                "error",
            ):
                if key in live:
                    job[key] = live[key]
    return _public_job(job)


def list_streamcopy_jobs(
    *,
    active_only: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    values = journal.list_jobs(active_only=active_only, limit=limit)
    with _lock:
        for value in values:
            live = _jobs.get(value["id"])
            if live is None:
                continue
            for key in (
                "bytes",
                "progress_percent",
                "average_mib_s",
                "current_path",
                "status",
                "error",
            ):
                if key in live:
                    value[key] = live[key]
    return [_public_job(value) for value in values]


def cancel_streamcopy_job(job_id: str) -> dict[str, Any]:
    job = journal.get_job(job_id)
    if job["status"] in TERMINAL_STATES:
        return _public_job(job)

    with _lock:
        event = _cancel_events.get(job_id)
    if event is not None:
        event.set()
        return get_streamcopy_job(job_id)

    if not journal.claim_job(job_id, _INSTANCE_ID, LEASE_SECONDS):
        raise RuntimeError("StreamCopy job is currently owned by another backend instance")
    _persist_job(
        job_id,
        status="cancelled",
        error="Operation cancelled by operator",
        finished_at=_now(),
    )
    journal.release_lease(job_id, _INSTANCE_ID)
    return get_streamcopy_job(job_id)
