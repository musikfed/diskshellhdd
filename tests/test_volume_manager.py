import pytest

import backend.services.storage.volume_manager as volume_manager


def _disk(style="GPT", free=500 * 1024**3):
    return {
        "number": 2,
        "partition_style": style,
        "largest_free_extent": free,
        "protected": False,
        "size": 4_000_000_000_000,
        "unique_id": "disk-test",
    }


def test_create_partition_plan_uses_free_extent(monkeypatch):
    monkeypatch.setattr(volume_manager, "_get_disk", lambda _number: _disk())

    plan = volume_manager.create_partition_plan(
        2,
        size_bytes=100 * 1024**3,
        filesystem="NTFS",
        label="Data",
        allocation_unit=16384,
        drive_letter="S",
    )

    assert plan["size_bytes"] == 100 * 1024**3
    assert plan["allocation_unit"] == 16384
    assert plan["drive_letter"] == "S"
    assert plan["confirmation"] == "CREATE PARTITION DISK 2"


def test_create_partition_requires_initialized_disk(monkeypatch):
    monkeypatch.setattr(volume_manager, "_get_disk", lambda _number: _disk(style="RAW"))

    with pytest.raises(ValueError, match="Initialize"):
        volume_manager.create_partition_plan(2)
