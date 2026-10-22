import pytest

import backend.services.storage.partition_magic as partition_magic


def _disk():
    return {
        "number": 2,
        "friendly_name": "WDC Test",
        "serial_number": "SERIAL",
        "unique_id": "UNIQUE",
        "size": 4_000_000_000_000,
        "protected": False,
        "protection_reasons": [],
    }


def test_destructive_plan_can_leave_unallocated_space(monkeypatch):
    monkeypatch.setattr(partition_magic, "list_windows_disks", lambda: [_disk()])

    plan = partition_magic.format_plan(
        2,
        filesystem="NTFS",
        label="Storage",
        allocation_unit=16384,
        size_bytes=1 * 1024**4,
        drive_letter="S",
    )

    assert plan["use_maximum"] is False
    assert plan["size_bytes"] == 1 * 1024**4
    assert plan["drive_letter"] == "S"
    assert plan["layout"] == "first_partition_custom_size"


def test_destructive_plan_rejects_too_small_ntfs_cluster_for_full_4tb(monkeypatch):
    monkeypatch.setattr(partition_magic, "list_windows_disks", lambda: [_disk()])

    with pytest.raises(ValueError, match="larger allocation unit"):
        partition_magic.format_plan(
            2,
            filesystem="NTFS",
            label="Storage",
            allocation_unit=512,
        )
