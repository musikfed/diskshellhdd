from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from backend.config import settings


DATABASE_PATH = settings.data_dir / "diskshell.db"


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS scan_sessions (
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

CREATE TABLE IF NOT EXISTS directories (
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
    category TEXT NOT NULL DEFAULT 'directory',
    storage_class TEXT,
    scan_complete INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(id) ON DELETE CASCADE,
    UNIQUE(scan_id, path)
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    parent_path TEXT NOT NULL,
    name TEXT NOT NULL,
    extension TEXT,
    category TEXT NOT NULL DEFAULT 'other',
    storage_class TEXT,
    size INTEGER NOT NULL,
    modified_ns INTEGER,
    accessed_ns INTEGER,
    created_ns INTEGER,
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(id) ON DELETE CASCADE,
    UNIQUE(scan_id, path)
);

CREATE TABLE IF NOT EXISTS storage_classes (
    key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    relative_root TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS placement_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category TEXT,
    extension TEXT,
    min_size INTEGER,
    max_size INTEGER,
    min_age_days INTEGER,
    target_class TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    enabled INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (target_class) REFERENCES storage_classes(key)
);

CREATE TABLE IF NOT EXISTS placement_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    storage_root TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    total_items INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    projected_used_bytes INTEGER NOT NULL DEFAULT 0,
    projected_free_bytes INTEGER NOT NULL DEFAULT 0,
    reserve_bytes INTEGER NOT NULL DEFAULT 0,
    warnings TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS placement_plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_class TEXT NOT NULL,
    size INTEGER NOT NULL,
    reason TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'move',
    FOREIGN KEY (plan_id) REFERENCES placement_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS access_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    operation TEXT NOT NULL,
    latency_ms REAL,
    bytes_count INTEGER,
    sampled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_scan_parent ON files(scan_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_files_scan_size ON files(scan_id, size DESC);
CREATE INDEX IF NOT EXISTS idx_files_scan_category ON files(scan_id, category);
CREATE INDEX IF NOT EXISTS idx_files_scan_storage_class ON files(scan_id, storage_class);
CREATE INDEX IF NOT EXISTS idx_directories_scan_parent ON directories(scan_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_directories_scan_size ON directories(scan_id, total_size DESC);
CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON placement_plan_items(plan_id);
"""


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_columns(
    connection: sqlite3.Connection,
    table: str,
    columns: Iterable[tuple[str, str]],
) -> None:
    existing = _columns(connection, table)
    for name, definition in columns:
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_database() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        # Lightweight migration from baseline 0.2 databases.
        _ensure_columns(
            connection,
            "files",
            [
                ("category", "TEXT NOT NULL DEFAULT 'other'"),
                ("storage_class", "TEXT"),
                ("accessed_ns", "INTEGER"),
                ("created_ns", "INTEGER"),
            ],
        )
        _ensure_columns(
            connection,
            "directories",
            [
                ("category", "TEXT NOT NULL DEFAULT 'directory'"),
                ("storage_class", "TEXT"),
            ],
        )
        connection.commit()
