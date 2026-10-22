from __future__ import annotations

import sqlite3

import backend.core.database as database


def test_database_schema_exists():
    database.init_database()

    with database.connect() as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    required = {
        "scan_sessions",
        "files",
        "directories",
        "storage_classes",
        "placement_plans",
        "placement_plan_items",
        "operation_journal",
        "file_hashes",
        "photos",
        "faces",
        "persons",
        "recovery_snapshots",
        "security_scan_results",
        "diagnostic_runs",
    }
    assert required <= tables


def test_legacy_database_is_migrated_before_indexes(tmp_path, monkeypatch):
    legacy_path = tmp_path / "legacy.db"

    with sqlite3.connect(legacy_path) as connection:
        connection.executescript(
            """
            CREATE TABLE scan_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_path TEXT NOT NULL,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                files_count INTEGER NOT NULL DEFAULT 0,
                directories_count INTEGER NOT NULL DEFAULT 0,
                bytes_total INTEGER NOT NULL DEFAULT 0,
                errors_count INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE directories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                parent_path TEXT,
                name TEXT NOT NULL,
                direct_size INTEGER NOT NULL DEFAULT 0,
                total_size INTEGER NOT NULL DEFAULT 0,
                direct_files INTEGER NOT NULL DEFAULT 0,
                total_files INTEGER NOT NULL DEFAULT 0,
                child_directories INTEGER NOT NULL DEFAULT 0,
                scan_complete INTEGER NOT NULL DEFAULT 0,
                UNIQUE(scan_id, path)
            );

            CREATE TABLE files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                parent_path TEXT NOT NULL,
                name TEXT NOT NULL,
                extension TEXT,
                size INTEGER NOT NULL,
                modified_ns INTEGER,
                UNIQUE(scan_id, path)
            );
            """
        )

    monkeypatch.setattr(database, "DATABASE_PATH", legacy_path)

    database.init_database()

    with sqlite3.connect(legacy_path) as connection:
        file_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(files)").fetchall()
        }
        directory_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(directories)").fetchall()
        }
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(files)").fetchall()
        }

    assert {"category", "storage_class", "accessed_ns", "created_ns"} <= file_columns
    assert {"category", "storage_class"} <= directory_columns
    assert "idx_files_scan_category" in indexes
