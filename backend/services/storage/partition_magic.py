from __future__ import annotations

import os
import subprocess

from backend.config import settings
from backend.services.storage.windows_disks import list_windows_disks


class DiskWriteBlocked(RuntimeError):
    pass


VALID_CLUSTER_SIZES = {4096, 8192, 16384, 32768, 65536}


def format_plan(
    disk_number: int,
    filesystem: str = "NTFS",
    label: str = "Storage",
    allocation_unit: int = 4096,
) -> dict:
    disks = {int(d["number"]): d for d in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")
    fs = filesystem.upper()
    if fs not in {"NTFS", "EXFAT"}:
        raise ValueError("Only NTFS and exFAT are supported")
    if allocation_unit not in VALID_CLUSTER_SIZES:
        raise ValueError("Unsupported allocation unit size")
    if not label or len(label) > 32:
        raise ValueError("Invalid volume label")
    return {
        "disk": disk,
        "filesystem": fs,
        "label": label,
        "allocation_unit": allocation_unit,
        "partition_style": "GPT",
        "layout": "single_partition",
        "confirmation": f"FORMAT DISK {disk_number}",
        "allowed": settings.allow_disk_writes and not disk["protected"],
        "warning": "This operation destroys all existing partitions and data on the selected disk.",
        "recommended_for_mixed_storage": allocation_unit == 4096,
    }


def execute_format(
    disk_number: int,
    confirmation: str,
    filesystem: str = "NTFS",
    label: str = "Storage",
    allocation_unit: int = 4096,
) -> dict:
    plan = format_plan(disk_number, filesystem=filesystem, label=label, allocation_unit=allocation_unit)
    if not settings.allow_disk_writes:
        raise DiskWriteBlocked("DS_ALLOW_DISK_WRITES is disabled")
    if plan["disk"]["protected"]:
        raise DiskWriteBlocked("Protected system/boot/application disk")
    if confirmation != plan["confirmation"]:
        raise DiskWriteBlocked("Typed confirmation does not match")

    # Re-read immediately before the destructive call to catch a changed disk identity/protection state.
    fresh = format_plan(disk_number, filesystem=filesystem, label=label, allocation_unit=allocation_unit)
    if fresh["disk"].get("unique_id") != plan["disk"].get("unique_id") or fresh["disk"].get("size") != plan["disk"].get("size"):
        raise DiskWriteBlocked("Disk identity changed between plan and execution")
    if fresh["disk"]["protected"]:
        raise DiskWriteBlocked("Disk became protected")

    script = r'''
$ErrorActionPreference = "Stop"
$diskNumber = [int]$env:DISKSHELL_DISK_NUMBER
$fileSystem = [string]$env:DISKSHELL_FILE_SYSTEM
$label = [string]$env:DISKSHELL_VOLUME_LABEL
$allocation = [int]$env:DISKSHELL_ALLOCATION_UNIT
$disk = Get-Disk -Number $diskNumber
if ($disk.IsSystem -or $disk.IsBoot) { throw "Protected disk" }
Set-Disk -Number $diskNumber -IsOffline $false
Set-Disk -Number $diskNumber -IsReadOnly $false
Clear-Disk -Number $diskNumber -RemoveData -RemoveOEM -Confirm:$false
Initialize-Disk -Number $diskNumber -PartitionStyle GPT
$partition = New-Partition -DiskNumber $diskNumber -UseMaximumSize -AssignDriveLetter
Format-Volume -Partition $partition -FileSystem $fileSystem -NewFileSystemLabel $label -AllocationUnitSize $allocation -Confirm:$false
$partition | Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,AllocationUnitSize,Size,SizeRemaining | ConvertTo-Json -Compress
'''
    env = os.environ.copy()
    env.update(
        {
            "DISKSHELL_DISK_NUMBER": str(disk_number),
            "DISKSHELL_FILE_SYSTEM": plan["filesystem"],
            "DISKSHELL_VOLUME_LABEL": plan["label"],
            "DISKSHELL_ALLOCATION_UNIT": str(plan["allocation_unit"]),
        }
    )
    result = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Disk format failed")
    return {"status": "completed", "output": result.stdout.strip()}
