from __future__ import annotations

import hashlib
import shutil

import psutil
from pathlib import Path

from send2trash import send2trash

from backend.config import settings


class FileWriteBlocked(RuntimeError):
    pass


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=True)


def list_directory(path: str | Path) -> dict:
    root = _resolved(path)
    if not root.is_dir():
        raise NotADirectoryError(root)
    items: list[dict] = []
    for item in root.iterdir():
        try:
            stat = item.stat()
            items.append({"name": item.name, "path": str(item), "is_dir": item.is_dir(), "size": 0 if item.is_dir() else int(stat.st_size), "modified_ns": int(stat.st_mtime_ns)})
        except (PermissionError, FileNotFoundError, OSError):
            continue
    items.sort(key=lambda row: (not row["is_dir"], row["name"].casefold()))
    return {"path": str(root), "parent": str(root.parent) if root.parent != root else None, "items": items}


def hash_file(path: str | Path, algorithm: str = "sha256") -> dict:
    file_path = _resolved(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    if algorithm not in hashlib.algorithms_available:
        raise ValueError("Unsupported hash algorithm")
    digest = hashlib.new(algorithm)
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(file_path), "algorithm": algorithm, "digest": digest.hexdigest()}


def _require_writes() -> None:
    if not settings.allow_file_writes:
        raise FileWriteBlocked("DS_ALLOW_FILE_WRITES is disabled")


def copy_item(source: str | Path, destination: str | Path) -> dict:
    _require_writes()
    src = _resolved(source)
    dst = Path(destination).expanduser().resolve()
    if dst.exists():
        raise FileExistsError(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=False)
    else:
        shutil.copy2(src, dst)
    return {"status": "completed", "source": str(src), "destination": str(dst)}


def move_item(source: str | Path, destination: str | Path) -> dict:
    _require_writes()
    src = _resolved(source)
    dst = Path(destination).expanduser().resolve()
    if dst.exists():
        raise FileExistsError(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return {"status": "completed", "source": str(src), "destination": str(dst)}


def make_directory(path: str | Path) -> dict:
    _require_writes()
    target = Path(path).expanduser().resolve()
    target.mkdir(parents=False, exist_ok=False)
    return {"status": "created", "path": str(target)}


def trash_item(path: str | Path) -> dict:
    _require_writes()
    target = _resolved(path)
    send2trash(str(target))
    return {"status": "trashed", "path": str(target)}


def rename_item(source: str | Path, destination: str | Path) -> dict:
    _require_writes()
    src = _resolved(source)
    dst = Path(destination).expanduser().resolve()
    if dst.exists():
        raise FileExistsError(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return {
        "status": "renamed",
        "source": str(src),
        "destination": str(dst),
    }


def list_roots() -> dict:
    roots: list[dict] = []
    seen: set[str] = set()
    for partition in psutil.disk_partitions(all=False):
        mountpoint = str(partition.mountpoint)
        key = mountpoint.casefold()
        if key in seen:
            continue
        seen.add(key)
        try:
            usage = shutil.disk_usage(mountpoint)
        except OSError:
            usage = None
        roots.append(
            {
                "path": mountpoint,
                "device": str(partition.device),
                "filesystem": str(partition.fstype or ""),
                "options": str(partition.opts or ""),
                "total": int(usage.total) if usage else None,
                "free": int(usage.free) if usage else None,
            }
        )
    roots.sort(key=lambda row: row["path"].casefold())
    return {"roots": roots}
