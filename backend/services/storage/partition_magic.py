from __future__ import annotations

import subprocess

from backend.config import settings
from backend.services.storage.windows_disks import list_windows_disks


class DiskWriteBlocked(RuntimeError):
    pass


def format_plan(disk_number: int, filesystem: str = "NTFS", label: str = "Storage") -> dict:
    disks = {int(d["number"]): d for d in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")
    return {
        "disk": disk,
        "filesystem": filesystem.upper(),
        "label": label,
        "partition_style": "GPT",
        "layout": "single_partition",
        "confirmation": f"FORMAT DISK {disk_number}",
        "allowed": settings.allow_disk_writes and not disk["protected"],
        "warning": "This operation destroys all existing partitions and data on the selected disk.",
    }


def execute_format(
    disk_number: int,
    confirmation: str,
    filesystem: str = "NTFS",
    label: str = "Storage",
) -> dict:
    plan = format_plan(disk_number, filesystem=filesystem, label=label)
    if not settings.allow_disk_writes:
        raise DiskWriteBlocked("DS_ALLOW_DISK_WRITES is disabled")
    if plan["disk"]["protected"]:
        raise DiskWriteBlocked("Protected system/boot/application disk")
    if confirmation != plan["confirmation"]:
        raise DiskWriteBlocked("Typed confirmation does not match")
    fs = filesystem.upper()
    if fs not in {"NTFS", "EXFAT"}:
        raise ValueError("Only NTFS and exFAT are supported by this operation")
    if not label or len(label) > 32:
        raise ValueError("Invalid volume label")

    # No user-controlled PowerShell source is constructed. Values are passed as parameters.
    script = r'''
param([int]$DiskNumber, [string]$FileSystem, [string]$Label)
$ErrorActionPreference = "Stop"
$disk = Get-Disk -Number $DiskNumber
if ($disk.IsSystem -or $disk.IsBoot) { throw "Protected disk" }
Set-Disk -Number $DiskNumber -IsOffline $false
Set-Disk -Number $DiskNumber -IsReadOnly $false
Clear-Disk -Number $DiskNumber -RemoveData -RemoveOEM -Confirm:$false
Initialize-Disk -Number $DiskNumber -PartitionStyle GPT
$partition = New-Partition -DiskNumber $DiskNumber -UseMaximumSize -AssignDriveLetter
Format-Volume -Partition $partition -FileSystem $FileSystem -NewFileSystemLabel $Label -Confirm:$false
$partition | Get-Volume | Select-Object DriveLetter,FileSystemLabel,FileSystem,Size,SizeRemaining | ConvertTo-Json -Compress
'''
    result = subprocess.run(
        [
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-Command", script, "-DiskNumber", str(disk_number),
            "-FileSystem", fs, "-Label", label,
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Disk format failed")
    return {"status": "completed", "output": result.stdout.strip()}
