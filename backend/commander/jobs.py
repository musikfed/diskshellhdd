from __future__ import annotations

import os
import shutil
import threading
import uuid
from contextlib import ExitStack
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from backend.files.endpoint_availability import (
    bind_local_volume,
    local_endpoint_state,
)
from backend.files.service import FileWriteBlocked
from backend.files.write_authorization import file_writes_allowed
from backend.remote.service import (
    RemoteConnectionError,
    RemoteNotFound,
    open_session,
    profile_identity,
)


CHUNK_SIZE = 8 * 1024 * 1024
TRANSFER_RETRY_LIMIT = 4
TRANSFER_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)
ENDPOINT_RECHECK_SECONDS = 3.0
WINDOWS_ENDPOINT_LOSS_ERRORS = {3, 21, 53, 64, 1117, 1167}


class CommanderCancelled(RuntimeError):
    pass


class CommanderConflict(RuntimeError):
    def __init__(self, conflicts: list[dict[str, Any]]):
        super().__init__(f"{len(conflicts)} destination conflict(s)")
        self.conflicts = conflicts


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
        result["remote_identity"] = profile_identity(connection_id)
        return result
    return bind_local_volume(result)


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


def _destination_info(endpoint: dict[str, Any]) -> dict[str, Any]:
    if endpoint["kind"] == "local":
        path = _local_path(endpoint)
        if not path.exists():
            return {"exists": False, "is_dir": False, "size": None}
        return {
            "exists": True,
            "is_dir": path.is_dir(),
            "size": None if path.is_dir() else int(path.stat().st_size),
        }

    try:
        with open_session(endpoint["connection_id"]) as session:
            entry = session.stat(_remote_path(endpoint))
    except RemoteNotFound:
        return {"exists": False, "is_dir": False, "size": None}
    return {
        "exists": True,
        "is_dir": bool(entry.is_dir),
        "size": None if entry.is_dir else int(entry.size),
    }


def _destination_exists(endpoint: dict[str, Any]) -> bool:
    return bool(_destination_info(endpoint)["exists"])


def _indexed_destination(
    endpoint: dict[str, Any],
    reserved: set[tuple[str, str, str]] | None = None,
    is_dir: bool = False,
) -> dict[str, Any]:
    reserved = reserved or set()
    if endpoint["kind"] == "local":
        path = _local_path(endpoint)
        suffix = (
            ""
            if is_dir
            else path.suffix if path.suffix and path.name != path.suffix else ""
        )
        base = path.name[:-len(suffix)] if suffix else path.name
        for index in range(1, 10000):
            candidate = path.with_name(f"{base} ({index}){suffix}")
            result = {**endpoint, "path": str(candidate)}
            if not _destination_exists(result) and _endpoint_key(result) not in reserved:
                return result
    else:
        path = PurePosixPath(_remote_path(endpoint))
        suffix = (
            ""
            if is_dir
            else path.suffix if path.suffix and path.name != path.suffix else ""
        )
        base = path.name[:-len(suffix)] if suffix else path.name
        for index in range(1, 10000):
            candidate = path.with_name(f"{base} ({index}){suffix}")
            result = {**endpoint, "path": str(candidate)}
            if not _destination_exists(result) and _endpoint_key(result) not in reserved:
                return result
    raise RuntimeError("Could not allocate indexed destination name")


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


def _source_exists(endpoint: dict[str, Any]) -> bool:
    if endpoint["kind"] == "local":
        return _local_path(endpoint).exists()
    try:
        with open_session(endpoint["connection_id"]) as session:
            session.stat(_remote_path(endpoint))
        return True
    except RemoteNotFound:
        return False


def _is_missing_error(exc: Exception) -> bool:
    return isinstance(exc, (FileNotFoundError, RemoteNotFound)) or getattr(
        exc, "errno", None
    ) == 2


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


def _partial_destination_size(endpoint: dict[str, Any]) -> int:
    if endpoint["kind"] == "local":
        path = _local_path(endpoint)
        if not path.exists():
            return 0
        if not path.is_file():
            raise IsADirectoryError(path)
        return int(path.stat().st_size)

    try:
        with open_session(endpoint["connection_id"]) as session:
            entry = session.stat(_remote_path(endpoint))
    except RemoteNotFound:
        return 0
    if entry.is_dir:
        raise IsADirectoryError(endpoint["path"])
    return int(entry.size)


def _ensure_zero_length_destination(endpoint: dict[str, Any]) -> None:
    if endpoint["kind"] == "local":
        path = _local_path(endpoint)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if not path.is_file():
                raise IsADirectoryError(path)
            if path.stat().st_size != 0:
                raise OSError(f"Expected empty target, got {path.stat().st_size} bytes")
            return
        path.touch(exist_ok=False)
        return

    with open_session(endpoint["connection_id"]) as session:
        path = _remote_path(endpoint)
        try:
            entry = session.stat(path)
        except RemoteNotFound:
            parent = str(PurePosixPath(path).parent)
            session.makedirs(parent)
            with session.open_write(path, offset=0):
                pass
            return
        if entry.is_dir:
            raise IsADirectoryError(endpoint["path"])
        if int(entry.size) != 0:
            raise OSError(f"Expected empty target, got {entry.size} bytes")


def _endpoint_state(
    endpoint: dict[str, Any],
    connect_remote: bool = True,
) -> dict[str, Any]:
    if endpoint["kind"] == "local":
        return local_endpoint_state(endpoint)

    expected = endpoint.get("remote_identity")
    current = None
    if expected:
        try:
            current = profile_identity(endpoint["connection_id"])
        except KeyError:
            return {
                "available": False,
                "reason": "remote_profile_missing",
                "expected_identity": expected,
                "current_identity": None,
            }
        if current != expected:
            return {
                "available": False,
                "reason": "remote_identity_mismatch",
                "expected_identity": expected,
                "current_identity": current,
            }

    if not connect_remote:
        return {
            "available": True,
            "reason": None,
            "expected_identity": expected,
            "current_identity": current,
        }

    try:
        with open_session(endpoint["connection_id"]):
            pass
    except KeyError:
        return {
            "available": False,
            "reason": "remote_profile_missing",
            "expected_identity": expected,
            "current_identity": current,
        }
    except RemoteConnectionError as exc:
        return {
            "available": False,
            "reason": "remote_offline",
            "message": str(exc),
            "expected_identity": expected,
            "current_identity": current,
        }
    return {
        "available": True,
        "reason": None,
        "expected_identity": expected,
        "current_identity": current,
    }


def _unavailable_endpoints(
    source: dict[str, Any],
    destination: dict[str, Any],
    connect_remote: bool = True,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for role, endpoint in (("source", source), ("destination", destination)):
        state = _endpoint_state(endpoint, connect_remote=connect_remote)
        if not state.get("available"):
            result.append(
                {
                    "role": role,
                    "kind": endpoint["kind"],
                    "path": endpoint["path"],
                    "reason": state.get("reason") or "endpoint_offline",
                    "root": state.get("root"),
                    "message": state.get("message"),
                    "expected_identity": state.get("expected_identity"),
                    "current_identity": state.get("current_identity"),
                }
            )
    return result


def _looks_like_endpoint_loss(exc: Exception) -> bool:
    winerror = getattr(exc, "winerror", None)
    if winerror in WINDOWS_ENDPOINT_LOSS_ERRORS:
        return True
    return isinstance(
        exc,
        (
            RemoteConnectionError,
            ConnectionError,
            TimeoutError,
            EOFError,
        ),
    )


def _wait_for_endpoints(
    source: dict[str, Any],
    destination: dict[str, Any],
    event: threading.Event,
    wait_status,
    current_path: str,
    error: str,
) -> None:
    while True:
        _check_cancel(event)
        unavailable = _unavailable_endpoints(source, destination, connect_remote=True)
        if not unavailable:
            wait_status(False, [], current_path, error)
            return
        wait_status(True, unavailable, current_path, error)
        if event.wait(ENDPOINT_RECHECK_SECONDS):
            raise CommanderCancelled("Operation cancelled by operator")


def _run_endpoint_operation(
    action,
    source: dict[str, Any],
    destination: dict[str, Any],
    event: threading.Event,
    wait_status,
    current_path: str,
):
    while True:
        unavailable = _unavailable_endpoints(
            source,
            destination,
            connect_remote=False,
        )
        if unavailable:
            _wait_for_endpoints(
                source,
                destination,
                event,
                wait_status,
                current_path,
                "endpoint unavailable",
            )
        try:
            return action()
        except CommanderCancelled:
            raise
        except Exception as exc:
            unavailable = _unavailable_endpoints(
                source,
                destination,
                connect_remote=True,
            )
            if unavailable or _looks_like_endpoint_loss(exc):
                _wait_for_endpoints(
                    source,
                    destination,
                    event,
                    wait_status,
                    current_path,
                    f"{type(exc).__name__}: {exc}",
                )
                continue
            raise


def _retryable_transfer_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            CommanderCancelled,
            PermissionError,
            FileNotFoundError,
            FileExistsError,
            IsADirectoryError,
            NotADirectoryError,
            ValueError,
        ),
    ):
        return False
    if isinstance(
        exc,
        (
            RemoteConnectionError,
            ConnectionError,
            TimeoutError,
            EOFError,
            OSError,
        ),
    ):
        return True
    # Paramiko raises SSHException/ChannelException directly for some transport
    # failures during an already-open SFTPFile read/write.
    return exc.__class__.__module__.startswith("paramiko")


def _copy_file(
    source: dict[str, Any],
    destination: dict[str, Any],
    expected_size: int,
    event: threading.Event,
    progress,
    retry_status,
    wait_status,
) -> None:
    has_remote = source["kind"] == "remote" or destination["kind"] == "remote"
    reported = 0
    retries = 0

    while True:
        _check_cancel(event)
        unavailable = _unavailable_endpoints(
            source,
            destination,
            connect_remote=False,
        )
        if unavailable:
            _wait_for_endpoints(
                source,
                destination,
                event,
                wait_status,
                source["path"],
                "endpoint unavailable before transfer",
            )
            retries = 0

        try:
            offset = _partial_destination_size(destination)
            if int(expected_size) == 0:
                _ensure_zero_length_destination(destination)
                return
            if offset > int(expected_size):
                raise OSError(
                    f"Partial target is larger than source: {offset} > {expected_size}"
                )
            if offset != reported:
                progress(offset - reported, source["path"])
                reported = offset

            # A disconnect can happen while closing the remote stream after all
            # data reached the server. Do not retransmit an already-complete file.
            if offset == int(expected_size):
                return

            with ExitStack() as stack:
                if source["kind"] == "local":
                    source_stream = stack.enter_context(
                        _local_path(source, strict=True).open("rb")
                    )
                    source_stream.seek(offset)
                else:
                    source_session = stack.enter_context(
                        open_session(source["connection_id"])
                    )
                    source_stream = stack.enter_context(
                        source_session.open_read(_remote_path(source), offset=offset)
                    )

                if destination["kind"] == "local":
                    path = _local_path(destination)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    mode = "r+b" if path.exists() else "xb"
                    destination_stream = stack.enter_context(path.open(mode))
                    destination_stream.seek(offset)
                else:
                    destination_session = stack.enter_context(
                        open_session(destination["connection_id"])
                    )
                    parent = str(PurePosixPath(_remote_path(destination)).parent)
                    destination_session.makedirs(parent)
                    destination_stream = stack.enter_context(
                        destination_session.open_write(
                            _remote_path(destination),
                            offset=offset,
                        )
                    )

                while reported < int(expected_size):
                    _check_cancel(event)
                    remaining = int(expected_size) - reported
                    chunk = source_stream.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    destination_stream.write(chunk)
                    destination_stream.flush()
                    reported += len(chunk)
                    progress(len(chunk), source["path"])

            return
        except CommanderCancelled:
            raise
        except Exception as exc:
            unavailable = _unavailable_endpoints(
                source,
                destination,
                connect_remote=True,
            )
            if unavailable:
                _wait_for_endpoints(
                    source,
                    destination,
                    event,
                    wait_status,
                    source["path"],
                    f"{type(exc).__name__}: {exc}",
                )
                retries = 0
                continue

            retryable = _retryable_transfer_error(exc) or _looks_like_endpoint_loss(exc)
            if not retryable or (not has_remote and not _looks_like_endpoint_loss(exc)):
                raise

            if retries < TRANSFER_RETRY_LIMIT:
                retries += 1
                retry_status(
                    retries,
                    TRANSFER_RETRY_LIMIT,
                    reported,
                    f"{type(exc).__name__}: {exc}",
                    source["path"],
                )
                delay = TRANSFER_RETRY_BACKOFF_SECONDS[
                    min(retries - 1, len(TRANSFER_RETRY_BACKOFF_SECONDS) - 1)
                ]
                if event.wait(delay):
                    raise CommanderCancelled("Operation cancelled by operator") from exc
                continue

            # Fast reconnect attempts are exhausted. Do not fail a multi-gigabyte
            # transfer: enter downloader-like waiting mode and keep the partial.
            wait_status(
                True,
                [
                    {
                        "role": "connection",
                        "kind": "remote" if has_remote else "local",
                        "path": source["path"],
                        "reason": "reconnect_backoff",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                ],
                source["path"],
                f"{type(exc).__name__}: {exc}",
            )
            if event.wait(ENDPOINT_RECHECK_SECONDS):
                raise CommanderCancelled("Operation cancelled by operator") from exc
            _wait_for_endpoints(
                source,
                destination,
                event,
                wait_status,
                source["path"],
                f"{type(exc).__name__}: {exc}",
            )
            retries = 0


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


def _endpoint_key(endpoint: dict[str, Any]) -> tuple[str, str, str]:
    if endpoint["kind"] == "local":
        path = str(_local_path(endpoint))
        if os.name == "nt":
            path = path.casefold()
        return ("local", "", path)
    return (
        "remote",
        str(endpoint["connection_id"]),
        _remote_path(endpoint),
    )


def _prepare_transfer(raw: dict[str, Any]) -> dict[str, Any]:
    src = _validate_endpoint(dict(raw["source"]))
    dst = _validate_endpoint(dict(raw["destination"]))
    try:
        is_dir, directories, files = _source_manifest(src)
        missing_source = False
    except (FileNotFoundError, RemoteNotFound):
        is_dir, directories, files = False, [], []
        missing_source = True

    destination_info = _destination_info(dst)
    same_as_source = _endpoint_key(src) == _endpoint_key(dst)
    source_size = (
        None
        if is_dir or missing_source
        else int(files[0][1]) if files else 0
    )
    can_resume = bool(
        destination_info["exists"]
        and not same_as_source
        and (
            (is_dir and destination_info["is_dir"])
            or (
                not is_dir
                and not destination_info["is_dir"]
                and source_size is not None
                and destination_info["size"] is not None
                and int(destination_info["size"]) <= int(source_size)
            )
        )
    )
    return {
        "source": src,
        "destination": dst,
        "original_destination": dict(dst),
        "is_dir": is_dir,
        "directories": directories,
        "files": files,
        "total_files": len(files),
        "total_bytes": sum(size for _relative, size in files),
        "missing_source": missing_source,
        "destination_info": destination_info,
        "same_as_source": same_as_source,
        "can_resume": can_resume,
        "skip_before_run": False,
        "replace_existing": False,
        "resume_existing": False,
        "conflict_resolution": None,
    }


def _conflict_payload(item: dict[str, Any]) -> dict[str, Any]:
    info = item["destination_info"]
    return {
        "source": _public_endpoint(item["source"]),
        "destination": _public_endpoint(item["destination"]),
        "is_dir": bool(item["is_dir"]),
        "source_size": None if item["is_dir"] else int(item["total_bytes"]),
        "destination_size": info["size"],
        "destination_is_dir": bool(info["is_dir"]),
        "can_resume": bool(item["can_resume"]),
        "same_as_source": bool(item["same_as_source"]),
    }


def _apply_conflict_policy(
    prepared: list[dict[str, Any]],
    policy: str,
) -> list[dict[str, Any]]:
    conflicts = [
        item
        for item in prepared
        if item["destination_info"]["exists"] and not item["missing_source"]
    ]
    if policy == "ask" and conflicts:
        raise CommanderConflict([_conflict_payload(item) for item in conflicts[:200]])

    reserved: set[tuple[str, str, str]] = set()
    for item in prepared:
        if item["missing_source"]:
            continue
        exists = bool(item["destination_info"]["exists"])
        if not exists:
            reserved.add(_endpoint_key(item["destination"]))
            continue
        if policy == "skip":
            item["skip_before_run"] = True
            item["conflict_resolution"] = "skip"
            continue
        if policy == "keep_both":
            item["destination"] = _indexed_destination(
                item["destination"],
                reserved,
                is_dir=bool(item["is_dir"]),
            )
            item["conflict_resolution"] = "keep_both"
            reserved.add(_endpoint_key(item["destination"]))
            continue
        if policy == "replace":
            if item["same_as_source"]:
                raise ValueError("Cannot replace a destination that is the source itself")
            item["replace_existing"] = True
            item["conflict_resolution"] = "replace"
            reserved.add(_endpoint_key(item["destination"]))
            continue
        if policy == "resume":
            if not item["can_resume"]:
                raise CommanderConflict([_conflict_payload(item)])
            item["resume_existing"] = True
            item["conflict_resolution"] = "resume"
            reserved.add(_endpoint_key(item["destination"]))
            continue
        raise ValueError(f"Unsupported conflict policy: {policy}")

    return prepared


def start_commander_batch_job(
    operation: str,
    transfers: list[dict[str, Any]],
    conflict_policy: str = "ask",
) -> dict[str, Any]:
    if not file_writes_allowed():
        raise FileWriteBlocked("File writes are locked")

    op = str(operation).casefold()
    if op not in {"copy", "move"}:
        raise ValueError("operation must be copy or move")
    if not isinstance(transfers, list) or not transfers:
        raise ValueError("at least one transfer is required")
    if len(transfers) > 4000:
        raise ValueError("too many transfer items; maximum is 4000")

    policy = str(conflict_policy or "ask").casefold()
    if policy not in {"ask", "replace", "keep_both", "resume", "skip"}:
        raise ValueError("conflict_policy must be ask, replace, keep_both, resume or skip")

    prepared = _apply_conflict_policy(
        [_prepare_transfer(dict(item)) for item in transfers],
        policy,
    )

    destination_keys = [
        _endpoint_key(item["destination"])
        for item in prepared
        if not item["skip_before_run"] and not item["missing_source"]
    ]
    if len(set(destination_keys)) != len(destination_keys):
        raise ValueError("batch contains duplicate destination paths")

    active_prepared = [
        item
        for item in prepared
        if not item["skip_before_run"] and not item["missing_source"]
    ]
    total_bytes = sum(int(item["total_bytes"]) for item in active_prepared)
    total_files = sum(int(item["total_files"]) for item in active_prepared)
    first = prepared[0]

    job_id = uuid.uuid4().hex
    event = threading.Event()
    job = {
        "id": job_id,
        "type": (
            "commander_transfer_batch"
            if len(prepared) > 1
            else "commander_transfer"
        ),
        "operation": op,
        "source": _public_endpoint(first["source"]),
        "destination": _public_endpoint(first["destination"]),
        "transfers": [
            {
                "source": _public_endpoint(item["source"]),
                "destination": _public_endpoint(item["destination"]),
                "is_dir": bool(item["is_dir"]),
                "total_files": int(item["total_files"]),
                "total_bytes": int(item["total_bytes"]),
                "missing_source": bool(item["missing_source"]),
                "conflict_resolution": item["conflict_resolution"],
            }
            for item in prepared
        ],
        "items": 0,
        "total_items": len(prepared),
        "files": 0,
        "total_files": total_files,
        "bytes": 0,
        "total_bytes": total_bytes,
        "progress_percent": 0.0 if total_bytes else None,
        "current_item": 0,
        "current_path": first["source"]["path"],
        "retries": 0,
        "retrying": False,
        "retry_attempt": 0,
        "retry_limit": TRANSFER_RETRY_LIMIT,
        "resume_offset": 0,
        "last_retry_error": None,
        "waiting_endpoint": False,
        "waiting_since": None,
        "waiting_for": [],
        "wait_cycles": 0,
        "auto_resumes": 0,
        "conflict_policy": policy,
        "skipped": 0,
        "missing": 0,
        "partial_retained": False,
        "partial_path": None,
        "warnings": [],
        "started_at": None,
        "finished_at": None,
        "error": None,
        "cancel_requested": False,
    }
    with _lock:
        _jobs[job_id] = job
        _cancel_events[job_id] = event

    threading.Thread(
        target=_run_batch_job,
        args=(job_id, op, prepared, event),
        daemon=True,
        name=f"commander-{job_id[:8]}",
    ).start()
    return get_commander_job(job_id)


def start_commander_job(
    operation: str,
    source: dict[str, Any],
    destination: dict[str, Any],
    conflict_policy: str = "ask",
) -> dict[str, Any]:
    """Backward-compatible single-object Commander job."""
    return start_commander_batch_job(
        operation,
        [{"source": source, "destination": destination}],
        conflict_policy=conflict_policy,
    )


def _run_batch_job(
    job_id: str,
    operation: str,
    transfers: list[dict[str, Any]],
    event: threading.Event,
) -> None:
    with _lock:
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["started_at"] = _now()

    def progress(count: int, current_path: str) -> None:
        with _lock:
            job = _jobs[job_id]
            job["bytes"] = max(0, job["bytes"] + int(count))
            job["current_path"] = current_path
            total = int(job["total_bytes"] or 0)
            job["progress_percent"] = (
                min(100.0, job["bytes"] * 100.0 / total)
                if total
                else None
            )

    def retry_status(
        attempt: int,
        retry_limit: int,
        resume_offset: int,
        error: str,
        current_path: str,
    ) -> None:
        with _lock:
            job = _jobs[job_id]
            job["retries"] += 1
            job["retrying"] = True
            job["retry_attempt"] = attempt
            job["retry_limit"] = retry_limit
            job["resume_offset"] = int(resume_offset)
            job["last_retry_error"] = error
            job["current_path"] = current_path

    def wait_status(
        waiting: bool,
        states: list[dict[str, Any]],
        current_path: str,
        error: str,
    ) -> None:
        with _lock:
            job = _jobs[job_id]
            was_waiting = bool(job["waiting_endpoint"])
            job["waiting_endpoint"] = bool(waiting)
            job["waiting_for"] = states
            job["current_path"] = current_path
            job["last_retry_error"] = error or job.get("last_retry_error")
            if waiting:
                if not was_waiting:
                    job["waiting_since"] = _now()
                    job["wait_cycles"] += 1
                job["status"] = "waiting_endpoint"
                job["retrying"] = False
            else:
                if was_waiting:
                    job["auto_resumes"] += 1
                job["waiting_since"] = None
                job["waiting_for"] = []
                job["status"] = "running"

    try:
        for index, transfer in enumerate(transfers, start=1):
            _check_cancel(event)
            source = transfer["source"]
            destination = transfer["destination"]
            is_dir = bool(transfer["is_dir"])
            directories = transfer["directories"]
            files = transfer["files"]
            created_target = False

            with _lock:
                job = _jobs[job_id]
                job["current_item"] = index
                job["current_path"] = source["path"]

            if transfer["missing_source"]:
                with _lock:
                    job = _jobs[job_id]
                    job["missing"] += 1
                    job["skipped"] += 1
                    job["items"] += 1
                    job["warnings"].append(
                        f"Source missing before transfer: {source['path']}"
                    )
                continue

            if transfer["skip_before_run"]:
                with _lock:
                    job = _jobs[job_id]
                    job["skipped"] += 1
                    job["items"] += 1
                    job["warnings"].append(
                        f"Destination conflict skipped: {destination['path']}"
                    )
                continue

            try:
                _wait_for_endpoints(
                    source,
                    destination,
                    event,
                    wait_status,
                    source["path"],
                    "endpoint unavailable",
                )
                if not _source_exists(source):
                    with _lock:
                        job = _jobs[job_id]
                        job["missing"] += 1
                        job["skipped"] += 1
                        job["items"] += 1
                        job["total_bytes"] = max(
                            0,
                            int(job["total_bytes"]) - int(transfer["total_bytes"]),
                        )
                        job["total_files"] = max(
                            0,
                            int(job["total_files"]) - int(transfer["total_files"]),
                        )
                        job["warnings"].append(
                            f"Source disappeared before transfer: {source['path']}"
                        )
                    continue

                if transfer["replace_existing"]:
                    _run_endpoint_operation(
                        lambda: _delete_endpoint(destination),
                        source,
                        destination,
                        event,
                        wait_status,
                        destination["path"],
                    )

                if (
                    operation == "move"
                    and not transfer["resume_existing"]
                    and _same_native_location(source, destination)
                ):
                    _run_endpoint_operation(
                        lambda: _rename_native(source, destination),
                        source,
                        destination,
                        event,
                        wait_status,
                        source["path"],
                    )
                    created_target = True
                    with _lock:
                        job = _jobs[job_id]
                        job["bytes"] += int(transfer["total_bytes"])
                        job["files"] += int(transfer["total_files"])
                        job["current_path"] = destination["path"]
                else:
                    if is_dir:
                        _run_endpoint_operation(
                            lambda: _make_directory(destination),
                            source,
                            destination,
                            event,
                            wait_status,
                            destination["path"],
                        )
                        created_target = True
                        for relative in directories:
                            if relative:
                                directory_endpoint = _join_endpoint(destination, relative)
                                _run_endpoint_operation(
                                    lambda endpoint=directory_endpoint: _make_directory(endpoint),
                                    source,
                                    directory_endpoint,
                                    event,
                                    wait_status,
                                    directory_endpoint["path"],
                                )
                    else:
                        created_target = True

                    for relative, expected_size in files:
                        _check_cancel(event)
                        source_file = _join_endpoint(source, relative)
                        destination_file = _join_endpoint(
                            destination,
                            relative,
                        )
                        with _lock:
                            _jobs[job_id]["current_path"] = source_file["path"]
                        destination_before = _run_endpoint_operation(
                            lambda: _destination_info(destination_file),
                            source_file,
                            destination_file,
                            event,
                            wait_status,
                            destination_file["path"],
                        )
                        try:
                            _copy_file(
                                source_file,
                                destination_file,
                                expected_size,
                                event,
                                progress,
                                retry_status,
                                wait_status,
                            )
                            _run_endpoint_operation(
                                lambda: _verify_size(destination_file, expected_size),
                                source_file,
                                destination_file,
                                event,
                                wait_status,
                                destination_file["path"],
                            )
                        except Exception as exc:
                            if _is_missing_error(exc):
                                if not destination_before["exists"]:
                                    try:
                                        _delete_endpoint(destination_file)
                                    except Exception:  # noqa: BLE001
                                        pass
                                with _lock:
                                    job = _jobs[job_id]
                                    job["missing"] += 1
                                    job["skipped"] += 1
                                    job["total_bytes"] = max(
                                        0,
                                        int(job["total_bytes"]) - int(expected_size),
                                    )
                                    job["total_files"] = max(
                                        0,
                                        int(job["total_files"]) - 1,
                                    )
                                    total = int(job["total_bytes"] or 0)
                                    job["progress_percent"] = (
                                        min(100.0, job["bytes"] * 100.0 / total)
                                        if total
                                        else 100.0
                                    )
                                    job["retrying"] = False
                                    job["retry_attempt"] = 0
                                    job["resume_offset"] = 0
                                    job["warnings"].append(
                                        f"Source file disappeared; skipped: {source_file['path']}"
                                    )
                                continue
                            raise
                        with _lock:
                            _jobs[job_id]["files"] += 1
                            _jobs[job_id]["retrying"] = False
                            _jobs[job_id]["retry_attempt"] = 0
                            _jobs[job_id]["resume_offset"] = 0
                            _jobs[job_id]["waiting_endpoint"] = False
                            _jobs[job_id]["waiting_since"] = None
                            _jobs[job_id]["waiting_for"] = []

                    _check_cancel(event)
                    if operation == "move":
                        _run_endpoint_operation(
                            lambda: _remove_source_after_move(source),
                            source,
                            destination,
                            event,
                            wait_status,
                            source["path"],
                        )

                with _lock:
                    job = _jobs[job_id]
                    job["items"] += 1
                    total = int(job["total_bytes"] or 0)
                    if total:
                        job["progress_percent"] = min(
                            100.0,
                            job["bytes"] * 100.0 / total,
                        )
            except Exception as exc:
                preserve_partial = isinstance(exc, CommanderCancelled) or (
                    _retryable_transfer_error(exc)
                    and (
                        source["kind"] == "remote"
                        or destination["kind"] == "remote"
                        or _looks_like_endpoint_loss(exc)
                    )
                )
                if preserve_partial and created_target:
                    with _lock:
                        job = _jobs[job_id]
                        job["partial_retained"] = True
                        job["partial_path"] = destination["path"]
                        job["warnings"].append(
                            f"Partial target retained for Continue: {destination['path']}"
                        )
                elif created_target and not transfer["resume_existing"]:
                    # Roll back only a newly-created incomplete destination.
                    # Never delete a user-confirmed existing resume target.
                    try:
                        _delete_endpoint(destination)
                    except Exception:  # noqa: BLE001
                        pass
                raise

    except CommanderCancelled:
        with _lock:
            job = _jobs[job_id]
            job["status"] = "cancelled"
            job["finished_at"] = _now()
        return
    except Exception as exc:  # noqa: BLE001
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
