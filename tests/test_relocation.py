from __future__ import annotations

import backend.core.database as database
from backend.core.database import connect, init_database
from backend.storage_brain.relocation import relocation_plan


def test_relocation_plan_is_read_only_and_classifies_known_trees(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DATABASE_PATH", tmp_path / "relocation.db")
    init_database()

    with connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO scan_sessions(
                root_path,status,files_count,directories_count,bytes_total,completed_at
            ) VALUES(?, 'completed', 10, 4, 100000, CURRENT_TIMESTAMP)
            """,
            ("C:\\",),
        )
        scan_id = int(cursor.lastrowid)
        rows = [
            (scan_id, r"C:\Windows", None, "Windows", 40000, 4),
            (scan_id, r"C:\Users\me\Downloads", None, "Downloads", 30000, 3),
            (scan_id, r"C:\Users\me\.cache", None, ".cache", 20000, 2),
            (scan_id, r"C:\Archive", None, "Archive", 10000, 1),
        ]
        connection.executemany(
            """
            INSERT INTO directories(
                scan_id,path,parent_path,name,total_size,total_files,scan_complete
            ) VALUES(?,?,?,?,?,?,1)
            """,
            rows,
        )
        connection.commit()

    plan = relocation_plan(scan_id)
    by_path = {item["path"]: item for item in plan["items"]}

    assert plan["mode"] == "read_only_advisor"
    assert by_path[r"C:\Windows"]["action"] == "leave"
    assert by_path[r"C:\Users\me\Downloads"]["action"] == "native_relocate"
    assert by_path[r"C:\Users\me\.cache"]["action"] == "junction_candidate"
    assert by_path[r"C:\Archive"]["action"] == "archive_candidate"
    assert plan["rules"]["execution_model"] == "copy -> verify -> switch -> delete old"
