from __future__ import annotations

import backend.streamcopy.locality as locality


def test_locality_order_sorts_known_lcn_and_keeps_unknown_stable(monkeypatch):
    lcn = {
        "a.bin": 900,
        "b.bin": None,
        "c.bin": 100,
        "d.bin": None,
        "e.bin": 500,
    }
    monkeypatch.setattr(
        locality,
        "first_ntfs_lcn",
        lambda path: lcn[str(path)],
    )
    items = [
        {"item_index": index, "source_path": name}
        for index, name in enumerate(["a.bin", "b.bin", "c.bin", "d.bin", "e.bin"])
    ]

    ordered, metrics = locality.order_manifest_by_ntfs_locality(items)

    assert [item["source_path"] for item in ordered] == [
        "c.bin",
        "e.bin",
        "a.bin",
        "b.bin",
        "d.bin",
    ]
    assert [item["item_index"] for item in ordered] == [0, 1, 2, 3, 4]
    assert [item["manifest_original_index"] for item in ordered] == [2, 4, 0, 1, 3]
    assert metrics["known_lcn"] == 3
    assert metrics["unknown_lcn"] == 2
    assert metrics["coverage_percent"] == 60.0


def test_locality_order_with_no_known_lcn_is_original_order(monkeypatch):
    monkeypatch.setattr(locality, "first_ntfs_lcn", lambda _path: None)
    items = [
        {"item_index": index, "source_path": name}
        for index, name in enumerate(["one", "two", "three"])
    ]

    ordered, metrics = locality.order_manifest_by_ntfs_locality(items)

    assert [item["source_path"] for item in ordered] == ["one", "two", "three"]
    assert metrics["known_lcn"] == 0
    assert metrics["coverage_percent"] == 0.0
