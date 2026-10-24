from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable

from backend.config import settings


DATABASE_PATH = settings.data_dir / "diskshell.db"

_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()


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

CREATE TABLE IF NOT EXISTS file_hashes (
    file_id INTEGER PRIMARY KEY,
    algorithm TEXT NOT NULL,
    digest TEXT NOT NULL,
    size INTEGER NOT NULL,
    hashed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
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
    started_at TEXT,
    completed_at TEXT,
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
    layout_lane TEXT,
    target_band_bytes INTEGER,
    selected INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    verification TEXT,
    layout_verification TEXT,
    error TEXT,
    FOREIGN KEY (plan_id) REFERENCES placement_plans(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS operation_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER,
    plan_item_id INTEGER,
    operation TEXT NOT NULL,
    source_path TEXT NOT NULL,
    target_path TEXT,
    status TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (plan_id) REFERENCES placement_plans(id) ON DELETE SET NULL,
    FOREIGN KEY (plan_item_id) REFERENCES placement_plan_items(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    width INTEGER,
    height INTEGER,
    faces_count INTEGER NOT NULL DEFAULT 0,
    analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    UNIQUE(scan_id, file_id)
);

CREATE TABLE IF NOT EXISTS image_subject_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    label TEXT NOT NULL,
    score REAL NOT NULL,
    model_key TEXT NOT NULL,
    analyzed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
    UNIQUE(scan_id, file_id, label, model_key)
);

CREATE TABLE IF NOT EXISTS persons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    auto_cluster INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scan_id) REFERENCES scan_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id INTEGER NOT NULL,
    person_id INTEGER,
    x REAL NOT NULL,
    y REAL NOT NULL,
    width REAL NOT NULL,
    height REAL NOT NULL,
    score REAL NOT NULL,
    embedding BLOB,
    embedding_dim INTEGER,
    FOREIGN KEY (photo_id) REFERENCES photos(id) ON DELETE CASCADE,
    FOREIGN KEY (person_id) REFERENCES persons(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS access_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    operation TEXT NOT NULL,
    latency_ms REAL,
    bytes_count INTEGER,
    sampled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recovery_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    engine TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_code INTEGER,
    threats INTEGER,
    output TEXT,
    started_at TEXT,
    completed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_catalog (
    path TEXT PRIMARY KEY,
    parent_path TEXT NOT NULL,
    name TEXT NOT NULL,
    extension TEXT,
    category TEXT NOT NULL DEFAULT 'other',
    size INTEGER NOT NULL DEFAULT 0,
    modified_ns INTEGER,
    accessed_ns INTEGER,
    created_ns INTEGER,
    last_scan_id INTEGER,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS file_catalog_roots (
    root_path TEXT PRIMARY KEY,
    last_scan_id INTEGER,
    status TEXT NOT NULL DEFAULT 'unknown',
    files_count INTEGER NOT NULL DEFAULT 0,
    refreshed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    active_page TEXT NOT NULL DEFAULT 'dashboard',
    active_volume TEXT NOT NULL DEFAULT '',
    scan_id TEXT NOT NULL DEFAULT '',
    view_state_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workspace_views (
    view_id TEXT PRIMARY KEY,
    active_page TEXT NOT NULL DEFAULT 'dashboard',
    active_volume TEXT NOT NULL DEFAULT '',
    scan_id TEXT NOT NULL DEFAULT '',
    view_state_json TEXT NOT NULL DEFAULT '{}',
    detached INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS streamcopy_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    source_path TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    source_endpoint_json TEXT NOT NULL DEFAULT '{}',
    destination_endpoint_json TEXT NOT NULL DEFAULT '{}',
    profile_json TEXT NOT NULL DEFAULT '{}',
    verify_mode TEXT NOT NULL DEFAULT 'size',
    delete_source_after_verify INTEGER NOT NULL DEFAULT 0,
    target_root TEXT,
    current_item_index INTEGER,
    current_path TEXT NOT NULL DEFAULT '',
    bytes INTEGER NOT NULL DEFAULT 0,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    files INTEGER NOT NULL DEFAULT 0,
    total_files INTEGER NOT NULL DEFAULT 0,
    skipped INTEGER NOT NULL DEFAULT 0,
    skipped_bytes INTEGER NOT NULL DEFAULT 0,
    manifest_files INTEGER NOT NULL DEFAULT 0,
    manifest_directories INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    error TEXT,
    progress_percent REAL NOT NULL DEFAULT 0,
    average_mib_s REAL NOT NULL DEFAULT 0,
    wait_cycles INTEGER NOT NULL DEFAULT 0,
    auto_resumes INTEGER NOT NULL DEFAULT 0,
    waiting_since TEXT,
    lease_owner TEXT,
    lease_expires_at REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS streamcopy_items (
    job_id TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    source_path TEXT NOT NULL,
    target_path TEXT NOT NULL,
    partial_path TEXT NOT NULL,
    size INTEGER NOT NULL,
    source_mtime_ns INTEGER,
    status TEXT NOT NULL DEFAULT 'pending',
    confirmed_offset INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    PRIMARY KEY (job_id, item_index),
    FOREIGN KEY (job_id) REFERENCES streamcopy_jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS streamcopy_checkpoints (
    job_id TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    block_start INTEGER NOT NULL,
    block_size INTEGER NOT NULL,
    digest TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (job_id, item_index, offset),
    FOREIGN KEY (job_id, item_index)
        REFERENCES streamcopy_items(job_id, item_index)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS commander_jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    operation TEXT NOT NULL,
    job_json TEXT NOT NULL DEFAULT '{}',
    transfers_json TEXT NOT NULL DEFAULT '[]',
    lease_owner TEXT,
    lease_expires_at REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS diagnostic_runs (
    id TEXT PRIMARY KEY,
    disk_number INTEGER NOT NULL,
    disk_identity TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    rating TEXT,
    total_bytes INTEGER NOT NULL DEFAULT 0,
    sampled_bytes INTEGER NOT NULL DEFAULT 0,
    read_errors INTEGER NOT NULL DEFAULT 0,
    slow_cells INTEGER NOT NULL DEFAULT 0,
    cells_json TEXT NOT NULL DEFAULT '[]',
    summary_json TEXT NOT NULL DEFAULT '{}'
);

"""

INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_files_scan_parent ON files(scan_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_files_scan_size ON files(scan_id, size DESC);
CREATE INDEX IF NOT EXISTS idx_files_scan_category ON files(scan_id, category);
CREATE INDEX IF NOT EXISTS idx_files_scan_storage_class ON files(scan_id, storage_class);
CREATE INDEX IF NOT EXISTS idx_file_catalog_name ON file_catalog(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_file_catalog_parent ON file_catalog(parent_path);
CREATE INDEX IF NOT EXISTS idx_file_catalog_extension ON file_catalog(extension);
CREATE INDEX IF NOT EXISTS idx_file_catalog_category ON file_catalog(category);
CREATE INDEX IF NOT EXISTS idx_file_catalog_size ON file_catalog(size DESC);
CREATE INDEX IF NOT EXISTS idx_file_catalog_modified ON file_catalog(modified_ns DESC);
CREATE INDEX IF NOT EXISTS idx_hash_digest ON file_hashes(algorithm, digest, size);
CREATE INDEX IF NOT EXISTS idx_directories_scan_parent ON directories(scan_id, parent_path);
CREATE INDEX IF NOT EXISTS idx_directories_scan_size ON directories(scan_id, total_size DESC);
CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON placement_plan_items(plan_id, status);
CREATE INDEX IF NOT EXISTS idx_photos_scan ON photos(scan_id);
CREATE INDEX IF NOT EXISTS idx_subject_tags_scan_label
ON image_subject_tags(scan_id, label, score DESC);
CREATE INDEX IF NOT EXISTS idx_subject_tags_file
ON image_subject_tags(file_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_faces_photo ON faces(photo_id);
CREATE INDEX IF NOT EXISTS idx_faces_person ON faces(person_id);
CREATE INDEX IF NOT EXISTS idx_persons_scan ON persons(scan_id);
CREATE INDEX IF NOT EXISTS idx_streamcopy_jobs_status
ON streamcopy_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_streamcopy_items_job_status
ON streamcopy_items(job_id, status, item_index);
CREATE INDEX IF NOT EXISTS idx_streamcopy_checkpoints_item
ON streamcopy_checkpoints(job_id, item_index, offset DESC);
CREATE INDEX IF NOT EXISTS idx_commander_jobs_status
ON commander_jobs(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diagnostic_runs_disk
ON diagnostic_runs(disk_number, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_workspace_views_updated
ON workspace_views(updated_at DESC);
"""


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH, timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=30000")
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
    database_key = str(DATABASE_PATH.resolve())
    if database_key in _INITIALIZED_PATHS:
        return

    with _INIT_LOCK:
        if database_key in _INITIALIZED_PATHS:
            return

        with connect() as connection:
            # WAL is a database-level setting and can require an exclusive lock.
            # Configure it once during schema initialization, never on every request.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.executescript(SCHEMA)
            # Lightweight migrations from 0.2/0.3. Runtime state is kept intact.
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
            _ensure_columns(
                connection,
                "placement_plans",
                [
                    ("started_at", "TEXT"),
                    ("completed_at", "TEXT"),
                ],
            )
            _ensure_columns(
                connection,
                "workspace_state",
                [
                    ("view_state_json", "TEXT NOT NULL DEFAULT '{}'"),
                ],
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO workspace_state
                    (id, active_page, active_volume, scan_id, view_state_json)
                VALUES (1, 'dashboard', '', '', '{}')
                """
            )
            _ensure_columns(
                connection,
                "placement_plan_items",
                [
                    ("status", "TEXT NOT NULL DEFAULT 'pending'"),
                    ("verification", "TEXT"),
                    ("error", "TEXT"),
                    ("layout_lane", "TEXT"),
                    ("target_band_bytes", "INTEGER"),
                    ("selected", "INTEGER NOT NULL DEFAULT 0"),
                    ("layout_verification", "TEXT"),
                ],
            )
            # Indexes that reference migrated columns must be created only after
            # legacy 0.2/0.3 tables have received those columns.
            connection.executescript(INDEX_SCHEMA)
            connection.commit()

        _INITIALIZED_PATHS.add(database_key)
