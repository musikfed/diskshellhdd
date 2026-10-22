from __future__ import annotations

import backend.core.database as database
from backend.storage_brain.service import get_plan_page, update_plan_selection


def _prepare_plan(tmp_path, monkeypatch):
    db_path = tmp_path / "placement.db"
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    database.init_database()

    with database.connect() as connection:
        scan_id = connection.execute(
            """
            INSERT INTO scan_sessions(root_path, status, completed_at)
            VALUES (?, 'completed', CURRENT_TIMESTAMP)
            """,
            (str(tmp_path),),
        ).lastrowid
        plan_id = connection.execute(
            """
            INSERT INTO placement_plans(
                scan_id, storage_root, total_items, total_bytes,
                projected_used_bytes, projected_free_bytes, reserve_bytes
            ) VALUES (?, ?, 3, 600, 600, 100000, 1000)
            """,
            (scan_id, str(tmp_path / "Storage")),
        ).lastrowid
        connection.executemany(
            """
            INSERT INTO placement_plan_items(
                plan_id, source_path, target_path, target_class, size,
                reason, action, layout_lane, target_band_bytes, selected
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    plan_id,
                    str(tmp_path / "a.iso"),
                    str(tmp_path / "Storage" / "Images" / "a.iso"),
                    "images",
                    100,
                    "Disk images",
                    "copy_cross_volume",
                    "D-cold",
                    1024,
                    1,
                ),
                (
                    plan_id,
                    str(tmp_path / "b.zip"),
                    str(tmp_path / "Storage" / "Archive" / "b.zip"),
                    "archive",
                    200,
                    "Archives",
                    "copy_cross_volume",
                    "D-cold",
                    1024,
                    1,
                ),
                (
                    plan_id,
                    str(tmp_path / "c.mp4"),
                    str(tmp_path / "Storage" / "Media" / "c.mp4"),
                    "media",
                    300,
                    "Video",
                    "copy_cross_volume",
                    "A-media-sequential",
                    512,
                    1,
                ),
            ],
        )
        connection.commit()
    return int(plan_id)


def test_plan_page_is_paginated_and_reports_selected_totals(tmp_path, monkeypatch):
    plan_id = _prepare_plan(tmp_path, monkeypatch)

    first = get_plan_page(plan_id, limit=2, offset=0)

    assert len(first["items"]) == 2
    assert first["page"]["total"] == 3
    assert first["page"]["returned"] == 2
    assert first["selected_items"] == 3
    assert first["selected_bytes"] == 600


def test_plan_selection_can_disable_filtered_items(tmp_path, monkeypatch):
    plan_id = _prepare_plan(tmp_path, monkeypatch)

    updated = update_plan_selection(
        plan_id,
        selected=False,
        all_items=True,
        query=".zip",
    )

    assert updated["selected_items"] == 2

    filtered = get_plan_page(plan_id, query=".zip")
    assert filtered["page"]["filtered"] == 1
    assert filtered["items"][0]["selected"] == 0
