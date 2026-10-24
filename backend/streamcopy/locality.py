from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Any


def first_ntfs_lcn(path: str | Path) -> int | None:
    """Return the first allocated NTFS LCN without spawning fsutil.

    None means unsupported/unavailable/empty/sparse-at-start. This function is
    read-only and intentionally best-effort: transfer safety never depends on it.
    """
    if os.name != "nt":
        return None

    file_path = Path(path)
    try:
        if file_path.stat().st_size <= 0:
            return None

        import win32file  # type: ignore[import-not-found]
        import winioctlcon  # type: ignore[import-not-found]

        share = (
            win32file.FILE_SHARE_READ
            | win32file.FILE_SHARE_WRITE
            | win32file.FILE_SHARE_DELETE
        )
        handle = win32file.CreateFile(
            str(file_path),
            0,
            share,
            None,
            win32file.OPEN_EXISTING,
            win32file.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        try:
            output = win32file.DeviceIoControl(
                handle,
                winioctlcon.FSCTL_GET_RETRIEVAL_POINTERS,
                struct.pack("<q", 0),
                64 * 1024,
            )
        finally:
            handle.Close()
    except Exception:  # noqa: BLE001
        return None

    # RETRIEVAL_POINTERS_BUFFER:
    # DWORD ExtentCount; padding; LARGE_INTEGER StartingVcn;
    # then Extents[] = { LARGE_INTEGER NextVcn; LARGE_INTEGER Lcn; }.
    if len(output) < 32:
        return None
    try:
        extent_count, _starting_vcn = struct.unpack_from("<I4xq", output, 0)
        offset = 16
        for _ in range(int(extent_count)):
            if offset + 16 > len(output):
                break
            _next_vcn, lcn = struct.unpack_from("<qq", output, offset)
            offset += 16
            if int(lcn) >= 0:
                return int(lcn)
    except (struct.error, ValueError):
        return None
    return None


def order_manifest_by_ntfs_locality(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Sort known files by first LCN; unknown files remain stable at the end."""
    decorated: list[tuple[int, int, int, dict[str, Any]]] = []
    known = 0
    unknown = 0

    for original_index, item in enumerate(items):
        lcn = first_ntfs_lcn(item["source_path"])
        if lcn is None:
            unknown += 1
            decorated.append((1, 0, original_index, dict(item)))
        else:
            known += 1
            decorated.append((0, int(lcn), original_index, dict(item)))

    decorated.sort(key=lambda row: (row[0], row[1], row[2]))
    ordered = []
    for new_index, (_unknown_flag, lcn, original_index, item) in enumerate(decorated):
        item["item_index"] = new_index
        item["source_first_lcn"] = None if _unknown_flag else int(lcn)
        item["manifest_original_index"] = int(original_index)
        ordered.append(item)

    return ordered, {
        "mode": "ntfs_first_lcn",
        "files": len(items),
        "known_lcn": known,
        "unknown_lcn": unknown,
        "coverage_percent": round(known * 100 / len(items), 2) if items else 100.0,
    }
