from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.database import connect, init_database
from backend.services.storage.windows_disks import list_windows_disks


def _detect_boot_sector(data: bytes) -> str | None:
    if len(data) < 90:
        return None
    oem = data[3:11]
    if oem == b"NTFS    ":
        return "NTFS"
    if oem == b"EXFAT   ":
        return "exFAT"
    if oem == b"-FVE-FS-":
        return "BitLocker/FVE"
    if data[82:90] == b"FAT32   ":
        return "FAT32"
    if data[54:62] in {b"FAT16   ", b"FAT12   "}:
        return data[54:62].decode("ascii").strip()
    return None


def probe_disk_signatures(disk_number: int) -> dict[str, Any]:
    disks = {int(d["number"]): d for d in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")

    device = Path(str(disk["device_id"]))
    result: dict[str, Any] = {
        "disk_number": int(disk_number),
        "device_id": str(device),
        "friendly_name": disk.get("friendly_name"),
        "serial_number": disk.get("serial_number"),
        "unique_id": disk.get("unique_id"),
        "size": disk.get("size"),
        "readable": False,
        "mbr_signature": False,
        "gpt_header": False,
        "partitions": [],
        "error": None,
    }

    try:
        with open(str(device), "rb", buffering=0) as handle:
            first = handle.read(4096)
            result["readable"] = True
            result["mbr_signature"] = len(first) >= 512 and first[510:512] == b"\x55\xaa"
            result["gpt_header"] = len(first) >= 1024 and first[512:520] == b"EFI PART"

            for partition in disk.get("partitions") or []:
                offset = int(partition.get("offset") or 0)
                try:
                    handle.seek(offset)
                    boot = handle.read(4096)
                    detected = _detect_boot_sector(boot)
                    result["partitions"].append(
                        {
                            "partition_number": partition.get("partition_number"),
                            "offset": offset,
                            "size": partition.get("size"),
                            "drive_letter": partition.get("drive_letter"),
                            "reported_filesystem": partition.get("filesystem"),
                            "signature_filesystem": detected,
                            "boot_signature": boot[510:512].hex() if len(boot) >= 512 else None,
                        }
                    )
                except OSError as exc:
                    result["partitions"].append(
                        {
                            "partition_number": partition.get("partition_number"),
                            "offset": offset,
                            "size": partition.get("size"),
                            "error": str(exc),
                        }
                    )
    except (PermissionError, OSError) as exc:
        result["error"] = str(exc)

    return result


def create_recovery_snapshot() -> dict[str, Any]:
    init_database()
    disks = list_windows_disks()
    payload = {
        "created_at": datetime.now(UTC).isoformat(),
        "disks": disks,
    }
    with connect() as connection:
        cursor = connection.execute(
            "INSERT INTO recovery_snapshots (payload) VALUES (?)",
            (json.dumps(payload, ensure_ascii=False),),
        )
        snapshot_id = int(cursor.lastrowid)
        connection.commit()
    payload["id"] = snapshot_id
    return payload


def latest_recovery_snapshot() -> dict[str, Any]:
    init_database()
    with connect() as connection:
        row = connection.execute(
            "SELECT id, created_at, payload FROM recovery_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        raise KeyError("latest")
    payload = json.loads(row["payload"])
    payload["id"] = int(row["id"])
    payload["database_created_at"] = row["created_at"]
    return payload


def list_recovery_snapshots(limit: int = 20) -> list[dict[str, Any]]:
    init_database()
    limit = max(1, min(int(limit), 100))
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, payload
            FROM recovery_snapshots
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = json.loads(row["payload"])
        result.append(
            {
                "id": int(row["id"]),
                "created_at": row["created_at"],
                "disk_count": len(payload.get("disks") or []),
            }
        )
    return result
