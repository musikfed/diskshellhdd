from __future__ import annotations

from pathlib import PurePath
from typing import Any

from backend.core.database import connect, init_database


_SYSTEM_MARKERS = (
    "\\windows",
    "\\program files",
    "\\program files (x86)",
    "\\programdata",
    "\\$recycle.bin",
    "\\system volume information",
)
_CACHE_MARKERS = (
    "\\temp",
    "\\cache",
    "\\caches",
    "\\node_modules",
    "\\.cache",
    "\\.gradle",
    "\\npm-cache",
    "\\pip\\cache",
)
_NATIVE_RELOCATE_MARKERS = (
    "\\downloads",
    "\\documents",
    "\\pictures",
    "\\videos",
    "\\music",
    "\\steamapps",
    "\\steamlibrary",
)
_ARCHIVE_MARKERS = (
    "\\backup",
    "\\backups",
    "\\archive",
    "\\archives",
    "\\iso",
)


def _decision(path: str, size: int) -> tuple[str, str, str]:
    normalized = path.casefold().replace("/", "\\")
    if any(marker in normalized for marker in _SYSTEM_MARKERS):
        return (
            "leave",
            "SYSTEM/HOT",
            "System/application infrastructure should remain in place; do not junction whole system trees.",
        )
    if any(marker in normalized for marker in _CACHE_MARKERS):
        return (
            "junction_candidate",
            "CACHE",
            "Cache/build tree: prefer application-native cache relocation; junction only if the application has no supported setting.",
        )
    if any(marker in normalized for marker in _NATIVE_RELOCATE_MARKERS):
        return (
            "native_relocate",
            "DATA",
            "User/library data: prefer Windows/application supported location change before using a junction.",
        )
    if any(marker in normalized for marker in _ARCHIVE_MARKERS):
        return (
            "archive_candidate",
            "ARCHIVE",
            "Cold/archive-like tree: good candidate for HDD/cold storage after copy and verification.",
        )
    if size >= 8 * 1024**3:
        return (
            "review",
            "LARGE",
            "Large directory with no safe automatic classification. Review owner/application before relocation.",
        )
    return (
        "leave",
        "UNKNOWN",
        "No strong relocation signal; leave in place until ownership and workload are known.",
    )


def relocation_plan(scan_id: int, limit: int = 50) -> dict[str, Any]:
    init_database()
    bounded = max(1, min(500, int(limit)))
    with connect() as connection:
        session = connection.execute(
            """
            SELECT id,root_path,status,files_count,directories_count,bytes_total,completed_at
            FROM scan_sessions WHERE id=?
            """,
            (int(scan_id),),
        ).fetchone()
        if session is None:
            raise KeyError(scan_id)
        rows = connection.execute(
            """
            SELECT path,total_size,total_files,direct_files,child_directories
            FROM directories
            WHERE scan_id=? AND total_size>0
            ORDER BY total_size DESC
            LIMIT ?
            """,
            (int(scan_id), bounded),
        ).fetchall()

    items = []
    for row in rows:
        action, classification, reason = _decision(
            str(row["path"]),
            int(row["total_size"] or 0),
        )
        items.append(
            {
                **dict(row),
                "action": action,
                "classification": classification,
                "reason": reason,
                "destructive": False,
                "recommended_sequence": (
                    ["copy", "verify", "switch_path", "delete_old"]
                    if action != "leave"
                    else []
                ),
            }
        )

    return {
        "scan": dict(session),
        "mode": "read_only_advisor",
        "items": items,
        "rules": {
            "never_wholesale_junction": [
                "Windows",
                "Program Files",
                "Program Files (x86)",
                "ProgramData",
                "Users root",
            ],
            "execution_model": "copy -> verify -> switch -> delete old",
        },
    }
