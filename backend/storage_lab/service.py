from __future__ import annotations

import math
import platform
import re
import subprocess
from pathlib import Path

from backend.config import settings
from backend.core.database import connect


CLASS_LANES = {
    "video": "A-media-sequential",
    "audio": "A-media-sequential",
    "photo": "B-photo-mixed",
    "document": "C-interactive",
    "archive": "D-cold",
    "disk_image": "D-cold",
    "development": "C-interactive",
    "code": "C-interactive",
    "cache": "E-temporary",
    "other": "C-interactive",
}


def simulate_interleave(scan_id: int, chunk_size: int = 8 * 1024 * 1024) -> dict:
    if chunk_size < 256 * 1024 or chunk_size > 64 * 1024 * 1024:
        raise ValueError("chunk_size must be between 256 KiB and 64 MiB")

    with connect() as connection:
        files = [
            dict(row)
            for row in connection.execute(
                "SELECT path, category, size FROM files WHERE scan_id = ? ORDER BY size DESC",
                (scan_id,),
            ).fetchall()
        ]

    lanes: dict[str, list[dict]] = {}
    for row in files:
        lane = CLASS_LANES.get(row["category"], "C-interactive")
        lanes.setdefault(lane, []).append(row)

    lane_names = sorted(lanes)
    positions = {lane: 0 for lane in lane_names}
    extents: list[dict] = []
    logical_offset = 0
    active = True
    while active and len(extents) < 50_000:
        active = False
        for lane in lane_names:
            queue = lanes[lane]
            index = positions[lane]
            if index >= len(queue):
                continue
            active = True
            row = queue[index]
            segments = max(1, math.ceil(row["size"] / chunk_size))
            segment_index = sum(
                1 for item in extents if item["path"] == row["path"]
            )
            remaining = row["size"] - segment_index * chunk_size
            length = min(chunk_size, max(0, remaining))
            if length <= 0 or segment_index >= segments:
                positions[lane] += 1
                continue
            extents.append(
                {
                    "logical_offset": logical_offset,
                    "length": length,
                    "lane": lane,
                    "path": row["path"],
                    "segment": segment_index,
                }
            )
            logical_offset += length
            if segment_index + 1 >= segments:
                positions[lane] += 1

    return {
        "mode": "simulation",
        "scan_id": scan_id,
        "chunk_size": chunk_size,
        "lanes": lane_names,
        "extents": extents,
        "extent_moves_allowed": settings.allow_extent_moves,
        "note": "Logical target layout only; HDD firmware physical geometry remains hidden.",
    }


def query_file_extents(path: str | Path) -> dict:
    file_path = Path(path).expanduser().resolve(strict=True)
    if platform.system() != "Windows":
        return {"supported": False, "reason": "Windows/NTFS only"}
    result = subprocess.run(
        ["fsutil.exe", "file", "queryextents", str(file_path)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        return {"supported": False, "reason": result.stderr.strip() or result.stdout.strip()}

    extents = []
    pattern = re.compile(
        r"VCN:\s*(?P<vcn>0x[0-9a-fA-F]+).*?Clusters:\s*(?P<clusters>0x[0-9a-fA-F]+).*?LCN:\s*(?P<lcn>0x[0-9a-fA-F]+)",
        re.IGNORECASE,
    )
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if match:
            extents.append(
                {
                    "vcn": int(match.group("vcn"), 16),
                    "clusters": int(match.group("clusters"), 16),
                    "lcn": int(match.group("lcn"), 16),
                }
            )
    return {"supported": True, "path": str(file_path), "extents": extents, "raw": result.stdout}
