from __future__ import annotations

import backend.core.database as database
from backend.files.service import list_directory


def test_commander_uses_indexed_directory_total_size(tmp_path, monkeypatch):
    db_path = tmp_path / "files.db"
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    database.init_database()

    root = tmp_path / "volume"
    child = root / "dataset"
    child.mkdir(parents=True)

    with database.connect() as connection:
        scan_id = connection.execute(
            """
            INSERT INTO scan_sessions(root_path, status, completed_at)
            VALUES (?, 'completed', CURRENT_TIMESTAMP)
            """,
            (str(root),),
        ).lastrowid
        connection.execute(
            """
            INSERT INTO directories(
                scan_id, path, parent_path, name, total_size,
                total_files, child_directories, scan_complete
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                scan_id,
                str(child),
                str(root),
                child.name,
                12_345_678,
                42,
                3,
            ),
        )
        connection.commit()

    result = list_directory(root, scan_id=int(scan_id))
    item = next(row for row in result["items"] if row["name"] == "dataset")

    assert item["is_dir"] is True
    assert item["size_known"] is True
    assert item["size"] == 12_345_678
    assert item["total_files"] == 42
    assert item["indexed_scan_id"] == scan_id
