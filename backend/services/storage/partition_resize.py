from __future__ import annotations

import os
import subprocess
from typing import Any

from backend.services.storage.windows_disks import list_windows_disks
from backend.services.storage.windows_privileges import require_process_elevated
from backend.services.storage.write_authorization import (
    DiskWriteBlocked,
    require_disk_write_authorized,
)


def _disk_and_partition(disk_number: int, partition_number: int) -> tuple[dict[str, Any], dict[str, Any]]:
    disks = {int(item["number"]): item for item in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")
    partition = next(
        (
            item
            for item in disk.get("partitions") or []
            if int(item.get("partition_number") or -1) == int(partition_number)
        ),
        None,
    )
    if partition is None:
        raise ValueError("Partition not found")
    return disk, partition


def _neighbor_gaps(disk: dict[str, Any], partition: dict[str, Any]) -> tuple[int, int]:
    parts = sorted(
        [item for item in disk.get("partitions") or [] if int(item.get("size") or 0) > 0],
        key=lambda item: int(item.get("offset") or 0),
    )
    index = next(
        idx
        for idx, item in enumerate(parts)
        if int(item.get("partition_number") or -1)
        == int(partition.get("partition_number") or -2)
    )
    start = int(partition.get("offset") or 0)
    end = start + int(partition.get("size") or 0)
    prev_end = 0 if index == 0 else int(parts[index - 1].get("offset") or 0) + int(
        parts[index - 1].get("size") or 0
    )
    next_start = int(disk.get("size") or 0) if index == len(parts) - 1 else int(
        parts[index + 1].get("offset") or 0
    )
    return max(0, start - prev_end), max(0, next_start - end)


def boundary_plan(
    disk_number: int,
    partition_number: int,
    *,
    boundary: str,
    target_size_bytes: int | None = None,
    target_start_offset: int | None = None,
) -> dict[str, Any]:
    disk, partition = _disk_and_partition(disk_number, partition_number)
    before_gap, after_gap = _neighbor_gaps(disk, partition)
    current_size = int(partition.get("size") or 0)
    current_start = int(partition.get("offset") or 0)
    current_end = current_start + current_size
    bound = str(boundary).casefold()

    base = {
        "disk": disk,
        "partition": partition,
        "boundary": bound,
        "current_start": current_start,
        "current_end": current_end,
        "current_size": current_size,
        "free_before": before_gap,
        "free_after": after_gap,
        "protected_disk": bool(disk.get("protected")),
        "execution_supported": False,
        "confirmation": None,
        "warnings": [],
    }

    if bound == "start":
        if target_start_offset is None:
            raise ValueError("target_start_offset is required for start-boundary planning")
        target_start = int(target_start_offset)
        if target_start < 0 or target_start >= current_end:
            raise ValueError("target_start_offset is outside the current partition range")
        delta = target_start - current_start
        if delta < 0 and abs(delta) > before_gap:
            raise ValueError("Not enough contiguous unallocated space before the partition")
        base.update(
            {
                "target_start": target_start,
                "target_end": current_end,
                "target_size": current_end - target_start,
                "direction": "toward_disk_start" if delta < 0 else "away_from_disk_start",
                "strategy": "relocate_or_recreate",
                "execution_supported": False,
            }
        )
        base["warnings"].append(
            "Windows Resize-Partition changes the end/size of a partition; it does not move "
            "the partition start. Moving the start boundary requires data relocation, "
            "recreate/restore, or an offline filesystem-aware tool."
        )
        if disk.get("is_boot") or disk.get("is_system"):
            base["warnings"].append(
                "System/boot partition start relocation must be planned offline with a verified "
                "backup/recovery path. DiskShell will not execute it in the live 0.8.0 planner."
            )
        return base

    if bound != "end":
        raise ValueError("boundary must be start or end")
    if target_size_bytes is None:
        raise ValueError("target_size_bytes is required for end-boundary planning")

    target_size = int(target_size_bytes)
    if target_size <= 0:
        raise ValueError("target_size_bytes must be positive")
    target_end = current_start + target_size
    direction = "grow_end" if target_size > current_size else "shrink_end"
    supported_min = partition.get("supported_size_min")
    supported_max = partition.get("supported_size_max")

    if supported_min is not None and target_size < int(supported_min):
        raise ValueError(
            f"Target size is below Windows supported minimum: {int(supported_min)} bytes"
        )
    if supported_max is not None and target_size > int(supported_max):
        raise ValueError(
            f"Target size exceeds Windows supported maximum: {int(supported_max)} bytes"
        )
    if target_size > current_size and target_size - current_size > after_gap:
        raise ValueError("Not enough contiguous unallocated space after the partition")

    protected = bool(disk.get("protected"))
    execution_supported = not protected and supported_min is not None and supported_max is not None
    base.update(
        {
            "target_start": current_start,
            "target_end": target_end,
            "target_size": target_size,
            "direction": direction,
            "strategy": "windows_resize_partition",
            "supported_size_min": supported_min,
            "supported_size_max": supported_max,
            "execution_supported": execution_supported,
            "confirmation": (
                f"RESIZE DISK {disk_number} PARTITION {partition_number} TO {target_size}"
                if execution_supported
                else None
            ),
        }
    )
    base["warnings"].append(
        "Resize changes filesystem/partition size in place. Maintain an independent backup "
        "and do not interrupt power or storage connectivity during execution."
    )
    if protected:
        base["warnings"].append(
            "This is a protected system/boot/application disk. DiskShell exposes a read-only "
            "plan only; live write execution remains blocked."
        )
    return base


def execute_end_resize(
    disk_number: int,
    partition_number: int,
    *,
    target_size_bytes: int,
    confirmation: str,
) -> dict[str, Any]:
    plan = boundary_plan(
        disk_number,
        partition_number,
        boundary="end",
        target_size_bytes=target_size_bytes,
    )
    if not plan["execution_supported"]:
        raise DiskWriteBlocked("Resize execution is not supported for this protected/unsupported partition")
    require_disk_write_authorized(plan["disk"])
    require_process_elevated()
    if confirmation != plan["confirmation"]:
        raise DiskWriteBlocked("Typed confirmation does not match")

    fresh = boundary_plan(
        disk_number,
        partition_number,
        boundary="end",
        target_size_bytes=target_size_bytes,
    )
    for key in ("unique_id", "serial_number", "size"):
        if fresh["disk"].get(key) != plan["disk"].get(key):
            raise DiskWriteBlocked("Disk identity changed between resize plan and execution")
    require_disk_write_authorized(fresh["disk"])

    script = r'''
$ErrorActionPreference = "Stop"
$diskNumber = [int]$env:DISKSHELL_DISK_NUMBER
$partitionNumber = [int]$env:DISKSHELL_PARTITION_NUMBER
$targetSize = [int64]$env:DISKSHELL_TARGET_SIZE
Resize-Partition -DiskNumber $diskNumber -PartitionNumber $partitionNumber -Size $targetSize -Confirm:$false
$p = Get-Partition -DiskNumber $diskNumber -PartitionNumber $partitionNumber
[PSCustomObject]@{
  DiskNumber = [int]$p.DiskNumber
  PartitionNumber = [int]$p.PartitionNumber
  Offset = [int64]$p.Offset
  Size = [int64]$p.Size
  DriveLetter = if ($p.DriveLetter) { [string]$p.DriveLetter } else { $null }
} | ConvertTo-Json -Compress
'''
    env = os.environ.copy()
    env.update(
        {
            "DISKSHELL_DISK_NUMBER": str(disk_number),
            "DISKSHELL_PARTITION_NUMBER": str(partition_number),
            "DISKSHELL_TARGET_SIZE": str(int(target_size_bytes)),
        }
    )
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=600,
        check=False,
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Resize-Partition failed")
    return {"status": "completed", "plan": plan, "output": result.stdout.strip()}
