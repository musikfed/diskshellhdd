from __future__ import annotations

import hashlib
import shutil

import psutil
from pathlib import Path

from send2trash import send2trash

from backend.core.database import connect
from backend.files.write_authorization import file_writes_allowed


class FileWriteBlocked(RuntimeError):
    pass


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve(strict=True)


def _indexed_child_directories(
    root: Path,
    scan_id: int | None = None,
) -> tuple[int | None, dict[str, dict]]:
    root_text = str(root)
    with connect() as connection:
        selected_scan_id = scan_id
        if selected_scan_id is None:
            row = connection.execute(
                """
                SELECT d.scan_id
                FROM directories d
                JOIN scan_sessions s ON s.id = d.scan_id
                WHERE d.parent_path = ? COLLATE NOCASE
                  AND s.status = 'completed'
                ORDER BY d.scan_id DESC
                LIMIT 1
                """,
                (root_text,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """
                    SELECT d.scan_id
                    FROM directories d
                    JOIN scan_sessions s ON s.id = d.scan_id
                    WHERE d.path = ? COLLATE NOCASE
                      AND s.status = 'completed'
                    ORDER BY d.scan_id DESC
                    LIMIT 1
                    """,
                    (root_text,),
                ).fetchone()
            selected_scan_id = int(row["scan_id"]) if row is not None else None

        if selected_scan_id is None:
            return None, {}

        rows = connection.execute(
            """
            SELECT path, total_size, total_files, child_directories, scan_complete
            FROM directories
            WHERE scan_id = ?
              AND parent_path = ? COLLATE NOCASE
            """,
            (int(selected_scan_id), root_text),
        ).fetchall()

    return int(selected_scan_id), {
        str(row["path"]).casefold(): dict(row)
        for row in rows
    }


def list_directory(path: str | Path, scan_id: int | None = None) -> dict:
    root = _resolved(path)
    if not root.is_dir():
        raise NotADirectoryError(root)

    indexed_scan_id, indexed_dirs = _indexed_child_directories(root, scan_id=scan_id)
    items: list[dict] = []
    for item in root.iterdir():
        try:
            stat = item.stat()
            is_dir = item.is_dir()
            indexed = indexed_dirs.get(str(item).casefold()) if is_dir else None
            items.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "is_dir": is_dir,
                    "size": (
                        int(indexed["total_size"])
                        if indexed is not None
                        else (None if is_dir else int(stat.st_size))
                    ),
                    "size_known": bool(indexed is not None or not is_dir),
                    "size_source": "scan_index" if indexed is not None else "filesystem",
                    "indexed_scan_id": indexed_scan_id if indexed is not None else None,
                    "total_files": int(indexed["total_files"]) if indexed is not None else None,
                    "child_directories": (
                        int(indexed["child_directories"]) if indexed is not None else None
                    ),
                    "scan_complete": bool(indexed["scan_complete"]) if indexed is not None else None,
                    "modified_ns": int(stat.st_mtime_ns),
                }
            )
        except (PermissionError, FileNotFoundError, OSError):
            continue
    items.sort(key=lambda row: (not row["is_dir"], row["name"].casefold()))
    return {
        "path": str(root),
        "parent": str(root.parent) if root.parent != root else None,
        "indexed_scan_id": indexed_scan_id,
        "items": items,
    }


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
    if not file_writes_allowed():
        raise FileWriteBlocked("File writes are locked")


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
