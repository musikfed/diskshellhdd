from __future__ import annotations

from pathlib import Path

import backend.core.database as database
from backend.core.database import connect, init_database
from backend.search.catalog import (
    begin_refresh,
    catalog_status,
    finish_refresh,
    search_files,
    upsert_rows,
)


def _row(scan_id: int, path: Path, size: int, category: str = "document"):
    return (
        scan_id,
        str(path),
        str(path.parent),
        path.name,
        path.suffix.casefold() or None,
        category,
        size,
        10,
        11,
        12,
    )


def test_current_catalog_search_and_stale_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "catalog.db")
    init_database()
    root = tmp_path / "root"
    root.mkdir()

    first = root / "invoice-2026.pdf"
    stale = root / "old-report.txt"

    with connect() as connection:
        begin_refresh(connection, root, 1)
        upsert_rows(
            connection,
            [
                _row(1, first, 4096),
                _row(1, stale, 1024),
            ],
        )
        finish_refresh(connection, root, 1, 2)
        connection.commit()

    result = search_files("invoice", root=str(root))
    assert [item["name"] for item in result["files"]] == ["invoice-2026.pdf"]

    with connect() as connection:
        begin_refresh(connection, root, 2)
        upsert_rows(connection, [_row(2, first, 8192)])
        finish_refresh(connection, root, 2, 1)
        connection.commit()

    all_files = search_files(root=str(root), limit=20)
    assert [item["name"] for item in all_files["files"]] == ["invoice-2026.pdf"]
    assert all_files["files"][0]["size"] == 8192

    status = catalog_status()
    assert status["files"] == 1
    assert status["roots"][0]["status"] == "ready"
    assert status["roots"][0]["last_scan_id"] == 2


def test_catalog_filters_extension_and_category(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "catalog.db")
    init_database()
    root = tmp_path / "root"
    root.mkdir()

    with connect() as connection:
        begin_refresh(connection, root, 3)
        upsert_rows(
            connection,
            [
                _row(3, root / "photo.jpg", 500, "photo"),
                _row(3, root / "notes.txt", 200, "document"),
            ],
        )
        finish_refresh(connection, root, 3, 2)
        connection.commit()

    photo = search_files(root=str(root), category="photo")
    assert [item["name"] for item in photo["files"]] == ["photo.jpg"]

    txt = search_files(root=str(root), extension="txt")
    assert [item["name"] for item in txt["files"]] == ["notes.txt"]
