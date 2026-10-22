from __future__ import annotations

import os
import shutil
import threading
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from backend.files.service import FileWriteBlocked
from backend.files.write_authorization import file_writes_allowed
from backend.remote.service import RemoteNotFound, open_session


CHUNK_SIZE = 8 * 1024 * 1024


class CommanderCancelled(RuntimeError):
    pass


_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}
_cancel_events: dict[str, threading.Event] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check_cancel(event: threading.Event) -> None:
    if event.is_set():
        raise CommanderCancelled("Operation cancelled by operator")


def _local_path(endpoint: dict[str, Any], strict: bool = False) -> Path:
    value = Path(str(endpoint["path"])).expanduser()
    return value.resolve(strict=strict)


def _remote_path(endpoint: dict[str, Any]) -> str:
    raw = str(endpoint["path"] or "/").replace("\\", "/")
    if not raw.startswith("/"):
        raw = "/" + raw
    return str(PurePosixPath(raw))


def _public_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    result = {"kind": endpoint["kind"], "path": str(endpoint["path"])}
    if endpoint["kind"] == "remote":
        result["connection_id"] = endpoint["connection_id"]
    return result


def _validate_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    kind = str(endpoint.get("kind", "")).casefold()
    if kind not in {"local", "remote"}:
        raise ValueError("endpoint kind must be local or remote")
    if not endpoint.get("path"):
        raise ValueError("endpoint path is required")
    result = {"kind": kind, "path": str(endpoint["path"])}
    if kind == "remote":
        connection_id = str(endpoint.get("connection_id") or "")
        if not connection_id:
            raise ValueError("remote endpoint requires connection_id")
        result["connection_id"] = connection_id
    return result


def _same_native_location(source: dict[str, Any], destination: dict[str, Any]) -> bool:
    if source["kind"] != destination["kind"]:
        return False
    if source["kind"] == "remote":
        return source["connection_id"] == destination["connection_id"]
    source_path = _local_path(source, strict=True)
    destination_path = _local_path(destination)
    if os.name == "nt":
        return source_path.drive.casefold() == destination_path.drive.casefold()
    anchor = destination_path
    while not anchor.exists() and anchor.parent != anchor:
        anchor = anchor.parent
    try:
        return source_path.stat().st_dev == anchor.stat().st_dev
    except OSError:
        return False


def _local_manifest(source: Path) -> tuple[bool, list[str], list[tuple[str, int]]]:
    if source.is_file():
        return False, [], [("", int(source.stat().st_size))]
    if not source.is_dir():
        raise FileNotFoundError(source)

    directories = [""]
    files: list[tuple[str, int]] = []
    for root, dirs, names in os.walk(source, followlinks=False):
        root_path = Path(root)
        rel_dir = root_path.relative_to(source)
        rel_text = "" if str(rel_dir) == "." else rel_dir.as_posix()

        kept: list[str] = []
        for name in dirs:
            child = root_path / name
            if child.is_symlink() or getattr(child, "is_junction", lambda: False)():
                continue
            kept.append(name)
            relative = f"{rel_text}/{name}".strip("/")
            directories.append(relative)
        dirs[:] = kept

        for name in names:
            child = root_path / name
            if child.is_symlink():
                continue
            try:
                size = int(child.stat().st_size)
            except (FileNotFoundError, PermissionError, OSError):
                continue
            relative = f"{rel_text}/{name}".strip("/")
            files.append((relative, size))

    directories.sort()
    files.sort()
    return True, directories, files


def _source_manifest(endpoint: dict[str, Any]):
    if endpoint["kind"] == "local":
        source = _local_path(endpoint, strict=True)
        return _local_manifest(source)

    with open_session(endpoint["connection_id"]) as session:
        path = _remote_path(endpoint)
        entry = session.stat(path)
        if not entry.is_dir:
            return False, [], [("", int(entry.size))]
        directories, files = session.walk(path)
        return True, directories, files


def _destination_exists(endpoint: dict[str, Any]) -> bool:
    if endpoint["kind"] == "local":
        return _local_path(endpoint).exists()
    try:
        with open_session(endpoint["connection_id"]) as session:
            session.stat(_remote_path(endpoint))
        return True
    except RemoteNotFound:
        return False


def _join_endpoint(root: dict[str, Any], relative: str) -> dict[str, Any]:
    if not relative:
        return dict(root)
    if root["kind"] == "local":
        path = _local_path(root) / Path(relative)
        return {**root, "path": str(path)}
    path = str(PurePosixPath(_remote_path(root)) / PurePosixPath(relative))
    return {**root, "path": path}


def _make_directory(endpoint: dict[str, Any]) -> None:
    if endpoint["kind"] == "local":
        _local_path(endpoint).mkdir(parents=True, exist_ok=True)
        return
    with open_session(endpoint["connection_id"]) as session:
        session.makedirs(_remote_path(endpoint))


def _delete_endpoint(endpoint: dict[str, Any]) -> None:
    if endpoint["kind"] == "local":
        path = _local_path(endpoint)
        if not path.exists():
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return
    with open_session(endpoint["connection_id"]) as session:
        try:
            session.delete_tree(_remote_path(endpoint))
        except RemoteNotFound:
            return


def _rename_native(source: dict[str, Any], destination: dict[str, Any]) -> None:
    if source["kind"] == "local":
        src = _local_path(source, strict=True)
        dst = _local_path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        return
    with open_session(source["connection_id"]) as session:
        parent = str(PurePosixPath(_remote_path(destination)).parent)
        session.makedirs(parent)
        session.rename(_remote_path(source), _remote_path(destination))


def _copy_file(
    source: dict[str, Any],
    destination: dict[str, Any],
    event: threading.Event,
    progress,
) -> None:
    if destination["kind"] == "local":
        path = _local_path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        destination_stream = path.open("xb")
        destination_session = None
    else:
        destination_session = open_session(destination["connection_id"]).__enter__()
        parent = str(PurePosixPath(_remote_path(destination)).parent)
        destination_session.makedirs(parent)
        destination_stream = destination_session.open_write(_remote_path(destination))

    try:
        if source["kind"] == "local":
            source_stream = _local_path(source, strict=True).open("rb")
            source_session = None
        else:
            source_session = open_session(source["connection_id"]).__enter__()
            source_stream = source_session.open_read(_remote_path(source))

        try:
            with source_stream, destination_stream:
                while True:
                    _check_cancel(event)
                    chunk = source_stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    destination_stream.write(chunk)
                    destination_stream.flush()
                    progress(len(chunk), source["path"])
        finally:
            if source_session is not None:
                source_session.__exit__(None, None, None)
    finally:
        if destination_session is not None:
            destination_session.__exit__(None, None, None)


def _verify_size(endpoint: dict[str, Any], expected: int) -> None:
    if endpoint["kind"] == "local":
        actual = int(_local_path(endpoint, strict=True).stat().st_size)
    else:
        with open_session(endpoint["connection_id"]) as session:
            actual = int(session.stat(_remote_path(endpoint)).size)
    if actual != int(expected):
        raise OSError(f"Size verification failed: expected {expected}, got {actual}")


def _remove_source_after_move(endpoint: dict[str, Any]) -> None:
    _delete_endpoint(endpoint)


def start_commander_job(
    operation: str,
    source: dict[str, Any],
    destination: dict[str, Any],
) -> dict[str, Any]:
    if not file_writes_allowed():
        raise FileWriteBlocked("File writes are locked")

    op = str(operation).casefold()
    if op not in {"copy", "move"}:
        raise ValueError("operation must be copy or move")

    src = _validate_endpoint(source)
    dst = _validate_endpoint(destination)
    if _destination_exists(dst):
        raise FileExistsError(dst["path"])

    is_dir, directories, files = _source_manifest(src)
    total_bytes = sum(size for _relative, size in files)

    job_id = uuid.uuid4().hex
    event = threading.Event()
    job = {
        "id": job_id,
        "type": "commander_transfer",
        "operation": op,
        "source": _public_endpoint(src),
        "destination": _public_endpoint(dst),
        "status": "queued",
        "is_dir": is_dir,
        "files": 0,
        "total_files": len(files),
        "bytes": 0,
        "total_bytes": total_bytes,
        "progress_percent": 0.0 if total_bytes else None,
        "current_path": src["path"],
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
        args=(job_id, op, src, dst, is_dir, directories, files, event),
        daemon=True,
        name=f"commander-{job_id[:8]}",
    ).start()
    return get_commander_job(job_id)


def _run_job(
    job_id: str,
    operation: str,
    source: dict[str, Any],
    destination: dict[str, Any],
    is_dir: bool,
    directories: list[str],
    files: list[tuple[str, int]],
    event: threading.Event,
) -> None:
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = _now()

    created_target = False

    def progress(count: int, current_path: str) -> None:
        with _lock:
            job = _jobs[job_id]
            job["bytes"] += int(count)
            job["current_path"] = current_path
            total = int(job["total_bytes"] or 0)
            job["progress_percent"] = (
                min(100.0, job["bytes"] * 100.0 / total) if total else None
            )

    try:
        _check_cancel(event)

        if operation == "move" and _same_native_location(source, destination):
            _rename_native(source, destination)
            created_target = True
            with _lock:
                job = _jobs[job_id]
                job["bytes"] = job["total_bytes"]
                job["files"] = job["total_files"]
                job["progress_percent"] = 100.0
                job["current_path"] = destination["path"]
        else:
            if is_dir:
                _make_directory(destination)
                created_target = True
                for relative in directories:
                    if relative:
                        _make_directory(_join_endpoint(destination, relative))
            else:
                created_target = True

            for relative, expected_size in files:
                _check_cancel(event)
                source_file = _join_endpoint(source, relative)
                destination_file = _join_endpoint(destination, relative)
                _copy_file(source_file, destination_file, event, progress)
                _verify_size(destination_file, expected_size)
                with _lock:
                    _jobs[job_id]["files"] += 1

            _check_cancel(event)
            if operation == "move":
                _remove_source_after_move(source)

    except CommanderCancelled:
        if created_target:
            try:
                _delete_endpoint(destination)
            except Exception:  # noqa: BLE001
                pass
        with _lock:
            job = _jobs[job_id]
            job["status"] = "cancelled"
            job["finished_at"] = _now()
        return
    except Exception as exc:  # noqa: BLE001
        if created_target:
            try:
                _delete_endpoint(destination)
            except Exception:  # noqa: BLE001
                pass
        with _lock:
            job = _jobs[job_id]
            job["status"] = "failed"
            job["error"] = f"{type(exc).__name__}: {exc}"
            job["finished_at"] = _now()
        return
    finally:
        with _lock:
            _cancel_events.pop(job_id, None)

    with _lock:
        job = _jobs[job_id]
        job["status"] = "completed"
        job["progress_percent"] = 100.0
        job["finished_at"] = _now()


def get_commander_job(job_id: str) -> dict[str, Any]:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return deepcopy(job)


def cancel_commander_job(job_id: str) -> dict[str, Any]:
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
