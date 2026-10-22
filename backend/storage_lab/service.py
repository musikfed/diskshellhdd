from __future__ import annotations

import math
import platform
import random
import re
import statistics
import subprocess
import time
from pathlib import Path

from backend.config import settings
from backend.core.database import connect


CLASS_LANES = {
    "video": "A-media-sequential",
    "audio": "A-media-sequential",
    "photo": "B-photo-mixed",
    "document": "C-interactive",
    "archive": "D-cold",
    "backup": "D-cold",
    "disk_image": "D-cold",
    "development": "C-interactive",
    "code": "C-interactive",
    "design": "C-interactive",
    "executable": "D-cold",
    "cache": "E-temporary",
    "other": "C-interactive",
}


def simulate_interleave(scan_id: int, chunk_size: int = 8 * 1024 * 1024) -> dict:
    if chunk_size < 256 * 1024 or chunk_size > 64 * 1024 * 1024:
        raise ValueError("chunk_size must be between 256 KiB and 64 MiB")

    with connect() as connection:
        files = [dict(row) for row in connection.execute("SELECT path, category, size FROM files WHERE scan_id = ? ORDER BY size DESC", (scan_id,)).fetchall()]

    lanes: dict[str, list[dict]] = {}
    for row in files:
        lane = CLASS_LANES.get(row["category"], "C-interactive")
        lanes.setdefault(lane, []).append(row)

    lane_names = sorted(lanes)
    positions = {lane: 0 for lane in lane_names}
    segment_positions: dict[str, int] = {}
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
            segment_index = segment_positions.get(row["path"], 0)
            segments = max(1, math.ceil(row["size"] / chunk_size))
            remaining = row["size"] - segment_index * chunk_size
            length = min(chunk_size, max(0, remaining))
            if length <= 0 or segment_index >= segments:
                positions[lane] += 1
                continue
            extents.append({"logical_offset": logical_offset, "length": length, "lane": lane, "path": row["path"], "segment": segment_index})
            logical_offset += length
            segment_positions[row["path"]] = segment_index + 1
            if segment_index + 1 >= segments:
                positions[lane] += 1

    return {
        "mode": "simulation",
        "scan_id": scan_id,
        "chunk_size": chunk_size,
        "lanes": lane_names,
        "extents": extents,
        "extent_moves_allowed": settings.allow_extent_moves,
        "note": "Logical target layout only. HDD firmware still hides platter/head/angular geometry and remapping.",
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
    pattern = re.compile(r"VCN:\s*(?P<vcn>0x[0-9a-fA-F]+).*?Clusters:\s*(?P<clusters>0x[0-9a-fA-F]+).*?LCN:\s*(?P<lcn>0x[0-9a-fA-F]+)", re.IGNORECASE)
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if match:
            extents.append({"vcn": int(match.group("vcn"), 16), "clusters": int(match.group("clusters"), 16), "lcn": int(match.group("lcn"), 16)})
    return {"supported": True, "path": str(file_path), "extents": extents, "extent_count": len(extents), "raw": result.stdout}


def benchmark_file(path: str | Path, block_size: int = 4 * 1024 * 1024, samples: int = 48) -> dict:
    file_path = Path(path).expanduser().resolve(strict=True)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    block_size = min(max(block_size, 256 * 1024), 32 * 1024 * 1024)
    samples = min(max(samples, 4), 256)
    size = file_path.stat().st_size
    if size == 0:
        raise ValueError("Cannot benchmark an empty file")
    read_size = min(block_size, size)

    sequential_latencies = []
    sequential_bytes = 0
    sequential_start = time.perf_counter()
    with file_path.open("rb", buffering=0) as handle:
        for _ in range(samples):
            start = time.perf_counter()
            chunk = handle.read(read_size)
            if not chunk:
                handle.seek(0)
                chunk = handle.read(read_size)
            sequential_latencies.append((time.perf_counter() - start) * 1000)
            sequential_bytes += len(chunk)
    sequential_elapsed = time.perf_counter() - sequential_start

    rng = random.Random(0)
    random_latencies = []
    random_bytes = 0
    max_offset = max(0, size - read_size)
    random_start = time.perf_counter()
    with file_path.open("rb", buffering=0) as handle:
        for _ in range(samples):
            offset = 0 if not max_offset else rng.randrange(0, max_offset + 1)
            start = time.perf_counter()
            handle.seek(offset)
            chunk = handle.read(read_size)
            random_latencies.append((time.perf_counter() - start) * 1000)
            random_bytes += len(chunk)
    random_elapsed = time.perf_counter() - random_start

    def stats(latencies: list[float], byte_count: int, elapsed: float) -> dict:
        ordered = sorted(latencies)
        p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
        return {
            "bytes": byte_count,
            "seconds": elapsed,
            "mib_per_second": (byte_count / 1024**2) / elapsed if elapsed else 0,
            "latency_ms_median": statistics.median(ordered),
            "latency_ms_p95": ordered[p95_index],
        }

    result = {
        "path": str(file_path),
        "file_size": size,
        "block_size": read_size,
        "samples": samples,
        "sequential": stats(sequential_latencies, sequential_bytes, sequential_elapsed),
        "random": stats(random_latencies, random_bytes, random_elapsed),
        "note": "Read-only application-level benchmark. OS/HDD caches and firmware scheduling still affect results.",
    }
    with connect() as connection:
        connection.execute("INSERT INTO access_samples(path,operation,latency_ms,bytes_count) VALUES(?,?,?,?)", (str(file_path), "benchmark-sequential", result["sequential"]["latency_ms_median"], sequential_bytes))
        connection.execute("INSERT INTO access_samples(path,operation,latency_ms,bytes_count) VALUES(?,?,?,?)", (str(file_path), "benchmark-random", result["random"]["latency_ms_median"], random_bytes))
        connection.commit()
    return result
