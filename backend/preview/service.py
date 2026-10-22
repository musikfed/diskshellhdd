from __future__ import annotations

import io
import json
import mimetypes
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps


TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".html", ".css", ".scss", ".sql", ".log", ".ini", ".cfg", ".csv",
}
MEDIA_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus"}


def _ffprobe(path: Path) -> dict | None:
    executable = shutil.which("ffprobe")
    if not executable:
        return None
    result = subprocess.run(
        [
            executable, "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


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
        text = file_path.read_text(encoding="utf-8", errors="replace")
        result["text"] = text[:200_000]
        result["truncated"] = len(text) > 200_000
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
            return result
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

    if file_path.suffix.casefold() in MEDIA_EXTENSIONS:
        result["provider"] = "media"
        metadata = _ffprobe(file_path)
        if metadata is not None:
            result["ffprobe"] = metadata
        else:
            result["ffprobe_available"] = False
    return result


def thumbnail_bytes(path: str | Path, max_size: int = 720) -> tuple[bytes, str]:
    file_path = Path(path).expanduser().resolve(strict=True)
    max_size = min(max(max_size, 64), 2048)

    if file_path.suffix.casefold() == ".pdf":
        try:
            import fitz  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ValueError("Install preview extra for PDF thumbnails") from exc
        with fitz.open(file_path) as document:
            if not document.page_count:
                raise ValueError("PDF has no pages")
            page = document[0]
            pixmap = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")
    else:
        image = Image.open(file_path)
        image = ImageOps.exif_transpose(image).convert("RGB")

    image.thumbnail((max_size, max_size))
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue(), "image/jpeg"
