from __future__ import annotations

import math
import platform
import random
import re
import statistics
import subprocess
import time
from collections import Counter, deque
from pathlib import Path

from backend.config import settings
from backend.core.database import connect


MIB = 1024 * 1024
GIB = 1024 * MIB

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

# The simulator intentionally uses macro-bands, not tiny fixed stripes.
# Values are target logical extents/bands, not claims about hidden platter geometry.
LANE_POLICIES = {
    "A-media-sequential": {
        "min_band": 128 * MIB,
        "target_band": 512 * MIB,
        "max_band": 1 * GIB,
        "weight": 3,
        "max_extents_per_file": 24,
        "description": "Video/audio: long sequential runs, but still interleaved at macro scale.",
    },
    "B-photo-mixed": {
        "min_band": 64 * MIB,
        "target_band": 192 * MIB,
        "max_band": 512 * MIB,
        "weight": 2,
        "max_extents_per_file": 16,
        "description": "Photos/RAW: medium bands for browse + batch access.",
    },
    "C-interactive": {
        "min_band": 32 * MIB,
        "target_band": 96 * MIB,
        "max_band": 256 * MIB,
        "weight": 2,
        "max_extents_per_file": 12,
        "description": "Documents/code/design: tighter locality for interactive mixed access.",
    },
    "D-cold": {
        "min_band": 256 * MIB,
        "target_band": 1 * GIB,
        "max_band": 2 * GIB,
        "weight": 1,
        "max_extents_per_file": 24,
        "description": "Archives/backups/images: long cold sequential bands.",
    },
    "E-temporary": {
        "min_band": 64 * MIB,
        "target_band": 128 * MIB,
        "max_band": 256 * MIB,
        "weight": 1,
        "max_extents_per_file": 8,
        "description": "Temporary/cache: bounded bands so churn does not dominate the layout.",
    },
}


def _clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def _seek_floor_bytes(
    sequential_mib_s: float,
    seek_ms: float,
    target_seek_overhead: float,
) -> int:
    # Approximate minimum transfer window so one seek is no more than the
    # requested fraction of seek+transfer time.
    throughput = max(1.0, float(sequential_mib_s)) * MIB
    seek_seconds = max(0.1, float(seek_ms)) / 1000.0
    fraction = max(0.005, min(0.20, float(target_seek_overhead)))
    transfer_seconds = seek_seconds * (1.0 - fraction) / fraction
    return int(throughput * transfer_seconds)


def _effective_policy(
    lane: str,
    sequential_mib_s: float,
    seek_ms: float,
    target_seek_overhead: float,
) -> dict:
    base = dict(LANE_POLICIES[lane])
    seek_floor = _seek_floor_bytes(
        sequential_mib_s,
        seek_ms,
        target_seek_overhead,
    )

    # Do not let one benchmark force absurd bands; the lane policy remains the
    # primary bound. The floor only lifts undersized policies.
    lifted_min = _clamp(
        max(int(base["min_band"]), seek_floor),
        16 * MIB,
        int(base["max_band"]),
    )
    target = _clamp(
        max(int(base["target_band"]), lifted_min * 2),
        lifted_min,
        int(base["max_band"]),
    )
    base["effective_min_band"] = lifted_min
    base["effective_target_band"] = target
    base["seek_floor_bytes"] = seek_floor

    transfer_seconds = target / (max(1.0, sequential_mib_s) * MIB)
    seek_seconds = max(0.1, seek_ms) / 1000.0
    base["estimated_seek_overhead"] = (
        seek_seconds / (seek_seconds + transfer_seconds)
        if transfer_seconds > 0
        else 1.0
    )
    return base


def _segment_lengths(file_size: int, policy: dict) -> list[int]:
    size = max(0, int(file_size))
    if size == 0:
        return [0]

    minimum = int(policy["effective_min_band"])
    target = int(policy["effective_target_band"])
    maximum = int(policy["max_band"])
    budget = max(1, int(policy["max_extents_per_file"]))

    min_segments = max(1, math.ceil(size / maximum))
    ideal_segments = max(1, round(size / target))
    max_segments_by_min = max(1, size // minimum)

    # Respect the extent budget when possible, but never violate max-band.
    upper = max(min_segments, min(budget, max_segments_by_min))
    count = _clamp(ideal_segments, min_segments, upper)

    base, remainder = divmod(size, count)
    lengths = [base + (1 if index < remainder else 0) for index in range(count)]

    # Equalized segmentation avoids the classic tiny-tail fragment.
    return lengths


def _build_lane_queues(files: list[dict], policies: dict[str, dict]) -> dict[str, deque]:
    queues: dict[str, deque] = {}
    for row in files:
        lane = CLASS_LANES.get(row["category"], "C-interactive")
        policy = policies[lane]
        queue = queues.setdefault(lane, deque())
        lengths = _segment_lengths(int(row["size"]), policy)
        for segment_index, length in enumerate(lengths):
            queue.append(
                {
                    "path": row["path"],
                    "category": row["category"],
                    "file_size": int(row["size"]),
                    "length": length,
                    "segment": segment_index,
                    "segments_total": len(lengths),
                }
            )
    return queues


def _choose_lane(
    queues: dict[str, deque],
    deficits: dict[str, int],
    policies: dict[str, dict],
    last_lane: str | None,
) -> str | None:
    active = [lane for lane, queue in queues.items() if queue]
    if not active:
        return None

    for lane in active:
        deficits[lane] = deficits.get(lane, 0) + int(policies[lane]["weight"])

    candidates = [lane for lane in active if lane != last_lane] or active
    lane = max(candidates, key=lambda name: (deficits.get(name, 0), name))
    deficits[lane] -= sum(int(policies[name]["weight"]) for name in active)
    return lane


def simulate_interleave(
    scan_id: int,
    sequential_mib_s: float = 150.0,
    seek_ms: float = 10.0,
    target_seek_overhead: float = 0.02,
    max_layout_extents: int = 50_000,
) -> dict:
    if not 10 <= sequential_mib_s <= 1000:
        raise ValueError("sequential_mib_s must be between 10 and 1000")
    if not 0.1 <= seek_ms <= 100:
        raise ValueError("seek_ms must be between 0.1 and 100")
    if not 0.005 <= target_seek_overhead <= 0.20:
        raise ValueError("target_seek_overhead must be between 0.5% and 20%")
    if not 100 <= max_layout_extents <= 200_000:
        raise ValueError("max_layout_extents must be between 100 and 200000")

    with connect() as connection:
        files = [
            dict(row)
            for row in connection.execute(
                """
                SELECT path, category, size
                FROM files
                WHERE scan_id = ?
                ORDER BY size DESC, path
                """,
                (scan_id,),
            ).fetchall()
        ]

    lane_names = sorted(
        {
            CLASS_LANES.get(row["category"], "C-interactive")
            for row in files
        }
    )
    policies = {
        lane: _effective_policy(
            lane,
            sequential_mib_s,
            seek_ms,
            target_seek_overhead,
        )
        for lane in lane_names
    }
    queues = _build_lane_queues(files, policies)

    extents: list[dict] = []
    bands: list[dict] = []
    deficits = {lane: 0 for lane in lane_names}
    logical_offset = 0
    last_lane: str | None = None
    lane_band_index = Counter()
    truncated = False

    while len(extents) < max_layout_extents:
        lane = _choose_lane(queues, deficits, policies, last_lane)
        if lane is None:
            break

        policy = policies[lane]
        target_band = int(policy["effective_target_band"])
        band_start = logical_offset
        band_bytes = 0
        band_extent_start = len(extents)
        band_files: set[str] = set()

        while queues[lane] and band_bytes < target_band:
            segment = queues[lane][0]

            # Small files stay whole. Large-file segments were pre-sized with
            # equalized lengths, so we never create a tiny remainder here.
            if (
                band_bytes > 0
                and band_bytes + int(segment["length"]) > int(policy["max_band"])
            ):
                break

            queues[lane].popleft()
            length = int(segment["length"])
            extents.append(
                {
                    "logical_offset": logical_offset,
                    "length": length,
                    "lane": lane,
                    "path": segment["path"],
                    "category": segment["category"],
                    "segment": segment["segment"],
                    "segments_total": segment["segments_total"],
                    "file_size": segment["file_size"],
                    "band_index": len(bands),
                    "lane_band_index": lane_band_index[lane],
                }
            )
            logical_offset += length
            band_bytes += length
            band_files.add(segment["path"])

            if len(extents) >= max_layout_extents:
                truncated = any(queue for queue in queues.values())
                break

        if len(extents) == band_extent_start:
            # Safety valve for an unexpected policy/queue corner case.
            break

        bands.append(
            {
                "index": len(bands),
                "lane": lane,
                "logical_offset": band_start,
                "length": band_bytes,
                "extent_count": len(extents) - band_extent_start,
                "file_count": len(band_files),
            }
        )
        lane_band_index[lane] += 1
        last_lane = lane

        if truncated:
            break

    per_file = Counter()
    for extent in extents:
        per_file[extent["path"]] += 1

    extent_lengths = [int(extent["length"]) for extent in extents if extent["length"] > 0]
    lane_stats = {}
    for lane in lane_names:
        lane_extents = [item for item in extents if item["lane"] == lane]
        lane_bands = [item for item in bands if item["lane"] == lane]
        lane_stats[lane] = {
            "bytes": sum(int(item["length"]) for item in lane_extents),
            "extents": len(lane_extents),
            "bands": len(lane_bands),
            "target_band": int(policies[lane]["effective_target_band"]),
            "min_band": int(policies[lane]["effective_min_band"]),
            "max_band": int(policies[lane]["max_band"]),
            "weight": int(policies[lane]["weight"]),
            "estimated_seek_overhead": float(policies[lane]["estimated_seek_overhead"]),
            "description": policies[lane]["description"],
        }

    return {
        "mode": "adaptive_macro_interleave",
        "scan_id": scan_id,
        "inputs": {
            "sequential_mib_s": sequential_mib_s,
            "seek_ms": seek_ms,
            "target_seek_overhead": target_seek_overhead,
            "max_layout_extents": max_layout_extents,
        },
        "lanes": lane_names,
        "lane_stats": lane_stats,
        "bands": bands,
        "extents": extents,
        "metrics": {
            "files": len(files),
            "bands": len(bands),
            "extents": len(extents),
            "fragmented_files": sum(1 for count in per_file.values() if count > 1),
            "max_extents_per_file": max(per_file.values(), default=0),
            "median_extent_bytes": (
                int(statistics.median(extent_lengths)) if extent_lengths else 0
            ),
            "smallest_extent_bytes": min(extent_lengths, default=0),
            "largest_extent_bytes": max(extent_lengths, default=0),
            "truncated": truncated,
        },
        "extent_moves_allowed": settings.allow_extent_moves,
        "note": (
            "Simulation only. This is bounded macro-interleave over logical "
            "LCN/LBA-visible placement. HDD firmware still hides platter/head/"
            "angular geometry, remapping, caches, read-ahead and command scheduling."
        ),
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
