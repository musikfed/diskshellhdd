from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path


class UnsupportedArchive(ValueError):
    pass


def list_archive(path: str | Path, limit: int = 5000) -> dict:
    archive = Path(path).expanduser().resolve(strict=True)
    suffix = archive.suffix.casefold()
    entries: list[dict] = []

    if suffix == ".zip":
        with zipfile.ZipFile(archive) as handle:
            for info in handle.infolist()[:limit]:
                entries.append(
                    {
                        "name": info.filename,
                        "size": info.file_size,
                        "compressed_size": info.compress_size,
                        "is_dir": info.is_dir(),
                    }
                )
        provider = "zip"
    elif suffix in {".tar", ".gz", ".tgz", ".bz2", ".xz"}:
        with tarfile.open(archive, mode="r:*") as handle:
            for member in handle.getmembers()[:limit]:
                entries.append(
                    {"name": member.name, "size": member.size, "is_dir": member.isdir()}
                )
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

    return {
        "path": str(archive),
        "provider": provider,
        "entries": entries,
        "truncated": len(entries) >= limit,
    }
