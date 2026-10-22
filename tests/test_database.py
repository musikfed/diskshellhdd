from backend.core.database import connect, init_database


def test_database_schema_exists():
    init_database()
    with connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    required = {
        "scan_sessions", "files", "directories", "storage_classes", "placement_plans",
        "placement_plan_items", "operation_journal", "file_hashes", "photos", "faces", "persons",
    }
    assert required <= tables
