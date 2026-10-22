import pytest

from backend.services.storage.write_authorization import (
    DiskWriteBlocked,
    lock_selected_disk,
    unlock_selected_disk,
    write_state_for_disk,
)


def _disk(number=2, protected=False, serial="SERIAL12345678"):
    return {
        "number": number,
        "unique_id": "WD-UNIQUE-12345678",
        "serial_number": serial,
        "size": 4_000_000_000_000,
        "friendly_name": "Test storage disk",
        "protected": protected,
        "protection_reasons": ["system_disk"] if protected else [],
    }


def test_selected_disk_write_toggle_stays_enabled_until_manual_lock():
    disk = _disk()
    lock_selected_disk(disk["number"])

    assert write_state_for_disk(disk)["allowed"] is False

    state = unlock_selected_disk(disk)

    assert state["allowed"] is True
    assert state["runtime_unlocked"] is True
    assert state["expires_at_epoch"] is None
    assert state["confirmation"] is None
    assert state["unlock_mode"] == "manual_until_restart"
    assert write_state_for_disk(disk)["allowed"] is True

    lock_selected_disk(disk["number"])
    assert write_state_for_disk(disk)["allowed"] is False


def test_runtime_write_enablement_is_bound_to_exact_disk_identity():
    original = _disk(serial="SERIAL-OLD")
    replacement = _disk(serial="SERIAL-NEW")
    lock_selected_disk(original["number"])

    unlock_selected_disk(original)

    assert write_state_for_disk(original)["allowed"] is True
    assert write_state_for_disk(replacement)["allowed"] is False
    assert write_state_for_disk(original)["allowed"] is False


def test_protected_disk_cannot_be_write_enabled():
    disk = _disk(number=1, protected=True)

    with pytest.raises(DiskWriteBlocked):
        unlock_selected_disk(disk)
