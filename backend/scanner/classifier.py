from __future__ import annotations

from pathlib import Path


CATEGORY_EXTENSIONS: dict[str, set[str]] = {
    "photo": {
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff",
        ".heic", ".heif", ".avif", ".cr2", ".cr3", ".nef", ".arw", ".dng",
        ".raf", ".orf", ".rw2",
    },
    "video": {
        ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mts",
        ".m2ts", ".ts", ".flv",
    },
    "audio": {
        ".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus", ".wma",
        ".aiff",
    },
    "document": {
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt",
        ".ods", ".odp", ".rtf", ".epub", ".djvu",
    },
    "archive": {
        ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab",
    },
    "disk_image": {".iso", ".img", ".vhd", ".vhdx", ".dmg", ".wim", ".esd"},
    "code": {
        ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".java", ".c", ".h", ".cpp",
        ".hpp", ".cs", ".go", ".rs", ".php", ".rb", ".swift", ".kt", ".kts",
        ".html", ".css", ".scss", ".json", ".yaml", ".yml", ".toml", ".xml", ".sql",
        ".ps1", ".sh", ".bat", ".cmd",
    },
    "executable": {".exe", ".msi", ".dll", ".sys", ".com", ".scr", ".appx", ".msix"},
    "design": {
        ".psd", ".psb", ".ai", ".eps", ".svg", ".blend", ".obj", ".fbx", ".stl",
        ".3ds", ".dwg", ".dxf",
    },
}

DEVELOPMENT_DIR_NAMES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules", "vendor", "dist", "build",
}
CACHE_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".cache", "cache", "tmp",
    "temp",
}
SYSTEM_DIR_NAMES = {"$recycle.bin", "system volume information", "windows", "$windows.~bt"}


def classify_extension(extension: str | None) -> str:
    if not extension:
        return "other"
    ext = extension.casefold()
    for category, extensions in CATEGORY_EXTENSIONS.items():
        if ext in extensions:
            return category
    return "other"


def classify_path(path: Path, extension: str | None) -> str:
    parts = {part.casefold() for part in path.parts}
    if parts & SYSTEM_DIR_NAMES:
        return "system"
    if parts & CACHE_DIR_NAMES:
        return "cache"
    if parts & DEVELOPMENT_DIR_NAMES:
        return "development"
    return classify_extension(extension)
