from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.services.storage.filesystem_profiles import capabilities
from backend.services.storage.partition_magic import execute_format, format_plan
from backend.services.storage.volume_manager import (
    assign_drive_letter,
    create_partition,
    create_partition_plan,
    initialize_disk,
    initialize_plan,
)
from backend.services.storage.windows_disks import (
    APPLICATION_DRIVE,
    DiskDetectionError,
    list_windows_disks,
)
from backend.services.storage.windows_privileges import (
    WindowsElevationRequired,
    is_process_elevated,
)
from backend.services.storage.write_authorization import (
    DiskWriteBlocked,
    annotate_disks,
    lock_selected_disk,
    unlock_selected_disk,
    write_state_for_disk,
)


bp = Blueprint("disks", __name__, url_prefix="/api/disks")


def _disk_by_number(disk_number: int) -> dict:
    disks = {int(d["number"]): d for d in list_windows_disks()}
    disk = disks.get(int(disk_number))
    if disk is None:
        raise ValueError("Disk not found")
    return disk


@bp.get("/capabilities")
def get_capabilities():
    payload = capabilities()
    payload["process_elevated"] = is_process_elevated()
    payload["destructive_requires_elevation"] = True
    return jsonify(payload)


@bp.get("")
def get_disks():
    try:
        disks = annotate_disks(list_windows_disks())
    except DiskDetectionError as exc:
        return jsonify({"error": "disk_detection_failed", "message": str(exc)}), 500
    return jsonify(
        {
            "mode": "admin_safe",
            "application_drive": APPLICATION_DRIVE,
            "disk_count": len(disks),
            "disks": disks,
        }
    )


@bp.post("/<int:disk_number>/unlock-plan")
def get_unlock_plan(disk_number: int):
    try:
        disk = _disk_by_number(disk_number)
        state = write_state_for_disk(disk)
        if disk.get("protected"):
            raise DiskWriteBlocked("Protected system/boot/application disk cannot be unlocked")
        return jsonify(
            {
                "disk": disk,
                "write_access": state,
                "confirmation": state["confirmation"],
                "expires_in_seconds": 900,
                "warning": (
                    "Unlocking authorizes destructive storage operations for this exact physical "
                    "disk identity for a limited time. It does not bypass protected-disk checks."
                ),
            }
        )
    except DiskWriteBlocked as exc:
        return jsonify({"error": "disk_unlock_blocked", "message": str(exc)}), 403
    except (ValueError, DiskDetectionError) as exc:
        return jsonify({"error": "disk_unlock_plan_failed", "message": str(exc)}), 400


@bp.post("/<int:disk_number>/unlock")
def unlock_disk(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        disk = _disk_by_number(disk_number)
        state = unlock_selected_disk(disk, str(payload.get("confirmation", "")))
        return jsonify({"disk_number": disk_number, "write_access": state})
    except DiskWriteBlocked as exc:
        return jsonify({"error": "disk_unlock_blocked", "message": str(exc)}), 403
    except (ValueError, DiskDetectionError) as exc:
        return jsonify({"error": "disk_unlock_failed", "message": str(exc)}), 400


@bp.post("/<int:disk_number>/lock")
def lock_disk(disk_number: int):
    lock_selected_disk(disk_number)
    return jsonify({"disk_number": disk_number, "status": "locked"})


@bp.post("/<int:disk_number>/format-plan")
def get_format_plan(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        raw_size = payload.get("size_bytes")
        size_bytes = None if raw_size in {None, "", 0} else int(raw_size)
        plan = format_plan(
            disk_number,
            filesystem=str(payload.get("filesystem", "NTFS")),
            label=str(payload.get("label", "Storage")),
            allocation_unit=int(payload.get("allocation_unit", 4096)),
            size_bytes=size_bytes,
            drive_letter=payload.get("drive_letter"),
        )
    except (ValueError, DiskDetectionError, DiskWriteBlocked) as exc:
        return jsonify({"error": "format_plan_failed", "message": str(exc)}), 400
    return jsonify(plan)


@bp.post("/<int:disk_number>/format")
def format_disk(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        raw_size = payload.get("size_bytes")
        size_bytes = None if raw_size in {None, "", 0} else int(raw_size)
        result = execute_format(
            disk_number,
            confirmation=str(payload.get("confirmation", "")),
            filesystem=str(payload.get("filesystem", "NTFS")),
            label=str(payload.get("label", "Storage")),
            allocation_unit=int(payload.get("allocation_unit", 4096)),
            size_bytes=size_bytes,
            drive_letter=payload.get("drive_letter"),
        )
    except (DiskWriteBlocked, WindowsElevationRequired) as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, RuntimeError, DiskDetectionError) as exc:
        return jsonify({"error": "format_failed", "message": str(exc)}), 400
    return jsonify(result)


@bp.post("/<int:disk_number>/initialize-plan")
def get_initialize_plan(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(initialize_plan(disk_number, str(payload.get("partition_style", "GPT"))))
    except (DiskWriteBlocked, WindowsElevationRequired) as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, DiskDetectionError) as exc:
        return jsonify({"error": "initialize_plan_failed", "message": str(exc)}), 400


@bp.post("/<int:disk_number>/initialize")
def initialize_selected_disk(disk_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            initialize_disk(
                disk_number,
                str(payload.get("partition_style", "GPT")),
                str(payload.get("confirmation", "")),
            )
        )
    except (DiskWriteBlocked, WindowsElevationRequired) as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, RuntimeError, DiskDetectionError) as exc:
        return jsonify({"error": "initialize_failed", "message": str(exc)}), 400


@bp.post("/<int:disk_number>/partitions/create-plan")
def get_create_partition_plan(disk_number: int):
    payload = request.get_json(silent=True) or {}
    raw_size = payload.get("size_bytes")
    size_bytes = None if raw_size in {None, "", 0} else int(raw_size)
    try:
        return jsonify(
            create_partition_plan(
                disk_number,
                size_bytes=size_bytes,
                filesystem=str(payload.get("filesystem", "NTFS")),
                label=str(payload.get("label", "Data")),
                allocation_unit=int(payload.get("allocation_unit", 4096)),
                drive_letter=payload.get("drive_letter"),
            )
        )
    except (DiskWriteBlocked, WindowsElevationRequired) as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, DiskDetectionError) as exc:
        return jsonify({"error": "partition_plan_failed", "message": str(exc)}), 400


@bp.post("/<int:disk_number>/partitions")
def create_selected_partition(disk_number: int):
    payload = request.get_json(silent=True) or {}
    raw_size = payload.get("size_bytes")
    size_bytes = None if raw_size in {None, "", 0} else int(raw_size)
    try:
        return jsonify(
            create_partition(
                disk_number,
                confirmation=str(payload.get("confirmation", "")),
                size_bytes=size_bytes,
                filesystem=str(payload.get("filesystem", "NTFS")),
                label=str(payload.get("label", "Data")),
                allocation_unit=int(payload.get("allocation_unit", 4096)),
                drive_letter=payload.get("drive_letter"),
            )
        )
    except (DiskWriteBlocked, WindowsElevationRequired) as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, RuntimeError, DiskDetectionError) as exc:
        return jsonify({"error": "partition_create_failed", "message": str(exc)}), 400


@bp.post("/<int:disk_number>/partitions/<int:partition_number>/drive-letter")
def set_partition_drive_letter(disk_number: int, partition_number: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            assign_drive_letter(
                disk_number,
                partition_number,
                str(payload.get("drive_letter", "")),
                str(payload.get("confirmation", "")),
            )
        )
    except (DiskWriteBlocked, WindowsElevationRequired) as exc:
        return jsonify({"error": "disk_write_blocked", "message": str(exc)}), 403
    except (ValueError, RuntimeError, DiskDetectionError) as exc:
        return jsonify({"error": "drive_letter_failed", "message": str(exc)}), 400
