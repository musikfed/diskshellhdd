from __future__ import annotations

import mimetypes
from pathlib import Path

from PIL import Image


TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".html", ".css", ".scss", ".sql", ".log", ".ini", ".cfg", ".csv",
}


def preview_metadata(path: str | Path) -> dict:
    file_path = Path(path).expanduser().resolve(strict=True)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    stat = file_path.stat()
    mime, _ = mimetypes.guess_type(file_path.name)
    result = {
        "path": str(file_path),
        "name": file_path.name,
        "extension": file_path.suffix.casefold(),
        "mime": mime or "application/octet-stream",
        "size": int(stat.st_size),
        "modified_ns": int(stat.st_mtime_ns),
        "provider": "generic",
    }

    if file_path.suffix.casefold() in TEXT_EXTENSIONS:
        result["provider"] = "text"
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            result["text"] = text[:200_000]
            result["truncated"] = len(text) > 200_000
        except OSError:
            pass
        return result

    try:
        with Image.open(file_path) as image:
            result.update(
                {
                    "provider": "image",
                    "width": image.width,
                    "height": image.height,
                    "format": image.format,
                    "mode": image.mode,
                }
            )
            exif = image.getexif()
            if exif:
                result["exif_count"] = len(exif)
    except (OSError, ValueError):
        pass

    if file_path.suffix.casefold() == ".pdf":
        try:
            import fitz  # type: ignore[import-not-found]

            with fitz.open(file_path) as document:
                result["provider"] = "pdf"
                result["pages"] = document.page_count
                if document.page_count:
                    result["text"] = document[0].get_text()[:50_000]
        except (ImportError, OSError, RuntimeError, ValueError):
            result["provider"] = "pdf-metadata-only"

    return result
