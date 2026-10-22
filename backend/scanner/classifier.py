from __future__ import annotations

from pathlib import Path


PHOTO = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".avif", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}
VIDEO = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".mts", ".m2ts", ".wmv"}
AUDIO = {".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".ape"}
DOCUMENT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp", ".rtf", ".epub", ".mobi", ".txt", ".md"}
ARCHIVE = {".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab"}
DISK_IMAGE = {".iso", ".img", ".vhd", ".vhdx", ".dmg", ".wim", ".esd"}
CODE = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".cs", ".cpp", ".c", ".h", ".hpp", ".rs", ".go", ".php", ".rb", ".swift", ".html", ".css", ".scss", ".sql", ".json", ".yaml", ".yml", ".toml", ".xml", ".sh", ".ps1"}
EXECUTABLE = {".exe", ".msi", ".dll", ".sys", ".com", ".bat", ".cmd", ".appx", ".msix"}
DESIGN = {".psd", ".ai", ".eps", ".svg", ".blend", ".obj", ".fbx", ".stl", ".dwg", ".dxf"}

DEVELOPMENT_PARTS = {".git", ".venv", "venv", "node_modules", "vendor", "dist", "build", "target"}
CACHE_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".cache", "cache", "temp", "tmp"}
SYSTEM_PARTS = {"system volume information", "$recycle.bin", "windows", "program files", "program files (x86)"}
BACKUP_MARKERS = {"backup", "backups", "snapshot", "snapshots", "bak", "restore"}


def classify_path(path: Path, extension: str | None = None) -> str:
    parts = {part.casefold() for part in path.parts}
    if parts & SYSTEM_PARTS:
        return "system"
    if parts & CACHE_PARTS:
        return "cache"
    if parts & DEVELOPMENT_PARTS:
        return "development"
    if parts & BACKUP_MARKERS:
        return "backup"

    ext = (extension or path.suffix).casefold()
    if ext in PHOTO:
        return "photo"
    if ext in VIDEO:
        return "video"
    if ext in AUDIO:
        return "audio"
    if ext in DOCUMENT:
        return "document"
    if ext in ARCHIVE:
        return "archive"
    if ext in DISK_IMAGE:
        return "disk_image"
    if ext in CODE:
        return "code"
    if ext in EXECUTABLE:
        return "executable"
    if ext in DESIGN:
        return "design"
    return "other"
