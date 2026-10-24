from __future__ import annotations

import os
import posixpath
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from backend.files.endpoint_availability import bind_local_volume, local_endpoint_state
from backend.remote.service import (
    RemoteConnectionError,
    RemoteNotFound,
    find_profile_id_by_identity,
    list_profiles,
    open_session,
    profile_identity,
)


def normalize_remote_path(path: str) -> str:
    raw = str(path or "/").replace("\\", "/")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def make_endpoint(
    kind: str,
    path: str,
    connection_id: str | None = None,
) -> dict[str, Any]:
    endpoint_kind = str(kind or "local").casefold()
    if endpoint_kind == "local":
        return bind_local_volume({"kind": "local", "path": str(path)})
    if endpoint_kind != "remote":
        raise ValueError("StreamCopy endpoint kind must be local or remote")

    profile_id = str(connection_id or "")
    if not profile_id:
        raise ValueError("SFTP StreamCopy endpoint requires connection_id")
    profile = next(
        (item for item in list_profiles() if str(item["id"]) == profile_id),
        None,
    )
    if profile is None:
        raise KeyError(profile_id)
    if str(profile.get("protocol") or "").casefold() != "sftp":
        raise ValueError("Persistent Remote River supports SFTP only")
    return {
        "kind": "remote",
        "protocol": "sftp",
        "path": normalize_remote_path(path),
        "connection_id": profile_id,
        "remote_identity": profile_identity(profile_id),
    }


def rebind(endpoint: dict[str, Any]) -> dict[str, Any]:
    if endpoint.get("kind") != "remote":
        return endpoint
    expected = str(endpoint.get("remote_identity") or "")
    current = str(endpoint.get("connection_id") or "")
    if current:
        try:
            if profile_identity(current) == expected:
                return endpoint
        except KeyError:
            pass
    rebound = find_profile_id_by_identity(expected)
    if rebound:
        endpoint["connection_id"] = rebound
    return endpoint


def state(endpoint: dict[str, Any], *, connect_remote: bool = True) -> dict[str, Any]:
    if endpoint.get("kind") == "local":
        return local_endpoint_state(endpoint)

    endpoint = rebind(endpoint)
    expected = str(endpoint.get("remote_identity") or "")
    connection_id = str(endpoint.get("connection_id") or "")
    if not connection_id:
        return {
            "available": False,
            "reason": "remote_profile_missing",
            "expected_identity": expected,
            "current_identity": None,
        }
    try:
        current = profile_identity(connection_id)
    except KeyError:
        return {
            "available": False,
            "reason": "remote_profile_missing",
            "expected_identity": expected,
            "current_identity": None,
        }
    if expected and current != expected:
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
        with open_session(connection_id):
            pass
    except (KeyError, RemoteConnectionError, OSError) as exc:
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


def _local(path: str) -> Path:
    return Path(path).expanduser()


def stat(endpoint: dict[str, Any], path: str) -> dict[str, Any]:
    if endpoint.get("kind") == "local":
        value = _local(path)
        info = value.stat()
        return {
            "path": str(value),
            "name": value.name,
            "is_dir": value.is_dir(),
            "is_symlink": value.is_symlink(),
            "size": 0 if value.is_dir() else int(info.st_size),
            "modified_ns": int(info.st_mtime_ns),
        }

    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        entry = session.stat(normalize_remote_path(path))
    return {
        "path": entry.path,
        "name": entry.name,
        "is_dir": bool(entry.is_dir),
        "is_symlink": bool(getattr(entry, "is_symlink", False)),
        "size": int(entry.size),
        "modified_ns": entry.modified_ns,
    }


def exists(endpoint: dict[str, Any], path: str) -> bool:
    try:
        stat(endpoint, path)
        return True
    except (FileNotFoundError, RemoteNotFound):
        return False


def listdir(endpoint: dict[str, Any], path: str) -> list[dict[str, Any]]:
    if endpoint.get("kind") == "local":
        result = []
        for child in _local(path).iterdir():
            try:
                info = child.lstat()
            except OSError:
                continue
            is_link = child.is_symlink() or getattr(child, "is_junction", lambda: False)()
            is_dir = child.is_dir() if not is_link else False
            result.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": is_dir,
                    "is_symlink": bool(is_link),
                    "size": 0 if is_dir else int(info.st_size),
                    "modified_ns": int(info.st_mtime_ns),
                }
            )
        result.sort(key=lambda item: (not item["is_dir"], str(item["name"]).casefold()))
        return result

    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        entries = session.listdir(normalize_remote_path(path))
    return [
        {
            "name": item.name,
            "path": item.path,
            "is_dir": bool(item.is_dir),
            "is_symlink": bool(getattr(item, "is_symlink", False)),
            "size": int(item.size),
            "modified_ns": item.modified_ns,
        }
        for item in entries
    ]


def join(endpoint: dict[str, Any], root: str, relative: str) -> str:
    if endpoint.get("kind") == "remote":
        if not relative:
            return normalize_remote_path(root)
        return normalize_remote_path(posixpath.join(normalize_remote_path(root), relative))
    if not relative:
        return str(_local(root))
    parts = [part for part in str(relative).replace("\\", "/").split("/") if part]
    return str(_local(root).joinpath(*parts))


def parent(endpoint: dict[str, Any], path: str) -> str:
    if endpoint.get("kind") == "remote":
        normalized = normalize_remote_path(path)
        return str(PurePosixPath(normalized).parent)
    return str(_local(path).parent)


def basename(endpoint: dict[str, Any], path: str) -> str:
    if endpoint.get("kind") == "remote":
        return PurePosixPath(normalize_remote_path(path)).name
    return _local(path).name


def makedirs(endpoint: dict[str, Any], path: str) -> None:
    if endpoint.get("kind") == "local":
        _local(path).mkdir(parents=True, exist_ok=True)
        return
    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        session.makedirs(normalize_remote_path(path))


@contextmanager
def open_read(
    endpoint: dict[str, Any],
    path: str,
    *,
    offset: int = 0,
) -> Iterator[Any]:
    if endpoint.get("kind") == "local":
        with _local(path).open("rb", buffering=0) as stream:
            if offset:
                stream.seek(int(offset))
            yield stream
        return

    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        with session.open_read(normalize_remote_path(path), offset=int(offset)) as stream:
            yield stream


@contextmanager
def open_write(
    endpoint: dict[str, Any],
    path: str,
    *,
    offset: int = 0,
) -> Iterator[Any]:
    if endpoint.get("kind") == "local":
        value = _local(path)
        value.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b" if value.exists() else "w+b"
        with value.open(mode, buffering=0) as stream:
            if offset:
                stream.seek(int(offset))
            yield stream
        return

    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        session.makedirs(parent(endpoint, path))
        with session.open_write(normalize_remote_path(path), offset=int(offset)) as stream:
            yield stream


def flush(stream: Any, endpoint: dict[str, Any]) -> None:
    stream.flush()
    if endpoint.get("kind") == "local":
        os.fsync(stream.fileno())


def truncate(endpoint: dict[str, Any], path: str, size: int) -> None:
    if endpoint.get("kind") == "local":
        value = _local(path)
        value.parent.mkdir(parents=True, exist_ok=True)
        mode = "r+b" if value.exists() else "w+b"
        with value.open(mode, buffering=0) as stream:
            stream.truncate(int(size))
            stream.flush()
            os.fsync(stream.fileno())
        return

    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        session.truncate(normalize_remote_path(path), int(size))


def rename(endpoint: dict[str, Any], source: str, destination: str) -> None:
    if endpoint.get("kind") == "local":
        _local(source).rename(_local(destination))
        return
    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        session.rename(normalize_remote_path(source), normalize_remote_path(destination))


def remove_file(endpoint: dict[str, Any], path: str) -> None:
    if endpoint.get("kind") == "local":
        _local(path).unlink(missing_ok=True)
        return
    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        try:
            session.remove(normalize_remote_path(path))
        except RemoteNotFound:
            pass


def remove_dir(endpoint: dict[str, Any], path: str) -> None:
    if endpoint.get("kind") == "local":
        _local(path).rmdir()
        return
    endpoint = rebind(endpoint)
    with open_session(str(endpoint["connection_id"])) as session:
        session.rmdir(normalize_remote_path(path))


def same_namespace(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    if left.get("kind") != right.get("kind"):
        return False
    if left.get("kind") == "remote":
        return str(left.get("remote_identity") or "") == str(right.get("remote_identity") or "")
    return str(left.get("volume_identity") or "") == str(right.get("volume_identity") or "")
