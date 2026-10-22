from __future__ import annotations

import os
import shutil
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings
from backend.files.service import FileWriteBlocked


class FileOperationCancelled(RuntimeError):
    pass


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check_cancel(event: threading.Event) -> None:
    if event.is_set():
        raise FileOperationCancelled("File operation cancelled by operator")


def _same_volume(source: Path, destination: Path) -> bool:
    if os.name == "nt":
        return source.drive.casefold() == destination.drive.casefold()
    try:
        anchor = destination
        while not anchor.exists() and anchor.parent != anchor:
            anchor = anchor.parent
        return source.stat().st_dev == anchor.stat().st_dev
    except OSError:
        return False


def start_file_job(operation: str, source: str, destination: str) -> dict[str, Any]:
    if not settings.allow_file_writes:
        raise FileWriteBlocked("DS_ALLOW_FILE_WRITES is disabled")
    if operation not in {"copy", "move"}:
        raise ValueError("operation must be copy or move")

    src = Path(source).expanduser().resolve(strict=True)
    dst = Path(destination).expanduser().resolve()
    if dst.exists():
        raise FileExistsError(dst)

    job_id = uuid.uuid4().hex
    event = threading.Event()
    job: dict[str, Any] = {
        "id": job_id,
        "type": "file_operation",
        "operation": operation,
        "source": str(src),
        "destination": str(dst),
        "status": "queued",
        "files": 0,
        "bytes": 0,
        "total_files": None,
        "total_bytes": None,
        "progress_percent": None,
        "current_path": str(src),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "cancel_requested": False,
    }
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = event

    threading.Thread(
        target=_run_job,
        args=(job_id, operation, src, dst, event),
        daemon=True,
        name=f"fileop-{job_id[:8]}",
    ).start()
    return get_file_job(job_id)


def _update(job_id: str, **values: Any) -> None:
    with _lock:
        _jobs[job_id].update(values)


def _refresh_percent(job_id: str) -> None:
    with _lock:
        job = _jobs[job_id]
        total = int(job.get("total_bytes") or 0)
        copied = int(job.get("bytes") or 0)
        job["progress_percent"] = (
            min(100.0, copied * 100.0 / total) if total > 0 else None
        )


def _measure_source(source: Path, event: threading.Event) -> tuple[int, int]:
    _check_cancel(event)
    if source.is_file():
        return 1, int(source.stat().st_size)

    files_count = 0
    bytes_total = 0
    for root, dirs, files in os.walk(source, followlinks=False):
        _check_cancel(event)
        root_path = Path(root)

        kept_dirs: list[str] = []
        for name in dirs:
            child = root_path / name
            if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                continue
            kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in files:
            _check_cancel(event)
            child = root_path / name
            if child.is_symlink():
                continue
            try:
                bytes_total += int(child.stat().st_size)
                files_count += 1
            except (FileNotFoundError, PermissionError, OSError):
                continue
    return files_count, bytes_total


def _copy_file(
    job_id: str,
    source: Path,
    destination: Path,
    event: threading.Event,
) -> None:
    partial = destination.with_name(
        f".{destination.name}.diskshell-partial-{uuid.uuid4().hex}"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with source.open("rb") as src, partial.open("xb") as dst:
            while True:
                _check_cancel(event)
                chunk = src.read(8 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)
                with _lock:
                    job = _jobs[job_id]
                    job["bytes"] += len(chunk)
                    job["current_path"] = str(source)
                _refresh_percent(job_id)
            dst.flush()
            os.fsync(dst.fileno())

        shutil.copystat(source, partial, follow_symlinks=False)
        if partial.stat().st_size != source.stat().st_size:
            raise OSError("Copied file size verification failed")

        _check_cancel(event)
        os.replace(partial, destination)
        with _lock:
            _jobs[job_id]["files"] += 1
    finally:
        if partial.exists():
            partial.unlink(missing_ok=True)


def _copy_tree(
    job_id: str,
    source: Path,
    destination: Path,
    event: threading.Event,
) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        for root, dirs, files in os.walk(source, followlinks=False):
            _check_cancel(event)
            root_path = Path(root)
            relative = root_path.relative_to(source)
            target_root = destination / relative
            target_root.mkdir(parents=True, exist_ok=True)

            kept_dirs: list[str] = []
            for name in dirs:
                child = root_path / name
                if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                    continue
                kept_dirs.append(name)
                (target_root / name).mkdir(parents=True, exist_ok=True)
            dirs[:] = kept_dirs

            for name in files:
                _check_cancel(event)
                child = root_path / name
                if child.is_symlink():
                    continue
                _copy_file(job_id, child, target_root / name, event)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise


def _copy(job_id: str, source: Path, destination: Path, event: threading.Event) -> None:
    if source.is_dir():
        _copy_tree(job_id, source, destination, event)
    else:
        _copy_file(job_id, source, destination, event)


def _run_job(
    job_id: str,
    operation: str,
    source: Path,
    destination: Path,
    event: threading.Event,
) -> None:
    _update(job_id, status="measuring", started_at=_now())
    try:
        _check_cancel(event)
        total_files, total_bytes = _measure_source(source, event)
        _update(
            job_id,
            total_files=total_files,
            total_bytes=total_bytes,
            progress_percent=0.0 if total_bytes > 0 else None,
            status="running",
        )

        if operation == "move" and _same_volume(source, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            _check_cancel(event)
            os.replace(source, destination)
            _update(
                job_id,
                files=total_files,
                bytes=total_bytes,
                progress_percent=100.0,
                current_path=str(destination),
            )
        else:
            _copy(job_id, source, destination, event)
            _check_cancel(event)
            if operation == "move":
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()

    except FileOperationCancelled:
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination, ignore_errors=True)
            else:
                destination.unlink(missing_ok=True)
        _update(job_id, status="cancelled", finished_at=_now())
        return
    except Exception as exc:  # noqa: BLE001
        if destination.exists() and operation == "move":
            try:
                if destination.is_dir():
                    shutil.rmtree(destination, ignore_errors=True)
                else:
                    destination.unlink(missing_ok=True)
            except OSError:
                pass
        _update(
            job_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
            finished_at=_now(),
        )
        return
    finally:
        with _lock:
            _cancel_events.pop(job_id, None)

    _update(job_id, status="completed", progress_percent=100.0, finished_at=_now())


def cancel_file_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] in {"completed", "failed", "cancelled"}:
            return deepcopy(job)
        event = _cancel_events.get(job_id)
        if event is not None:
            event.set()
        job["cancel_requested"] = True
        job["status"] = "cancelling"
        return deepcopy(job)


def get_file_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)
