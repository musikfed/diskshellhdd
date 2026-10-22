import pytest

from backend.services.storage.write_authorization import (
    DiskWriteBlocked,
    lock_selected_disk,
    unlock_confirmation,
    unlock_selected_disk,
    write_state_for_disk,
)


def _disk(number=2, protected=False):
    return {
        "number": number,
        "unique_id": "WD-UNIQUE-12345678",
        "serial_number": "SERIAL12345678",
        "size": 4_000_000_000_000,
        "friendly_name": "Test storage disk",
        "protected": protected,
        "protection_reasons": ["system_disk"] if protected else [],
    }


def test_selected_disk_runtime_unlock_and_lock():
    disk = _disk()
    lock_selected_disk(disk["number"])

    assert write_state_for_disk(disk)["allowed"] is False

    confirmation = unlock_confirmation(disk)
    state = unlock_selected_disk(disk, confirmation)

    assert state["allowed"] is True
    assert state["runtime_unlocked"] is True
    assert state["policy"] == "unlocked"

    lock_selected_disk(disk["number"])
    assert write_state_for_disk(disk)["allowed"] is False


def test_protected_disk_cannot_be_runtime_unlocked():
    disk = _disk(number=1, protected=True)

    with pytest.raises(DiskWriteBlocked):
        unlock_selected_disk(disk, unlock_confirmation(disk))
