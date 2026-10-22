from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class DiskDetectionError(RuntimeError):
    """Unable to read Windows disk inventory."""


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_DRIVE = PROJECT_ROOT.drive.upper()


POWERSHELL_SCRIPT = r'''
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [System.Text.UTF8Encoding]::new()

$items = @(
  Get-Disk | ForEach-Object {
    $disk = $_
    $partitions = @(
      Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | ForEach-Object {
        $partition = $_
        $volume = $null
        try { $volume = $partition | Get-Volume -ErrorAction Stop } catch { $volume = $null }
        [PSCustomObject]@{
          PartitionNumber = [int]$partition.PartitionNumber
          DriveLetter = if ($partition.DriveLetter) { [string]$partition.DriveLetter } else { $null }
          Size = [int64]$partition.Size
          Offset = [int64]$partition.Offset
          Type = [string]$partition.Type
          GptType = if ($partition.GptType) { [string]$partition.GptType } else { $null }
          MbrType = if ($partition.MbrType) { [string]$partition.MbrType } else { $null }
          IsActive = [bool]$partition.IsActive
          FileSystem = if ($volume) { [string]$volume.FileSystem } else { $null }
          FileSystemLabel = if ($volume) { [string]$volume.FileSystemLabel } else { $null }
          VolumeHealthStatus = if ($volume) { [string]$volume.HealthStatus } else { $null }
          VolumeSize = if ($volume) { [int64]$volume.Size } else { $null }
          SizeRemaining = if ($volume) { [int64]$volume.SizeRemaining } else { $null }
        }
      }
    )
    [PSCustomObject]@{
      Number = [int]$disk.Number
      FriendlyName = [string]$disk.FriendlyName
      SerialNumber = if ($disk.SerialNumber) { [string]$disk.SerialNumber } else { $null }
      UniqueId = if ($disk.UniqueId) { [string]$disk.UniqueId } else { $null }
      BusType = [string]$disk.BusType
      PartitionStyle = [string]$disk.PartitionStyle
      Size = [int64]$disk.Size
      AllocatedSize = [int64]$disk.AllocatedSize
      LargestFreeExtent = [int64]$disk.LargestFreeExtent
      LogicalSectorSize = [int]$disk.LogicalSectorSize
      PhysicalSectorSize = [int]$disk.PhysicalSectorSize
      OperationalStatus = [string]($disk.OperationalStatus -join ",")
      HealthStatus = [string]$disk.HealthStatus
      IsBoot = [bool]$disk.IsBoot
      IsSystem = [bool]$disk.IsSystem
      IsReadOnly = [bool]$disk.IsReadOnly
      IsOffline = [bool]$disk.IsOffline
      Partitions = $partitions
    }
  }
)
$items | ConvertTo-Json -Depth 8 -Compress
'''


def _partition_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    drive_letter = raw.get("DriveLetter")
    if drive_letter:
        drive_letter = f"{drive_letter}:"
    return {
        "partition_number": raw.get("PartitionNumber"),
        "drive_letter": drive_letter,
        "size": raw.get("Size"),
        "offset": raw.get("Offset"),
        "type": raw.get("Type"),
        "gpt_type": raw.get("GptType"),
        "mbr_type": raw.get("MbrType"),
        "is_active": raw.get("IsActive"),
        "filesystem": raw.get("FileSystem"),
        "label": raw.get("FileSystemLabel"),
        "health_status": raw.get("VolumeHealthStatus"),
        "volume_size": raw.get("VolumeSize"),
        "size_remaining": raw.get("SizeRemaining"),
    }


def _disk_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    raw_partitions = raw.get("Partitions") or []
    if isinstance(raw_partitions, dict):
        raw_partitions = [raw_partitions]
    partitions = [_partition_from_raw(item) for item in raw_partitions]
    reasons: list[str] = []
    if raw.get("IsSystem"):
        reasons.append("system_disk")
    if raw.get("IsBoot"):
        reasons.append("boot_disk")
    for partition in partitions:
        letter = partition.get("drive_letter")
        if letter and letter.upper() == APPLICATION_DRIVE:
            reasons.append("application_disk")
            break
    return {
        "number": raw.get("Number"),
        "device_id": rf"\\.\PHYSICALDRIVE{raw.get('Number')}",
        "friendly_name": raw.get("FriendlyName"),
        "serial_number": raw.get("SerialNumber"),
        "unique_id": raw.get("UniqueId"),
        "bus_type": raw.get("BusType"),
        "partition_style": raw.get("PartitionStyle"),
        "size": raw.get("Size"),
        "allocated_size": raw.get("AllocatedSize"),
        "largest_free_extent": raw.get("LargestFreeExtent"),
        "logical_sector_size": raw.get("LogicalSectorSize"),
        "physical_sector_size": raw.get("PhysicalSectorSize"),
        "operational_status": raw.get("OperationalStatus"),
        "health_status": raw.get("HealthStatus"),
        "is_boot": raw.get("IsBoot"),
        "is_system": raw.get("IsSystem"),
        "is_read_only": raw.get("IsReadOnly"),
        "is_offline": raw.get("IsOffline"),
        "protected": bool(reasons),
        "protection_reasons": reasons,
        "write_policy": "blocked" if reasons else "locked",
        "partitions": partitions,
    }


def list_windows_disks() -> list[dict[str, Any]]:
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
            "-ExecutionPolicy", "Bypass", "-Command", POWERSHELL_SCRIPT,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        errors="replace",
        timeout=30,
        creationflags=creation_flags,
        check=False,
    )
    if result.returncode != 0:
        raise DiskDetectionError(result.stderr.strip() or "Windows Storage API returned an error")
    output = result.stdout.strip()
    if not output:
        return []
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise DiskDetectionError(f"PowerShell returned invalid JSON: {exc}") from exc
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise DiskDetectionError("Windows returned an unexpected disk data format")
    return [_disk_from_raw(item) for item in parsed]
