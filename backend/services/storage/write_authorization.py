from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any

from backend.config import settings


class DiskWriteBlocked(RuntimeError):
    pass


_lock = threading.Lock()
_unlocked: dict[int, dict[str, Any]] = {}


def disk_identity(disk: dict[str, Any]) -> dict[str, Any]:
    return {
        "number": int(disk["number"]),
        "unique_id": disk.get("unique_id"),
        "serial_number": disk.get("serial_number"),
        "size": int(disk.get("size") or 0),
        "friendly_name": disk.get("friendly_name"),
    }


def _identity_key(disk: dict[str, Any]) -> tuple[Any, ...]:
    identity = disk_identity(disk)
    return (
        identity["number"],
        identity["unique_id"],
        identity["serial_number"],
        identity["size"],
    )


def unlock_selected_disk(disk: dict[str, Any]) -> dict[str, Any]:
    if disk.get("protected"):
        reasons = ", ".join(disk.get("protection_reasons") or [])
        raise DiskWriteBlocked(f"Protected disk cannot be write-enabled: {reasons}")

    with _lock:
        _unlocked[int(disk["number"])] = {
            "identity": _identity_key(disk),
        }
    return write_state_for_disk(disk)


def lock_selected_disk(disk_number: int) -> None:
    with _lock:
        _unlocked.pop(int(disk_number), None)


def _runtime_unlocked(disk: dict[str, Any]) -> bool:
    number = int(disk["number"])
    with _lock:
        record = _unlocked.get(number)
        if record is None:
            return False
        if tuple(record["identity"]) != _identity_key(disk):
            _unlocked.pop(number, None)
            return False
        return True


def write_state_for_disk(disk: dict[str, Any]) -> dict[str, Any]:
    runtime = _runtime_unlocked(disk)
    protected = bool(disk.get("protected"))
    global_override = bool(settings.allow_disk_writes and not protected)
    allowed = bool(not protected and (runtime or global_override))
    return {
        "allowed": allowed,
        "runtime_unlocked": runtime,
        "global_override": global_override,
        "expires_at_epoch": None,
        "confirmation": None,
        "unlock_mode": "manual_until_restart",
        "policy": "protected" if protected else ("unlocked" if allowed else "locked"),
    }


def annotate_disks(disks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for source in disks:
        disk = deepcopy(source)
        state = write_state_for_disk(disk)
        disk["write_access"] = state
        disk["write_policy"] = state["policy"]
        result.append(disk)
    return result


def require_disk_write_authorized(disk: dict[str, Any]) -> None:
    state = write_state_for_disk(disk)
    if not state["allowed"]:
        if disk.get("protected"):
            raise DiskWriteBlocked("Protected system/boot/application disk")
        raise DiskWriteBlocked(
            "Selected disk is write-locked. Enable write access for this exact disk first."
        )
