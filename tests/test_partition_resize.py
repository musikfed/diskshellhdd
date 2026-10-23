from __future__ import annotations

import pytest

import backend.services.storage.partition_resize as resize


def _disk(*, protected: bool = False):
    return {
        "number": 2,
        "friendly_name": "Test Disk",
        "size": 1000,
        "unique_id": "disk-2",
        "serial_number": "serial-2",
        "protected": protected,
        "is_boot": protected,
        "is_system": protected,
        "partitions": [
            {
                "partition_number": 1,
                "offset": 100,
                "size": 400,
                "filesystem": "NTFS",
                "supported_size_min": 200,
                "supported_size_max": 550,
            },
            {
                "partition_number": 2,
                "offset": 700,
                "size": 200,
                "filesystem": "NTFS",
                "supported_size_min": 150,
                "supported_size_max": 250,
            },
        ],
    }


def test_end_boundary_plan_uses_real_gap_and_windows_bounds(monkeypatch):
    monkeypatch.setattr(resize, "list_windows_disks", lambda: [_disk()])

    plan = resize.boundary_plan(
        2,
        1,
        boundary="end",
        target_size_bytes=550,
    )

    assert plan["direction"] == "grow_end"
    assert plan["free_before"] == 100
    assert plan["free_after"] == 200
    assert plan["target_end"] == 650
    assert plan["execution_supported"] is True
    assert plan["strategy"] == "windows_resize_partition"


def test_end_boundary_rejects_growth_beyond_windows_or_gap(monkeypatch):
    monkeypatch.setattr(resize, "list_windows_disks", lambda: [_disk()])

    with pytest.raises(ValueError, match="supported maximum"):
        resize.boundary_plan(
            2,
            1,
            boundary="end",
            target_size_bytes=600,
        )


def test_start_boundary_is_always_relocation_plan(monkeypatch):
    monkeypatch.setattr(resize, "list_windows_disks", lambda: [_disk()])

    plan = resize.boundary_plan(
        2,
        1,
        boundary="start",
        target_start_offset=50,
    )

    assert plan["direction"] == "toward_disk_start"
    assert plan["strategy"] == "relocate_or_recreate"
    assert plan["execution_supported"] is False
    assert any("does not move" in warning for warning in plan["warnings"])


def test_protected_system_disk_is_plan_only(monkeypatch):
    monkeypatch.setattr(resize, "list_windows_disks", lambda: [_disk(protected=True)])

    plan = resize.boundary_plan(
        2,
        1,
        boundary="end",
        target_size_bytes=500,
    )

    assert plan["protected_disk"] is True
    assert plan["execution_supported"] is False
    assert plan["confirmation"] is None
