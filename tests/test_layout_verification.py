from __future__ import annotations

from pathlib import Path

import backend.storage_brain.executor as executor


def test_layout_verification_reports_conforming(monkeypatch):
    monkeypatch.setattr(
        executor,
        "query_file_extents",
        lambda _path: {"supported": True, "extent_count": 4},
    )
    result = executor._verify_layout(
        {
            "size": 4 * 512 * 1024 * 1024,
            "target_band_bytes": 512 * 1024 * 1024,
            "layout_lane": "A-media-sequential",
        },
        Path("dummy.bin"),
    )

    assert result["status"] == "conforming"
    assert result["actual_extents"] == 4
    assert result["expected_extents"] == 4


def test_layout_verification_reports_drift(monkeypatch):
    monkeypatch.setattr(
        executor,
        "query_file_extents",
        lambda _path: {"supported": True, "extent_count": 1},
    )
    result = executor._verify_layout(
        {
            "size": 8 * 512 * 1024 * 1024,
            "target_band_bytes": 512 * 1024 * 1024,
            "layout_lane": "A-media-sequential",
        },
        Path("dummy.bin"),
    )

    assert result["status"] == "drift"
    assert result["actual_extents"] == 1
    assert result["expected_extents"] == 8


def test_layout_verification_is_explicit_when_unavailable(monkeypatch):
    monkeypatch.setattr(
        executor,
        "query_file_extents",
        lambda _path: {"supported": False, "reason": "not NTFS"},
    )
    result = executor._verify_layout(
        {
            "size": 1024,
            "target_band_bytes": 512,
            "layout_lane": "C-interactive",
        },
        Path("dummy.bin"),
    )

    assert result["status"] == "unavailable"
    assert result["reason"] == "not NTFS"
