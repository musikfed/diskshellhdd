from __future__ import annotations

import os
import re
import subprocess

from backend.services.storage.filesystem_profiles import (
    filesystem_names,
    filesystem_profile,
    validate_allocation_unit,
    validate_volume_size,
)
from backend.services.storage.windows_disks import list_windows_disks
from backend.services.storage.write_authorization import (
    DiskWriteBlocked,
    require_disk_write_authorized,
    write_state_for_disk,
)


_MIN_CUSTOM_PARTITION_BYTES = 16 * 1024 * 1024


def _drive_letter(value: str | None) -> str | None:
    if value is None or not str(value).strip():
        return None
    letter = str(value).strip().upper().rstrip(":")
    if not re.fullmatch(r"[A-Z]", letter):
        raise ValueError("Drive letter must be A..Z")
    return letter


def format_plan(
    disk_number: int,
    filesystem: str = "NTFS",
    label: str = "Storage",
    allocation_unit: int = 4096,
    size_bytes: int | None = None,
    drive_letter: str | None = None,
) -> dict:
    disks = {int(d["number"]): d for d in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")

    fs = filesystem.upper()
    if fs not in filesystem_names():
        supported = ", ".join(sorted(filesystem_names()))
        raise ValueError(f"Unsupported filesystem. Supported: {supported}")

    cluster = validate_allocation_unit(fs, allocation_unit)
    profile = filesystem_profile(fs)
    volume_label = label.strip()
    if not volume_label or len(volume_label) > 32:
        raise ValueError("Invalid volume label; use 1..32 characters")

    letter = _drive_letter(drive_letter)
    use_maximum = size_bytes in {None, 0}
    requested = None if use_maximum else int(size_bytes)
    disk_size = int(disk.get("size") or 0)
    target_size = disk_size if requested is None else requested
    if requested is not None:
        if requested < _MIN_CUSTOM_PARTITION_BYTES:
            raise ValueError("Custom partition must be at least 16 MiB")
        if requested >= disk_size:
            raise ValueError(
                "Custom partition size must be smaller than the physical disk; "
                "leave size empty to use the maximum available space"
            )
    validate_volume_size(fs, cluster, target_size)

    warnings = [
        "This operation destroys all existing partitions and data on the selected disk.",
        profile["warning"],
    ]
    if requested is not None:
        warnings.append(
            "Only the requested first partition will be created; the remaining disk "
            "space stays unallocated for additional partitions."
        )

    return {
        "disk": disk,
        "filesystem": fs,
        "label": volume_label,
        "allocation_unit": cluster,
        "partition_style": "GPT",
        "layout": "single_partition" if use_maximum else "first_partition_custom_size",
        "use_maximum": use_maximum,
        "size_bytes": requested,
        "drive_letter": letter,
        "confirmation": f"FORMAT DISK {disk_number}",
        "allowed": write_state_for_disk(disk)["allowed"],
        "warning": warnings[0],
        "warnings": warnings,
        "filesystem_profile": profile["family"],
        "filesystem_warning": profile["warning"],
        "allocation_profile": (
            "universal"
            if cluster == 4096
            else "mixed_large_storage"
            if fs == "NTFS" and cluster == 16384
            else "large_sequential"
            if cluster == 65536
            else "advanced"
        ),
    }


def execute_format(
    disk_number: int,
    confirmation: str,
    filesystem: str = "NTFS",
    label: str = "Storage",
    allocation_unit: int = 4096,
    size_bytes: int | None = None,
    drive_letter: str | None = None,
) -> dict:
    plan = format_plan(
        disk_number,
        filesystem=filesystem,
        label=label,
        allocation_unit=allocation_unit,
        size_bytes=size_bytes,
        drive_letter=drive_letter,
    )
    require_disk_write_authorized(plan["disk"])
    if confirmation != plan["confirmation"]:
        raise DiskWriteBlocked("Typed confirmation does not match")

    fresh = format_plan(
        disk_number,
        filesystem=filesystem,
        label=label,
        allocation_unit=allocation_unit,
        size_bytes=size_bytes,
        drive_letter=drive_letter,
    )
    if (
        fresh["disk"].get("unique_id") != plan["disk"].get("unique_id")
        or fresh["disk"].get("serial_number") != plan["disk"].get("serial_number")
        or fresh["disk"].get("size") != plan["disk"].get("size")
    ):
        raise DiskWriteBlocked("Disk identity changed between plan and execution")
    require_disk_write_authorized(fresh["disk"])

    script = r'''
$ErrorActionPreference = "Stop"
$diskNumber = [int]$env:DISKSHELL_DISK_NUMBER
$fileSystem = [string]$env:DISKSHELL_FILE_SYSTEM
$label = [string]$env:DISKSHELL_VOLUME_LABEL
$allocation = [int]$env:DISKSHELL_ALLOCATION_UNIT
$useMaximum = [bool]::Parse($env:DISKSHELL_USE_MAXIMUM)
$requestedSize = [int64]$env:DISKSHELL_PARTITION_SIZE
$letter = [string]$env:DISKSHELL_DRIVE_LETTER

$disk = Get-Disk -Number $diskNumber
if ($disk.IsSystem -or $disk.IsBoot) { throw "Protected disk" }

Set-Disk -Number $diskNumber -IsOffline $false
Set-Disk -Number $diskNumber -IsReadOnly $false

$disk = Get-Disk -Number $diskNumber
if ($disk.PartitionStyle -ne "RAW" -or [int64]$disk.AllocatedSize -gt 0) {
  Clear-Disk -Number $diskNumber -RemoveData -RemoveOEM -Confirm:$false
}

$disk = Get-Disk -Number $diskNumber
if ($disk.PartitionStyle -eq "RAW") {
  Initialize-Disk -Number $diskNumber -PartitionStyle GPT | Out-Null
}

if ($useMaximum) {
  if ($letter) {
    $partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -DriveLetter $letter
  } else {
    $partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -AssignDriveLetter
  }
} else {
  if ($letter) {
    $partition = New-Partition -DiskNumber $diskNumber -Size $requestedSize -DriveLetter $letter
  } else {
    $partition = New-Partition -DiskNumber $diskNumber -Size $requestedSize -AssignDriveLetter
  }
}

$supported = @()
try {
  $rawVolume = $partition | Get-Volume -ErrorAction Stop
  $supported = @($rawVolume | Get-SupportedFileSystems -ErrorAction Stop)
} catch {
  $supported = @()
}
if ($supported.Count -gt 0 -and -not ($supported -contains $fileSystem)) {
  throw "Filesystem $fileSystem is not supported for this volume on this Windows installation. Supported: $($supported -join ', ')"
}

$volume = Format-Volume -Partition $partition -FileSystem $fileSystem -NewFileSystemLabel $label -AllocationUnitSize $allocation -Confirm:$false
[PSCustomObject]@{
  DiskNumber = $partition.DiskNumber
  PartitionNumber = $partition.PartitionNumber
  DriveLetter = [string]$partition.DriveLetter
  PartitionSize = [int64]$partition.Size
  RequestedSize = if ($useMaximum) { $null } else { $requestedSize }
  UseMaximum = $useMaximum
  FileSystem = [string]$volume.FileSystem
  Label = [string]$volume.FileSystemLabel
  AllocationUnitSize = [int]$volume.AllocationUnitSize
  Size = [int64]$volume.Size
  SizeRemaining = [int64]$volume.SizeRemaining
  SupportedFileSystems = @($supported)
} | ConvertTo-Json -Depth 4 -Compress
'''
    env = os.environ.copy()
    env.update(
        {
            "DISKSHELL_DISK_NUMBER": str(disk_number),
            "DISKSHELL_FILE_SYSTEM": plan["filesystem"],
            "DISKSHELL_VOLUME_LABEL": plan["label"],
            "DISKSHELL_ALLOCATION_UNIT": str(plan["allocation_unit"]),
            "DISKSHELL_USE_MAXIMUM": str(bool(plan["use_maximum"])),
            "DISKSHELL_PARTITION_SIZE": str(plan["size_bytes"] or 0),
            "DISKSHELL_DRIVE_LETTER": plan["drive_letter"] or "",
        }
    )
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
        raise RuntimeError(result.stderr.strip() or "Disk format failed")
    return {"status": "completed", "output": result.stdout.strip()}
