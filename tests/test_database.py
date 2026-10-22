from backend.core.database import connect, init_database


def test_database_schema_exists():
    init_database()
    with connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"scan_sessions", "files", "directories", "storage_classes", "placement_plans"} <= tables
