from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.config import settings
from backend.core.database import connect, init_database


DEFAULT_CLASSES = [
    ("incoming", "Incoming", "New and unsorted data", "Incoming", 10),
    ("active", "Active", "Frequently used mixed data", "Active", 20),
    ("media", "Media", "Video and audio library", "Media", 30),
    ("photos", "Photos", "Photos and RAW originals", "Photos", 40),
    ("documents", "Documents", "Documents and books", "Documents", 50),
    ("images", "Images / ISO", "Disk and installation images", "Images", 60),
    ("archive", "Archive", "Cold archives and long-term data", "Archive", 70),
    ("backups", "Backups", "Backup sets", "Backups", 80),
    ("development", "Development", "Source code and dependencies", "Development", 90),
    ("temporary", "Temporary", "Caches and temporary data", "Temporary", 100),
    ("vault", "Vault", "Encrypted private storage", "Vault", 110),
    ("quarantine", "Quarantine", "Safety quarantine", "Quarantine", 120),
    ("other", "Other", "Unclassified data", "Other", 999),
]

DEFAULT_RULES = [
    ("Photos", "photo", None, None, None, None, "photos", 10),
    ("Video", "video", None, None, None, None, "media", 20),
    ("Audio", "audio", None, None, None, None, "media", 30),
    ("Documents", "document", None, None, None, None, "documents", 40),
    ("Disk images", "disk_image", None, None, None, None, "images", 50),
    ("Archives", "archive", None, None, None, None, "archive", 60),
    ("Development", "development", None, None, None, None, "development", 70),
    ("Code", "code", None, None, None, None, "development", 80),
    ("Cache", "cache", None, None, None, None, "temporary", 90),
    ("Other", "other", None, None, None, None, "other", 1000),
]


@dataclass(frozen=True)
class CapacityPolicy:
    total: int
    used: int
    free: int
    reserve: int
    soft_limit: int
    hard_limit: int

    @property
    def state(self) -> str:
        ratio = self.used / self.total if self.total else 0
        if ratio >= settings.hard_fill_limit:
            return "critical"
        if ratio >= settings.soft_fill_limit:
            return "warning"
        return "normal"


def ensure_defaults() -> None:
    init_database()
    with connect() as connection:
        connection.executemany(
            """
            INSERT OR IGNORE INTO storage_classes
                (key, title, description, relative_root, priority)
            VALUES (?, ?, ?, ?, ?)
            """,
            DEFAULT_CLASSES,
        )
        connection.executemany(
            """
            INSERT OR IGNORE INTO placement_rules
                (name, category, extension, min_size, max_size, min_age_days,
                 target_class, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            DEFAULT_RULES,
        )
        connection.commit()


def list_storage_classes() -> list[dict]:
    ensure_defaults()
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM storage_classes WHERE enabled = 1 ORDER BY priority, key"
        ).fetchall()
    return [dict(row) for row in rows]


def capacity_policy(storage_root: Path) -> CapacityPolicy:
    usage = shutil.disk_usage(storage_root)
    reserve = int(usage.total * settings.reserve_fraction)
    return CapacityPolicy(
        total=usage.total,
        used=usage.used,
        free=usage.free,
        reserve=reserve,
        soft_limit=int(usage.total * settings.soft_fill_limit),
        hard_limit=int(usage.total * settings.hard_fill_limit),
    )


def _rules(connection) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM placement_rules WHERE enabled = 1 ORDER BY priority, id"
        ).fetchall()
    ]


def choose_storage_class(file_row: dict, rules: list[dict]) -> tuple[str, str]:
    for rule in rules:
        if rule["category"] and rule["category"] != file_row["category"]:
            continue
        if rule["extension"] and rule["extension"] != file_row["extension"]:
            continue
        if rule["min_size"] is not None and file_row["size"] < rule["min_size"]:
            continue
        if rule["max_size"] is not None and file_row["size"] > rule["max_size"]:
            continue
        if rule["min_age_days"] is not None and file_row.get("modified_ns"):
            age_seconds = datetime.now(UTC).timestamp() - (file_row["modified_ns"] / 1_000_000_000)
            if age_seconds < rule["min_age_days"] * 86400:
                continue
        return str(rule["target_class"]), str(rule["name"])
    return "other", "Fallback"


def create_placement_plan(scan_id: int, storage_root: Path) -> dict:
    ensure_defaults()
    storage_root = storage_root.resolve()
    policy = capacity_policy(storage_root)

    with connect() as connection:
        session = connection.execute(
            "SELECT * FROM scan_sessions WHERE id = ? AND status = 'completed'",
            (scan_id,),
        ).fetchone()
        if session is None:
            raise ValueError("Scan session not found or not completed")

        classes = {
            row["key"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM storage_classes WHERE enabled = 1"
            ).fetchall()
        }
        rules = _rules(connection)
        files = [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM files WHERE scan_id = ? ORDER BY size DESC",
                (scan_id,),
            ).fetchall()
        ]

        warnings: list[str] = []
        projected_used = policy.used
        items: list[tuple] = []

        for file_row in files:
            target_class, reason = choose_storage_class(file_row, rules)
            class_row = classes.get(target_class, classes["other"])
            source = Path(file_row["path"])
            target = storage_root / class_row["relative_root"] / source.name

            # Files already below the target class root are considered correctly placed.
            try:
                source.resolve().relative_to((storage_root / class_row["relative_root"]).resolve())
                continue
            except ValueError:
                pass

            items.append(
                (
                    str(source),
                    str(target),
                    target_class,
                    int(file_row["size"]),
                    reason,
                    "move",
                )
            )

        total_bytes = sum(item[3] for item in items)
        projected_free = max(0, policy.total - projected_used)
        if projected_free < policy.reserve:
            warnings.append("Free space is below the configured working reserve")
        if projected_used >= policy.soft_limit:
            warnings.append("Storage is above the soft fill limit")
        if projected_used >= policy.hard_limit:
            warnings.append("Storage is above the hard fill limit; write-heavy reorganization should stop")

        cursor = connection.execute(
            """
            INSERT INTO placement_plans (
                scan_id, storage_root, total_items, total_bytes, projected_used_bytes,
                projected_free_bytes, reserve_bytes, warnings
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                str(storage_root),
                len(items),
                total_bytes,
                projected_used,
                projected_free,
                policy.reserve,
                json.dumps(warnings, ensure_ascii=False),
            ),
        )
        plan_id = int(cursor.lastrowid)
        connection.executemany(
            """
            INSERT INTO placement_plan_items
                (plan_id, source_path, target_path, target_class, size, reason, action)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [(plan_id, *item) for item in items],
        )
        connection.commit()

    return get_plan(plan_id)


def get_plan(plan_id: int) -> dict:
    with connect() as connection:
        plan = connection.execute(
            "SELECT * FROM placement_plans WHERE id = ?", (plan_id,)
        ).fetchone()
        if plan is None:
            raise KeyError(plan_id)
        items = connection.execute(
            """
            SELECT * FROM placement_plan_items WHERE plan_id = ?
            ORDER BY size DESC, source_path
            """,
            (plan_id,),
        ).fetchall()

    result = dict(plan)
    result["warnings"] = json.loads(result["warnings"] or "[]")
    result["items"] = [dict(row) for row in items]
    return result
