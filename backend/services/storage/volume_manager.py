from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any

from backend.services.storage.windows_disks import DiskDetectionError, list_windows_disks
from backend.services.storage.write_authorization import DiskWriteBlocked, require_disk_write_authorized


VALID_CLUSTER_SIZES = {4096, 8192, 16384, 32768, 65536}
VALID_FILESYSTEMS = {"NTFS", "EXFAT"}


def _get_disk(disk_number: int) -> dict[str, Any]:
    disks = {int(disk["number"]): disk for disk in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")
    return disk


def _validate_filesystem(filesystem: str) -> str:
    value = filesystem.upper()
    if value not in VALID_FILESYSTEMS:
        raise ValueError("Only NTFS and exFAT are supported")
    return value


def _validate_label(label: str) -> str:
    value = label.strip()
    if not value or len(value) > 32:
        raise ValueError("Volume label must contain 1..32 characters")
    return value


def _validate_cluster(allocation_unit: int) -> int:
    value = int(allocation_unit)
    if value not in VALID_CLUSTER_SIZES:
        raise ValueError("Unsupported allocation unit size")
    return value


def _validate_drive_letter(letter: str | None) -> str | None:
    if letter is None or not str(letter).strip():
        return None
    value = str(letter).strip().upper().rstrip(":")
    if not re.fullmatch(r"[A-Z]", value):
        raise ValueError("Drive letter must be A..Z")
    return value


def initialize_plan(disk_number: int, partition_style: str = "GPT") -> dict[str, Any]:
    disk = _get_disk(disk_number)
    style = partition_style.upper()
    if style not in {"GPT", "MBR"}:
        raise ValueError("Partition style must be GPT or MBR")
    if disk.get("protected"):
        raise DiskWriteBlocked("Protected system/boot/application disk")
    if str(disk.get("partition_style") or "").upper() not in {"RAW", "UNKNOWN"}:
        raise ValueError("Disk is already initialized; changing partition style requires a destructive reset")
    return {
        "disk": disk,
        "partition_style": style,
        "confirmation": f"INITIALIZE DISK {disk_number} {style}",
        "warning": "Initializing a disk writes a new partition table. Use only on the intended disk.",
    }


def initialize_disk(disk_number: int, partition_style: str, confirmation: str) -> dict[str, Any]:
    plan = initialize_plan(disk_number, partition_style)
    require_disk_write_authorized(plan["disk"])
    if confirmation != plan["confirmation"]:
        raise DiskWriteBlocked("Typed confirmation does not match")

    fresh = _get_disk(disk_number)
    require_disk_write_authorized(fresh)
    if (
        fresh.get("unique_id") != plan["disk"].get("unique_id")
        or int(fresh.get("size") or 0) != int(plan["disk"].get("size") or 0)
    ):
        raise DiskWriteBlocked("Disk identity changed between plan and execution")

    script = r"""
$ErrorActionPreference = "Stop"
$diskNumber = [int]$env:DISKSHELL_DISK_NUMBER
$style = [string]$env:DISKSHELL_PARTITION_STYLE
Initialize-Disk -Number $diskNumber -PartitionStyle $style -PassThru |
  Select-Object Number,FriendlyName,PartitionStyle,Size,UniqueId |
  ConvertTo-Json -Compress
"""
    return _run_storage_script(
        script,
        {
            "DISKSHELL_DISK_NUMBER": str(disk_number),
            "DISKSHELL_PARTITION_STYLE": plan["partition_style"],
        },
    )


def create_partition_plan(
    disk_number: int,
    size_bytes: int | None = None,
    filesystem: str = "NTFS",
    label: str = "Data",
    allocation_unit: int = 4096,
    drive_letter: str | None = None,
) -> dict[str, Any]:
    disk = _get_disk(disk_number)
    if disk.get("protected"):
        raise DiskWriteBlocked("Protected system/boot/application disk")
    if str(disk.get("partition_style") or "").upper() in {"RAW", "UNKNOWN"}:
        raise ValueError("Initialize the disk before creating partitions")

    fs = _validate_filesystem(filesystem)
    volume_label = _validate_label(label)
    cluster = _validate_cluster(allocation_unit)
    letter = _validate_drive_letter(drive_letter)
    largest = int(disk.get("largest_free_extent") or 0)
    if largest <= 0:
        raise ValueError("Disk has no unallocated extent large enough for a new partition")

    requested = largest if size_bytes in {None, 0} else int(size_bytes)
    if requested <= 0 or requested > largest:
        raise ValueError("Requested partition size exceeds the largest free extent")

    return {
        "disk": disk,
        "size_bytes": requested,
        "use_maximum": size_bytes in {None, 0},
        "filesystem": fs,
        "label": volume_label,
        "allocation_unit": cluster,
        "drive_letter": letter,
        "confirmation": f"CREATE PARTITION DISK {disk_number}",
        "warning": "This writes the partition table and creates/formats a new volume in unallocated space.",
    }


def create_partition(
    disk_number: int,
    confirmation: str,
    size_bytes: int | None = None,
    filesystem: str = "NTFS",
    label: str = "Data",
    allocation_unit: int = 4096,
    drive_letter: str | None = None,
) -> dict[str, Any]:
    plan = create_partition_plan(
        disk_number,
        size_bytes=size_bytes,
        filesystem=filesystem,
        label=label,
        allocation_unit=allocation_unit,
        drive_letter=drive_letter,
    )
    require_disk_write_authorized(plan["disk"])
    if confirmation != plan["confirmation"]:
        raise DiskWriteBlocked("Typed confirmation does not match")

    fresh = _get_disk(disk_number)
    require_disk_write_authorized(fresh)
    if (
        fresh.get("unique_id") != plan["disk"].get("unique_id")
        or int(fresh.get("size") or 0) != int(plan["disk"].get("size") or 0)
    ):
        raise DiskWriteBlocked("Disk identity changed between plan and execution")
    if int(fresh.get("largest_free_extent") or 0) < int(plan["size_bytes"]):
        raise DiskWriteBlocked("Available free extent changed; rebuild the create-partition plan")

    script = r"""
$ErrorActionPreference = "Stop"
$diskNumber = [int]$env:DISKSHELL_DISK_NUMBER
$size = [int64]$env:DISKSHELL_PARTITION_SIZE
$useMaximum = [bool]::Parse($env:DISKSHELL_USE_MAXIMUM)
$fileSystem = [string]$env:DISKSHELL_FILE_SYSTEM
$label = [string]$env:DISKSHELL_VOLUME_LABEL
$allocation = [int]$env:DISKSHELL_ALLOCATION_UNIT
$letter = [string]$env:DISKSHELL_DRIVE_LETTER

if ($useMaximum) {
  if ($letter) {
    $partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -DriveLetter $letter
  } else {
    $partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -AssignDriveLetter
  }
} else {
  if ($letter) {
    $partition = New-Partition -DiskNumber $diskNumber -Size $size -DriveLetter $letter
  } else {
    $partition = New-Partition -DiskNumber $diskNumber -Size $size -AssignDriveLetter
  }
}

$volume = Format-Volume -Partition $partition -FileSystem $fileSystem -NewFileSystemLabel $label -AllocationUnitSize $allocation -Confirm:$false
[PSCustomObject]@{
  DiskNumber = $partition.DiskNumber
  PartitionNumber = $partition.PartitionNumber
  DriveLetter = [string]$partition.DriveLetter
  PartitionSize = [int64]$partition.Size
  FileSystem = [string]$volume.FileSystem
  Label = [string]$volume.FileSystemLabel
  AllocationUnitSize = [int]$volume.AllocationUnitSize
  Size = [int64]$volume.Size
  SizeRemaining = [int64]$volume.SizeRemaining
} | ConvertTo-Json -Compress
"""
    return _run_storage_script(
        script,
        {
            "DISKSHELL_DISK_NUMBER": str(disk_number),
            "DISKSHELL_PARTITION_SIZE": str(plan["size_bytes"]),
            "DISKSHELL_USE_MAXIMUM": str(bool(plan["use_maximum"])),
            "DISKSHELL_FILE_SYSTEM": plan["filesystem"],
            "DISKSHELL_VOLUME_LABEL": plan["label"],
            "DISKSHELL_ALLOCATION_UNIT": str(plan["allocation_unit"]),
            "DISKSHELL_DRIVE_LETTER": plan["drive_letter"] or "",
        },
    )


def assign_drive_letter(
    disk_number: int,
    partition_number: int,
    drive_letter: str,
    confirmation: str,
) -> dict[str, Any]:
    disk = _get_disk(disk_number)
    require_disk_write_authorized(disk)
    letter = _validate_drive_letter(drive_letter)
    assert letter is not None
    expected = f"ASSIGN {letter}: DISK {disk_number} PARTITION {partition_number}"
    if confirmation != expected:
        raise DiskWriteBlocked("Typed confirmation does not match")

    script = r"""
$ErrorActionPreference = "Stop"
$diskNumber = [int]$env:DISKSHELL_DISK_NUMBER
$partitionNumber = [int]$env:DISKSHELL_PARTITION_NUMBER
$letter = [char]$env:DISKSHELL_DRIVE_LETTER
Set-Partition -DiskNumber $diskNumber -PartitionNumber $partitionNumber -NewDriveLetter $letter
Get-Partition -DiskNumber $diskNumber -PartitionNumber $partitionNumber |
  Select-Object DiskNumber,PartitionNumber,DriveLetter,Size,Type |
  ConvertTo-Json -Compress
"""
    return _run_storage_script(
        script,
        {
            "DISKSHELL_DISK_NUMBER": str(disk_number),
            "DISKSHELL_PARTITION_NUMBER": str(int(partition_number)),
            "DISKSHELL_DRIVE_LETTER": letter,
        },
    )


def _run_storage_script(script: str, extra_env: dict[str, str]) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(extra_env)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
        creationflags=creation_flags,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Windows Storage operation failed")
    output = result.stdout.strip()
    if not output:
        return {"status": "completed"}
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = {"raw_output": output}
    return {"status": "completed", "result": payload}


__all__ = [
    "DiskDetectionError",
    "DiskWriteBlocked",
    "VALID_CLUSTER_SIZES",
    "assign_drive_letter",
    "create_partition",
    "create_partition_plan",
    "initialize_disk",
    "initialize_plan",
]
