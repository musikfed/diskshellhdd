from __future__ import annotations

import errno
import ftplib
import io
import posixpath
import socket
import stat as statmod
import threading
import uuid
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from backend.config import settings


class RemoteConnectionError(RuntimeError):
    pass


class RemoteNotFound(FileNotFoundError):
    pass


_profiles_lock = threading.Lock()
_profiles: dict[str, dict[str, Any]] = {}

SSH_KEEPALIVE_SECONDS = 30
SSH_IO_TIMEOUT_SECONDS = 120
TCP_KEEPIDLE_SECONDS = 60
TCP_KEEPINTERVAL_SECONDS = 15
TCP_KEEPCOUNT = 4


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": profile["id"],
        "protocol": profile["protocol"],
        "host": profile["host"],
        "port": profile["port"],
        "username": profile["username"],
        "tls": profile.get("tls", False),
        "passive": profile.get("passive", True),
        "accept_unknown_host": profile.get("accept_unknown_host", False),
        "root": profile.get("root") or "/",
        "connected_at": profile.get("connected_at"),
        "identity": _identity_from_profile(profile),
    }


def _profile(profile_id: str) -> dict[str, Any]:
    with _profiles_lock:
        profile = _profiles.get(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        return dict(profile)


def list_profiles() -> list[dict[str, Any]]:
    with _profiles_lock:
        return [_public_profile(profile) for profile in _profiles.values()]


def _identity_from_profile(profile: dict[str, Any]) -> str:
    return "|".join(
        [
            str(profile["protocol"]),
            str(profile["host"]).casefold(),
            str(profile["port"]),
            str(profile["username"]).casefold(),
            str(profile.get("root") or "/"),
        ]
    )


def profile_identity(profile_id: str) -> str:
    return _identity_from_profile(_profile(profile_id))


def find_profile_id_by_identity(identity: str) -> str | None:
    expected = str(identity or "")
    if not expected:
        return None
    with _profiles_lock:
        for profile_id, profile in _profiles.items():
            if _identity_from_profile(profile) == expected:
                return str(profile_id)
    return None


def remote_endpoint_state(profile_id: str) -> dict[str, Any]:
    try:
        identity = profile_identity(profile_id)
    except KeyError:
        return {
            "available": False,
            "reason": "remote_profile_missing",
            "identity": None,
        }

    try:
        with open_session(profile_id):
            pass
    except RemoteConnectionError as exc:
        return {
            "available": False,
            "reason": "remote_offline",
            "identity": identity,
            "message": str(exc),
        }
    return {
        "available": True,
        "reason": None,
        "identity": identity,
    }


def create_profile(
    protocol: str,
    host: str,
    username: str,
    password: str = "",
    port: int | None = None,
    private_key_path: str = "",
    accept_unknown_host: bool = False,
    passive: bool = True,
    root: str = "/",
) -> dict[str, Any]:
    proto = protocol.strip().casefold()
    if proto not in {"sftp", "ftp", "ftps"}:
        raise ValueError("protocol must be sftp, ftp, or ftps")
    host = host.strip()
    username = username.strip()
    if not host or not username:
        raise ValueError("host and username are required")

    default_port = 22 if proto == "sftp" else 21
    value = int(port or default_port)
    if not 1 <= value <= 65535:
        raise ValueError("port must be between 1 and 65535")

    profile_id = uuid.uuid4().hex
    profile: dict[str, Any] = {
        "id": profile_id,
        "protocol": proto,
        "host": host,
        "port": value,
        "username": username,
        "password": password,
        "private_key_path": private_key_path.strip(),
        "accept_unknown_host": bool(accept_unknown_host),
        "passive": bool(passive),
        "tls": proto == "ftps",
        "root": _normalize_remote_path(root or "/"),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }

    # Test before storing credentials in RAM.
    with open_session_from_profile(profile) as session:
        session.listdir(profile["root"])

    with _profiles_lock:
        _profiles[profile_id] = profile
    return _public_profile(profile)


def delete_profile(profile_id: str) -> dict[str, Any]:
    with _profiles_lock:
        profile = _profiles.pop(profile_id, None)
    if profile is None:
        raise KeyError(profile_id)
    return {"status": "disconnected", "id": profile_id}


def _normalize_remote_path(path: str) -> str:
    raw = str(path or "/").replace("\\", "/")
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/"):
        normalized = "/" + normalized
    return normalized


def _parent(path: str) -> str | None:
    normalized = _normalize_remote_path(path)
    if normalized == "/":
        return None
    parent = posixpath.dirname(normalized.rstrip("/")) or "/"
    return parent


@dataclass
class RemoteEntry:
    name: str
    path: str
    is_dir: bool
    size: int
    modified_ns: int | None = None
    is_symlink: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "size": self.size,
            "modified_ns": self.modified_ns,
            "is_symlink": self.is_symlink,
        }


class RemoteSession(AbstractContextManager):
    def listdir(self, path: str) -> list[RemoteEntry]:
        raise NotImplementedError

    def stat(self, path: str) -> RemoteEntry:
        normalized = _normalize_remote_path(path)
        parent = _parent(normalized) or "/"
        name = PurePosixPath(normalized).name
        if normalized == "/":
            return RemoteEntry("/", "/", True, 0, None)
        for item in self.listdir(parent):
            if item.name == name:
                return item
        raise RemoteNotFound(normalized)

    def makedirs(self, path: str) -> None:
        normalized = _normalize_remote_path(path)
        if normalized == "/":
            return
        current = ""
        for part in PurePosixPath(normalized).parts:
            if part == "/":
                continue
            current += "/" + part
            try:
                entry = self.stat(current)
                if not entry.is_dir:
                    raise FileExistsError(current)
            except RemoteNotFound:
                self.mkdir(current)

    def mkdir(self, path: str) -> None:
        raise NotImplementedError

    def remove(self, path: str) -> None:
        raise NotImplementedError

    def rmdir(self, path: str) -> None:
        raise NotImplementedError

    def rename(self, source: str, destination: str) -> None:
        raise NotImplementedError

    def open_read(self, path: str, offset: int = 0) -> BinaryIO:
        raise NotImplementedError

    def open_write(self, path: str, offset: int = 0) -> BinaryIO:
        raise NotImplementedError

    def truncate(self, path: str, size: int) -> None:
        raise NotImplementedError

    def walk(self, path: str) -> tuple[list[str], list[tuple[str, int]]]:
        normalized = _normalize_remote_path(path)
        entry = self.stat(normalized)
        if not entry.is_dir:
            return [], [("", int(entry.size))]

        directories: list[str] = [""]
        files: list[tuple[str, int]] = []
        stack = [normalized]
        while stack:
            current = stack.pop()
            rel_dir = posixpath.relpath(current, normalized)
            if rel_dir == ".":
                rel_dir = ""
            for item in self.listdir(current):
                relative = posixpath.join(rel_dir, item.name) if rel_dir else item.name
                if item.is_dir:
                    directories.append(relative)
                    stack.append(item.path)
                else:
                    files.append((relative, int(item.size)))
        directories.sort()
        files.sort()
        return directories, files

    def delete_tree(self, path: str) -> None:
        normalized = _normalize_remote_path(path)
        entry = self.stat(normalized)
        if not entry.is_dir:
            self.remove(normalized)
            return
        directories, files = self.walk(normalized)
        for relative, _size in files:
            self.remove(posixpath.join(normalized, relative))
        for relative in sorted((x for x in directories if x), key=lambda x: x.count("/"), reverse=True):
            self.rmdir(posixpath.join(normalized, relative))
        self.rmdir(normalized)


class SFTPSession(RemoteSession):
    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.client = None
        self.sftp = None

    def __enter__(self):
        try:
            import paramiko
        except ImportError as exc:
            raise RemoteConnectionError(
                "SFTP requires the optional 'remote' dependency group (paramiko)"
            ) from exc

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self.profile.get("accept_unknown_host"):
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())

        kwargs: dict[str, Any] = {
            "hostname": self.profile["host"],
            "port": self.profile["port"],
            "username": self.profile["username"],
            "timeout": 15,
            "banner_timeout": 15,
            "auth_timeout": 15,
            "look_for_keys": not bool(self.profile.get("private_key_path")),
            "allow_agent": True,
        }
        if self.profile.get("password"):
            kwargs["password"] = self.profile["password"]
        if self.profile.get("private_key_path"):
            kwargs["key_filename"] = self.profile["private_key_path"]

        try:
            client.connect(**kwargs)
            transport = client.get_transport()
            if transport is None or not transport.is_active():
                raise RemoteConnectionError("SSH transport did not become active")

            transport.set_keepalive(SSH_KEEPALIVE_SECONDS)
            raw_socket = getattr(transport, "sock", None)
            if raw_socket is not None:
                try:
                    raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
                    if hasattr(socket, "TCP_KEEPIDLE"):
                        raw_socket.setsockopt(
                            socket.IPPROTO_TCP,
                            socket.TCP_KEEPIDLE,
                            TCP_KEEPIDLE_SECONDS,
                        )
                    if hasattr(socket, "TCP_KEEPINTVL"):
                        raw_socket.setsockopt(
                            socket.IPPROTO_TCP,
                            socket.TCP_KEEPINTVL,
                            TCP_KEEPINTERVAL_SECONDS,
                        )
                    if hasattr(socket, "TCP_KEEPCNT"):
                        raw_socket.setsockopt(
                            socket.IPPROTO_TCP,
                            socket.TCP_KEEPCNT,
                            TCP_KEEPCOUNT,
                        )
                except OSError:
                    # SSH keepalive still protects the session even if an OS
                    # does not expose/tolerate every TCP keepalive option.
                    pass

            self.client = client
            self.sftp = client.open_sftp()
            self.sftp.get_channel().settimeout(SSH_IO_TIMEOUT_SECONDS)
            return self
        except Exception as exc:  # noqa: BLE001
            client.close()
            raise RemoteConnectionError(str(exc)) from exc

    def __exit__(self, exc_type, exc, tb):
        if self.sftp is not None:
            self.sftp.close()
        if self.client is not None:
            self.client.close()
        return False

    def listdir(self, path: str) -> list[RemoteEntry]:
        assert self.sftp is not None
        normalized = _normalize_remote_path(path)
        try:
            attributes = self.sftp.listdir_attr(normalized)
        except OSError as exc:
            raise RemoteConnectionError(str(exc)) from exc
        items: list[RemoteEntry] = []
        for attr in attributes:
            child = posixpath.join(normalized, attr.filename)
            is_dir = statmod.S_ISDIR(attr.st_mode)
            is_symlink = statmod.S_ISLNK(attr.st_mode)
            mtime = getattr(attr, "st_mtime", None)
            items.append(
                RemoteEntry(
                    attr.filename,
                    child,
                    is_dir,
                    0 if is_dir else int(getattr(attr, "st_size", 0) or 0),
                    int(mtime * 1_000_000_000) if mtime else None,
                    is_symlink,
                )
            )
        items.sort(key=lambda row: (not row.is_dir, row.name.casefold()))
        return items

    def stat(self, path: str) -> RemoteEntry:
        assert self.sftp is not None
        normalized = _normalize_remote_path(path)
        try:
            attr = self.sftp.stat(normalized)
        except OSError as exc:
            if getattr(exc, "errno", None) == errno.ENOENT:
                raise RemoteNotFound(normalized) from exc
            raise RemoteConnectionError(str(exc)) from exc
        is_dir = statmod.S_ISDIR(attr.st_mode)
        mtime = getattr(attr, "st_mtime", None)
        return RemoteEntry(
            PurePosixPath(normalized).name or "/",
            normalized,
            is_dir,
            0 if is_dir else int(getattr(attr, "st_size", 0) or 0),
            int(mtime * 1_000_000_000) if mtime else None,
        )

    def mkdir(self, path: str) -> None:
        assert self.sftp is not None
        self.sftp.mkdir(_normalize_remote_path(path))

    def remove(self, path: str) -> None:
        assert self.sftp is not None
        self.sftp.remove(_normalize_remote_path(path))

    def rmdir(self, path: str) -> None:
        assert self.sftp is not None
        self.sftp.rmdir(_normalize_remote_path(path))

    def rename(self, source: str, destination: str) -> None:
        assert self.sftp is not None
        self.sftp.rename(_normalize_remote_path(source), _normalize_remote_path(destination))

    def open_read(self, path: str, offset: int = 0) -> BinaryIO:
        assert self.sftp is not None
        stream = self.sftp.open(_normalize_remote_path(path), "rb")
        if offset:
            stream.seek(int(offset))
        return stream

    def open_write(self, path: str, offset: int = 0) -> BinaryIO:
        assert self.sftp is not None
        normalized = _normalize_remote_path(path)
        stream = self.sftp.open(normalized, "r+b" if offset else "wb")
        if offset:
            stream.seek(int(offset))
        return stream

    def truncate(self, path: str, size: int) -> None:
        assert self.sftp is not None
        try:
            self.sftp.truncate(_normalize_remote_path(path), int(size))
        except OSError as exc:
            raise RemoteConnectionError(str(exc)) from exc


class _FTPStream(io.BufferedIOBase):
    def __init__(self, ftp, data_socket, mode: str):
        self.ftp = ftp
        self.socket = data_socket
        self.file = data_socket.makefile(mode)
        self._closed = False

    def readable(self) -> bool:
        return "r" in self.file.mode

    def writable(self) -> bool:
        return "w" in self.file.mode

    def read(self, size: int = -1):
        return self.file.read(size)

    def write(self, data):
        return self.file.write(data)

    def flush(self):
        return self.file.flush()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.file.close()
        finally:
            try:
                self.socket.close()
            finally:
                self.ftp.voidresp()

    @property
    def closed(self):
        return self._closed

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class FTPSession(RemoteSession):
    def __init__(self, profile: dict[str, Any]):
        self.profile = profile
        self.ftp = None

    def __enter__(self):
        ftp_class = ftplib.FTP_TLS if self.profile.get("tls") else ftplib.FTP
        ftp = ftp_class(timeout=20)
        try:
            ftp.connect(self.profile["host"], self.profile["port"])
            ftp.login(self.profile["username"], self.profile.get("password") or "")
            if self.profile.get("tls"):
                ftp.prot_p()
            ftp.set_pasv(bool(self.profile.get("passive", True)))
            self.ftp = ftp
            return self
        except (OSError, ftplib.Error) as exc:
            try:
                ftp.close()
            except OSError:
                pass
            raise RemoteConnectionError(str(exc)) from exc

    def __exit__(self, exc_type, exc, tb):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except (OSError, ftplib.Error):
                try:
                    self.ftp.close()
                except OSError:
                    pass
        return False

    def listdir(self, path: str) -> list[RemoteEntry]:
        assert self.ftp is not None
        normalized = _normalize_remote_path(path)
        items: list[RemoteEntry] = []
        try:
            for name, facts in self.ftp.mlsd(normalized, facts=["type", "size", "modify"]):
                if name in {".", ".."}:
                    continue
                kind = facts.get("type", "")
                is_dir = kind in {"dir", "cdir", "pdir"}
                size = 0 if is_dir else int(facts.get("size") or 0)
                modified_ns = None
                stamp = facts.get("modify")
                if stamp:
                    try:
                        parsed = datetime.strptime(stamp[:14], "%Y%m%d%H%M%S").replace(
                            tzinfo=timezone.utc
                        )
                        modified_ns = int(parsed.timestamp() * 1_000_000_000)
                    except ValueError:
                        modified_ns = None
                items.append(
                    RemoteEntry(
                        name,
                        posixpath.join(normalized, name),
                        is_dir,
                        size,
                        modified_ns,
                    )
                )
        except (OSError, ftplib.Error) as exc:
            raise RemoteConnectionError(
                f"FTP server must support MLSD for Commander browsing: {exc}"
            ) from exc
        items.sort(key=lambda row: (not row.is_dir, row.name.casefold()))
        return items

    def mkdir(self, path: str) -> None:
        assert self.ftp is not None
        self.ftp.mkd(_normalize_remote_path(path))

    def remove(self, path: str) -> None:
        assert self.ftp is not None
        self.ftp.delete(_normalize_remote_path(path))

    def rmdir(self, path: str) -> None:
        assert self.ftp is not None
        self.ftp.rmd(_normalize_remote_path(path))

    def rename(self, source: str, destination: str) -> None:
        assert self.ftp is not None
        self.ftp.rename(
            _normalize_remote_path(source),
            _normalize_remote_path(destination),
        )

    def open_read(self, path: str, offset: int = 0) -> BinaryIO:
        assert self.ftp is not None
        data_socket = self.ftp.transfercmd(
            f"RETR {_normalize_remote_path(path)}",
            rest=int(offset) if offset else None,
        )
        return _FTPStream(self.ftp, data_socket, "rb")

    def open_write(self, path: str, offset: int = 0) -> BinaryIO:
        assert self.ftp is not None
        data_socket = self.ftp.transfercmd(
            f"STOR {_normalize_remote_path(path)}",
            rest=int(offset) if offset else None,
        )
        return _FTPStream(self.ftp, data_socket, "wb")

    def truncate(self, path: str, size: int) -> None:
        del path, size
        raise RemoteConnectionError(
            "Persistent Remote River truncation is supported only for SFTP"
        )


def open_session_from_profile(profile: dict[str, Any]) -> RemoteSession:
    if profile["protocol"] == "sftp":
        return SFTPSession(profile)
    return FTPSession(profile)


def open_session(profile_id: str) -> RemoteSession:
    return open_session_from_profile(_profile(profile_id))


def list_directory(profile_id: str, path: str) -> dict[str, Any]:
    profile = _profile(profile_id)
    normalized = _normalize_remote_path(path or profile.get("root") or "/")
    with open_session_from_profile(profile) as session:
        items = [item.as_dict() for item in session.listdir(normalized)]
    return {
        "kind": "remote",
        "connection": _public_profile(profile),
        "path": normalized,
        "parent": _parent(normalized),
        "items": items,
    }


def make_directory(profile_id: str, path: str) -> dict[str, Any]:
    profile = _profile(profile_id)
    normalized = _normalize_remote_path(path)
    with open_session_from_profile(profile) as session:
        session.makedirs(normalized)
    return {"status": "created", "path": normalized}


def rename_item(profile_id: str, source: str, destination: str) -> dict[str, Any]:
    profile = _profile(profile_id)
    src = _normalize_remote_path(source)
    dst = _normalize_remote_path(destination)
    with open_session_from_profile(profile) as session:
        session.rename(src, dst)
    return {"status": "renamed", "source": src, "destination": dst}


def delete_item(profile_id: str, path: str, recursive: bool = False) -> dict[str, Any]:
    profile = _profile(profile_id)
    normalized = _normalize_remote_path(path)
    with open_session_from_profile(profile) as session:
        entry = session.stat(normalized)
        if entry.is_dir:
            if not recursive:
                raise ValueError("Remote directory delete requires recursive=true")
            session.delete_tree(normalized)
        else:
            session.remove(normalized)
    return {"status": "deleted", "path": normalized}


def cache_remote_file(
    profile_id: str,
    remote_path: str,
    max_bytes: int = 256 * 1024**2,
) -> dict[str, Any]:
    profile = _profile(profile_id)
    normalized = _normalize_remote_path(remote_path)
    with open_session_from_profile(profile) as session:
        entry = session.stat(normalized)
        if entry.is_dir:
            raise IsADirectoryError(normalized)
        if int(entry.size) > int(max_bytes):
            raise ValueError(
                f"Remote preview cache limit exceeded: {entry.size} > {max_bytes}"
            )

        cache_root = settings.data_dir / "cache" / "remote_preview" / profile_id
        cache_root.mkdir(parents=True, exist_ok=True)
        safe_name = PurePosixPath(normalized).name or "remote.bin"
        target = cache_root / f"{uuid.uuid4().hex}-{safe_name}"
        with session.open_read(normalized) as src, target.open("xb") as dst:
            while True:
                chunk = src.read(4 * 1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)

    return {
        "connection_id": profile_id,
        "remote_path": normalized,
        "local_path": str(target),
        "size": int(entry.size),
        "name": safe_name,
    }
