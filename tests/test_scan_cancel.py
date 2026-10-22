import pytest

import backend.core.database as database
from backend.scanner.quick_scan import ScanCancelled, scan


def test_quick_scan_can_be_cancelled(tmp_path, monkeypatch):
    db_path = tmp_path / "cancel.db"
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)

    root = tmp_path / "tree"
    root.mkdir()
    (root / "file.txt").write_text("data", encoding="utf-8")

    with pytest.raises(ScanCancelled):
        scan(root, cancel_callback=lambda: True)

    with database.connect() as connection:
        row = connection.execute(
            "SELECT status FROM scan_sessions ORDER BY id DESC LIMIT 1"
        ).fetchone()

    assert row["status"] == "cancelled"
