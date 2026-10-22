from __future__ import annotations

import shutil
import tarfile
import zipfile
from pathlib import Path

from backend.config import settings


class UnsupportedArchive(ValueError):
    pass


class ArchiveWriteBlocked(RuntimeError):
    pass


def list_archive(path: str | Path, limit: int = 5000) -> dict:
    archive = Path(path).expanduser().resolve(strict=True)
    suffix = archive.suffix.casefold()
    entries: list[dict] = []

    if suffix == ".zip":
        with zipfile.ZipFile(archive) as handle:
            for info in handle.infolist()[:limit]:
                entries.append({"name": info.filename, "size": info.file_size, "compressed_size": info.compress_size, "is_dir": info.is_dir()})
        provider = "zip"
    elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
        with tarfile.open(archive, mode="r:*") as handle:
            for member in handle.getmembers()[:limit]:
                entries.append({"name": member.name, "size": member.size, "is_dir": member.isdir()})
        provider = "tar"
    elif suffix == ".7z":
        try:
            import py7zr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UnsupportedArchive("Install the preview extra for 7z support") from exc
        with py7zr.SevenZipFile(archive, mode="r") as handle:
            for name in handle.getnames()[:limit]:
                entries.append({"name": name, "size": None, "is_dir": name.endswith("/")})
        provider = "7z"
    elif suffix == ".iso":
        try:
            import pycdlib  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UnsupportedArchive("Install the preview extra for ISO support") from exc
        iso = pycdlib.PyCdlib()
        iso.open(str(archive))
        try:
            for dirname, _dirs, files in iso.walk(iso_path="/"):
                for name in files:
                    entries.append({"name": f"{dirname}/{name}", "size": None, "is_dir": False})
                    if len(entries) >= limit:
                        break
                if len(entries) >= limit:
                    break
        finally:
            iso.close()
        provider = "iso"
    else:
        raise UnsupportedArchive(f"Unsupported archive type: {suffix}")

    return {"path": str(archive), "provider": provider, "entries": entries, "truncated": len(entries) >= limit}


def _safe_destination(root: Path, member_name: str) -> Path:
    normalized = member_name.replace("\\", "/").lstrip("/")
    target = (root / normalized).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Unsafe archive path: {member_name}") from exc
    return target


def extract_archive(
    path: str | Path,
    destination: str | Path,
    max_files: int = 50_000,
    max_total_bytes: int = 500 * 1024**3,
) -> dict:
    if not settings.allow_file_writes:
        raise ArchiveWriteBlocked("DS_ALLOW_FILE_WRITES is disabled")
    archive = Path(path).expanduser().resolve(strict=True)
    destination_path = Path(destination).expanduser().resolve()
    destination_path.mkdir(parents=True, exist_ok=True)
    suffix = archive.suffix.casefold()
    files = 0
    total = 0

    if suffix == ".zip":
        with zipfile.ZipFile(archive) as handle:
            infos = handle.infolist()
            if len(infos) > max_files:
                raise ValueError("Archive contains too many entries")
            total = sum(info.file_size for info in infos if not info.is_dir())
            if total > max_total_bytes:
                raise ValueError("Archive expands beyond the configured safety limit")
            for info in infos:
                target = _safe_destination(destination_path, info.filename)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with handle.open(info) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                files += 1
    elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
        with tarfile.open(archive, mode="r:*") as handle:
            members = handle.getmembers()
            if len(members) > max_files:
                raise ValueError("Archive contains too many entries")
            total = sum(member.size for member in members if member.isfile())
            if total > max_total_bytes:
                raise ValueError("Archive expands beyond the configured safety limit")
            for member in members:
                if member.issym() or member.islnk() or member.isdev():
                    continue
                target = _safe_destination(destination_path, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                src = handle.extractfile(member)
                if src is None:
                    continue
                with src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                files += 1
    else:
        raise UnsupportedArchive("Safe extraction is currently enabled for ZIP and TAR-family archives")

    return {"status": "completed", "archive": str(archive), "destination": str(destination_path), "files": files, "bytes": total}
