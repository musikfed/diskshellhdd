from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.services.storage.partition_magic import DiskWriteBlocked, execute_format, format_plan
from backend.services.storage.windows_disks import APPLICATION_DRIVE, DiskDetectionError, list_windows_disks


bp = Blueprint("disks", __name__, url_prefix="/api/disks")


@bp.get("")
def get_disks():
    try:
        disks = list_windows_disks()
    except DiskDetectionError as exc:
        return jsonify({"error": "disk_detection_failed", "message": str(exc)}), 500
    return jsonify({"mode": "safe", "application_drive": APPLICATION_DRIVE, "disk_count": len(disks), "disks": disks})


@bp.post("/<int:disk_number>/format-plan")
def get_format_plan(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        plan = format_plan(
            disk_number,
            filesystem=str(payload.get("filesystem", "NTFS")),
            label=str(payload.get("label", "Storage")),
            allocation_unit=int(payload.get("allocation_unit", 4096)),
        )
    except (ValueError, DiskDetectionError) as exc:
        return jsonify({"error": "format_plan_failed", "message": str(exc)}), 400
    return jsonify(plan)


@bp.post("/<int:disk_number>/format")
def format_disk(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        result = execute_format(
            disk_number,
            confirmation=str(payload.get("confirmation", "")),
            filesystem=str(payload.get("filesystem", "NTFS")),
            label=str(payload.get("label", "Storage")),
            allocation_unit=int(payload.get("allocation_unit", 4096)),
        )
    except DiskWriteBlocked as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, RuntimeError, DiskDetectionError) as exc:
        return jsonify({"error": "format_failed", "message": str(exc)}), 400
    return jsonify(result)
