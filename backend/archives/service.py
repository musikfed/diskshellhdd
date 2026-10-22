from __future__ import annotations

import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

from backend.files.write_authorization import file_writes_allowed


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
    elif suffix in {".rar", ".cab", ".wim"}:
        entries = _list_external_7z(archive, limit=limit)
        provider = "7zip-cli"
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
    if not file_writes_allowed():
        raise ArchiveWriteBlocked("File writes are locked")
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
    elif suffix == ".7z":
        try:
            import py7zr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UnsupportedArchive("Install the preview extra for 7z extraction") from exc
        with py7zr.SevenZipFile(archive, mode="r") as handle:
            names = handle.getnames()
            if len(names) > max_files:
                raise ValueError("Archive contains too many entries")
            for name in names:
                _safe_destination(destination_path, name)
            handle.extractall(path=destination_path)
        files = sum(1 for name in names if not name.endswith("/"))
        total = sum(
            int(path.stat().st_size)
            for path in destination_path.rglob("*")
            if path.is_file()
        )
        if total > max_total_bytes:
            raise ValueError("Archive expands beyond the configured safety limit")
    elif suffix in {".rar", ".cab", ".wim"}:
        entries = _list_external_7z(archive, limit=max_files + 1)
        if len(entries) > max_files:
            raise ValueError("Archive contains too many entries")
        total = sum(int(item.get("size") or 0) for item in entries if not item["is_dir"])
        if total > max_total_bytes:
            raise ValueError("Archive expands beyond the configured safety limit")
        for item in entries:
            _safe_destination(destination_path, item["name"])
        executable = _seven_zip_executable()
        if not executable:
            raise UnsupportedArchive("7-Zip executable not found")
        result = subprocess.run(
            [executable, "x", "-y", f"-o{destination_path}", str(archive)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
            check=False,
        )
        if result.returncode != 0:
            raise UnsupportedArchive(result.stderr.strip() or "7-Zip extraction failed")
        files = sum(1 for item in entries if not item["is_dir"])
    else:
        raise UnsupportedArchive(
            "Safe extraction supports ZIP, TAR-family, 7Z, and selected 7-Zip-readable formats"
        )

    return {
        "status": "completed",
        "archive": str(archive),
        "destination": str(destination_path),
        "files": files,
        "bytes": total,
    }


def _seven_zip_executable() -> str | None:
    return shutil.which("7z") or shutil.which("7zz") or shutil.which("7z.exe")


def _iter_source_files(source: Path):
    if source.is_file():
        yield source, source.name
        return
    root_name = source.name
    for item in source.rglob("*"):
        if item.is_symlink():
            continue
        relative = item.relative_to(source)
        archive_name = str(Path(root_name) / relative)
        yield item, archive_name


def create_archive(
    sources: list[str | Path],
    destination: str | Path,
    archive_format: str = "zip",
) -> dict:
    if not file_writes_allowed():
        raise ArchiveWriteBlocked("File writes are locked")
    if not sources:
        raise ValueError("At least one source is required")

    resolved = [Path(source).expanduser().resolve(strict=True) for source in sources]
    target = Path(destination).expanduser().resolve()
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    fmt = archive_format.strip().casefold()
    files = 0
    total = 0

    if fmt == "zip":
        with zipfile.ZipFile(
            target,
            mode="x",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as handle:
            for source in resolved:
                for item, arcname in _iter_source_files(source):
                    if item.is_dir():
                        continue
                    handle.write(item, arcname=arcname)
                    files += 1
                    total += int(item.stat().st_size)
    elif fmt in {"tar", "tar.gz", "tgz"}:
        mode = "x:gz" if fmt in {"tar.gz", "tgz"} else "x"
        with tarfile.open(target, mode=mode) as handle:
            for source in resolved:
                for item, arcname in _iter_source_files(source):
                    if item.is_dir():
                        continue
                    handle.add(item, arcname=arcname, recursive=False)
                    files += 1
                    total += int(item.stat().st_size)
    elif fmt == "7z":
        try:
            import py7zr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise UnsupportedArchive("Install the preview extra for 7z creation") from exc
        with py7zr.SevenZipFile(target, mode="x") as handle:
            for source in resolved:
                if source.is_dir():
                    handle.writeall(source, arcname=source.name)
                    for item in source.rglob("*"):
                        if item.is_file() and not item.is_symlink():
                            files += 1
                            total += int(item.stat().st_size)
                else:
                    handle.write(source, arcname=source.name)
                    files += 1
                    total += int(source.stat().st_size)
    else:
        raise UnsupportedArchive("Create supports ZIP, TAR, TAR.GZ/TGZ, and 7Z")

    return {
        "status": "completed",
        "archive": str(target),
        "format": fmt,
        "files": files,
        "bytes": total,
    }


def _list_external_7z(archive: Path, limit: int = 5000) -> list[dict]:
    executable = _seven_zip_executable()
    if not executable:
        raise UnsupportedArchive(
            "RAR/extra archive formats require 7-Zip (7z.exe/7zz) in PATH"
        )
    result = subprocess.run(
        [executable, "l", "-slt", str(archive)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise UnsupportedArchive(result.stderr.strip() or "7-Zip list failed")

    entries: list[dict] = []
    current: dict[str, str] = {}
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            if current.get("Path") and current["Path"] != str(archive):
                name = current["Path"]
                is_dir = current.get("Folder") == "+"
                entries.append(
                    {
                        "name": name,
                        "size": None if is_dir else int(current.get("Size") or 0),
                        "compressed_size": (
                            int(current["Packed Size"])
                            if current.get("Packed Size", "").isdigit()
                            else None
                        ),
                        "is_dir": is_dir,
                    }
                )
                if len(entries) >= limit:
                    break
            current = {}
            continue
        if " = " in line:
            key, value = line.split(" = ", 1)
            current[key] = value
    return entries
