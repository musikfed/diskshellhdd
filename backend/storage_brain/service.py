from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.config import settings
from backend.core.database import connect, init_database
from backend.scanner.classifier import classify_path
from backend.storage_lab.service import CLASS_LANES, LANE_POLICIES


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
    ("Backups", "backup", None, None, None, None, "backups", 5),
    ("Photos", "photo", None, None, None, None, "photos", 10),
    ("Video", "video", None, None, None, None, "media", 20),
    ("Audio", "audio", None, None, None, None, "media", 30),
    ("Documents", "document", None, None, None, None, "documents", 40),
    ("Disk images", "disk_image", None, None, None, None, "images", 50),
    ("Archives", "archive", None, None, None, None, "archive", 60),
    ("Development", "development", None, None, None, None, "development", 70),
    ("Code", "code", None, None, None, None, "development", 80),
    ("Cache", "cache", None, None, None, None, "temporary", 90),
    ("Design", "design", None, None, None, None, "active", 100),
    ("Executables", "executable", None, None, None, None, "archive", 110),
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



def _normalized_path(value: Path | str) -> str:
    return os.path.normcase(os.path.abspath(os.path.expanduser(str(value))))


def _is_within(path: Path | str, root: Path | str) -> bool:
    candidate = _normalized_path(path)
    parent = _normalized_path(root)
    try:
        return os.path.commonpath([candidate, parent]) == parent
    except ValueError:
        return False


def _layout_hint(category: str) -> tuple[str, int]:
    lane = CLASS_LANES.get(category, "C-interactive")
    policy = LANE_POLICIES[lane]
    return lane, int(policy["target_band"])

def _existing_anchor(path: Path) -> Path:
    candidate = path.expanduser().resolve()
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    if not candidate.exists():
        raise FileNotFoundError(path)
    return candidate


def capacity_policy(storage_root: Path) -> CapacityPolicy:
    usage = shutil.disk_usage(_existing_anchor(storage_root))
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


def _same_volume(source: Path, target_root: Path) -> bool:
    if os.name == "nt":
        return source.drive.casefold() == target_root.drive.casefold()
    try:
        return source.stat().st_dev == _existing_anchor(target_root).stat().st_dev
    except OSError:
        return False


def _year(file_row: dict) -> str:
    value = file_row.get("modified_ns")
    if not value:
        return "Unknown year"
    try:
        return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).strftime("%Y")
    except (OSError, OverflowError, ValueError):
        return "Unknown year"


def _target_folder(storage_root: Path, class_row: dict, file_row: dict) -> Path:
    base = storage_root / class_row["relative_root"]
    category = file_row["category"]
    if category == "photo":
        return base / _year(file_row)
    if category == "video":
        return base / "Video"
    if category == "audio":
        return base / "Audio"
    if category in {"archive", "backup"}:
        return base / _year(file_row)
    if category in {"development", "code"}:
        parent = Path(file_row["parent_path"]).name or "Projects"
        return base / parent
    return base


def _unique_target(folder: Path, source: Path, reserved: set[str]) -> Path:
    target = folder / source.name
    key = str(target).casefold()
    if key not in reserved and not target.exists():
        reserved.add(key)
        return target

    parent_hint = source.parent.name.strip() or "item"
    candidate = folder / f"{source.stem} [{parent_hint}]{source.suffix}"
    counter = 2
    while str(candidate).casefold() in reserved or candidate.exists():
        candidate = folder / f"{source.stem} [{parent_hint} {counter}]{source.suffix}"
        counter += 1
    reserved.add(str(candidate).casefold())
    return candidate


def create_placement_plan(
    scan_id: int,
    storage_root: Path,
    source_roots: list[Path] | None = None,
    exclude_roots: list[Path] | None = None,
) -> dict:
    ensure_defaults()
    storage_root = storage_root.expanduser().resolve()
    policy = capacity_policy(storage_root)

    includes = [Path(item).expanduser() for item in (source_roots or [])]
    excludes = [Path(item).expanduser() for item in (exclude_roots or [])]
    excludes.extend([settings.project_root, settings.data_dir, storage_root])

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
        items: list[tuple] = []
        reserved_targets: set[str] = set()
        additional_target_bytes = 0

        selected_files = 0
        skipped_outside_scope = 0
        skipped_excluded = 0

        for file_row in files:
            source = Path(file_row["path"])
            if includes and not any(_is_within(source, root) for root in includes):
                skipped_outside_scope += 1
                continue
            if any(_is_within(source, root) for root in excludes):
                skipped_excluded += 1
                continue

            selected_files += 1
            target_class, reason = choose_storage_class(file_row, rules)
            class_row = classes.get(target_class, classes["other"])
            target_class_root = storage_root / class_row["relative_root"]

            try:
                source.resolve().relative_to(target_class_root.resolve())
                connection.execute(
                    "UPDATE files SET storage_class = ? WHERE id = ?",
                    (target_class, file_row["id"]),
                )
                continue
            except ValueError:
                pass

            target = _unique_target(
                _target_folder(storage_root, class_row, file_row),
                source,
                reserved_targets,
            )
            same_volume = _same_volume(source, storage_root)
            action = "move_same_volume" if same_volume else "copy_cross_volume"
            # This is a target logical layout policy only. The current writer does not
            # force NTFS extent placement; executor verification later compares the
            # actual NTFS-visible extent count with this macro-band target.
            layout_lane, target_band_bytes = _layout_hint(str(file_row["category"]))
            if not same_volume:
                additional_target_bytes += int(file_row["size"])

            items.append(
                (
                    str(source),
                    str(target),
                    target_class,
                    int(file_row["size"]),
                    reason,
                    action,
                    layout_lane,
                    target_band_bytes,
                )
            )
            connection.execute(
                "UPDATE files SET storage_class = ? WHERE id = ?",
                (target_class, file_row["id"]),
            )

        projected_used = policy.used + additional_target_bytes
        projected_free = max(0, policy.total - projected_used)
        if projected_free < policy.reserve:
            warnings.append("Projected free space is below the configured working reserve")
        if projected_used >= policy.soft_limit:
            warnings.append("Projected storage use is above the soft fill limit")
        if projected_used >= policy.hard_limit:
            warnings.append("Projected storage use is above the hard fill limit; do not apply this plan")

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
                sum(item[3] for item in items),
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
                (
                    plan_id, source_path, target_path, target_class, size,
                    reason, action, layout_lane, target_band_bytes, selected
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            [(plan_id, *item) for item in items],
        )
        connection.commit()

    result = get_plan_page(plan_id)
    result["scope"] = {
        "source_roots": [str(path) for path in includes],
        "exclude_roots": [str(path) for path in excludes],
        "selected_files": selected_files,
        "skipped_outside_scope": skipped_outside_scope,
        "skipped_excluded": skipped_excluded,
    }
    return result


def _decorate_plan(result: dict) -> dict:
    items = result["items"]
    for item in items:
        raw_layout = item.get("layout_verification")
        if isinstance(raw_layout, str) and raw_layout:
            try:
                item["layout_verification"] = json.loads(raw_layout)
            except json.JSONDecodeError:
                item["layout_verification"] = {
                    "status": "unknown",
                    "detail": raw_layout,
                }

    selected = [item for item in items if bool(item.get("selected", 1))]
    result["same_volume_items"] = sum(
        1 for item in items if item["action"] == "move_same_volume"
    )
    result["cross_volume_items"] = sum(
        1 for item in items if item["action"] == "copy_cross_volume"
    )
    result["additional_target_bytes"] = sum(
        int(item["size"])
        for item in items
        if item["action"] == "copy_cross_volume"
    )
    result["selected_items"] = len(selected)
    result["selected_bytes"] = sum(int(item["size"]) for item in selected)
    result["selected_cross_volume_items"] = sum(
        1 for item in selected if item["action"] == "copy_cross_volume"
    )
    result["selected_additional_target_bytes"] = sum(
        int(item["size"])
        for item in selected
        if item["action"] == "copy_cross_volume"
    )
    result["layout_checks"] = {
        "conforming": sum(
            1
            for item in selected
            if isinstance(item.get("layout_verification"), dict)
            and item["layout_verification"].get("status") == "conforming"
        ),
        "drift": sum(
            1
            for item in selected
            if isinstance(item.get("layout_verification"), dict)
            and item["layout_verification"].get("status") == "drift"
        ),
        "unavailable": sum(
            1
            for item in selected
            if isinstance(item.get("layout_verification"), dict)
            and item["layout_verification"].get("status") == "unavailable"
        ),
    }
    result["confirmation"] = f"APPLY PLAN {result['id']}"
    return result


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
    return _decorate_plan(result)


def get_plan_for_execution(plan_id: int) -> dict:
    """Return only explicitly selected plan items for the executor.

    Large plans can contain hundreds of thousands of rows. Keeping API paging and
    execution selection separate prevents an unchecked draft from being loaded
    into memory just because the operator applies a small reviewed batch.
    """
    with connect() as connection:
        plan = connection.execute(
            "SELECT * FROM placement_plans WHERE id = ?",
            (int(plan_id),),
        ).fetchone()
        if plan is None:
            raise KeyError(plan_id)
        items = connection.execute(
            """
            SELECT *
            FROM placement_plan_items
            WHERE plan_id=? AND selected=1
            ORDER BY size DESC, source_path
            """,
            (int(plan_id),),
        ).fetchall()

    result = dict(plan)
    result["warnings"] = json.loads(result["warnings"] or "[]")
    result["items"] = [_decode_layout_verification(dict(row)) for row in items]
    return result


def plan_has_remaining_items(plan_id: int) -> bool:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM placement_plan_items
            WHERE plan_id=? AND status!='completed'
            LIMIT 1
            """,
            (int(plan_id),),
        ).fetchone()
    return row is not None


def get_plan_layout_summary(plan_id: int) -> dict:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                SUM(CASE WHEN selected=1 AND layout_verification LIKE '%conforming%' THEN 1 ELSE 0 END)
                    AS conforming,
                SUM(CASE WHEN selected=1 AND layout_verification LIKE '%"status": "drift"%' THEN 1 ELSE 0 END)
                    AS drift,
                SUM(CASE WHEN selected=1 AND layout_verification LIKE '%unavailable%' THEN 1 ELSE 0 END)
                    AS unavailable
            FROM placement_plan_items
            WHERE plan_id=?
            """,
            (int(plan_id),),
        ).fetchone()
    return {
        "conforming": int(row["conforming"] or 0),
        "drift": int(row["drift"] or 0),
        "unavailable": int(row["unavailable"] or 0),
    }


def _decode_layout_verification(item: dict) -> dict:
    raw_layout = item.get("layout_verification")
    if isinstance(raw_layout, str) and raw_layout:
        try:
            item["layout_verification"] = json.loads(raw_layout)
        except json.JSONDecodeError:
            item["layout_verification"] = {
                "status": "unknown",
                "detail": raw_layout,
            }
    return item


def get_plan_page(
    plan_id: int,
    *,
    limit: int = 250,
    offset: int = 0,
    query: str = "",
) -> dict:
    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    query = str(query or "").strip()

    with connect() as connection:
        plan = connection.execute(
            "SELECT * FROM placement_plans WHERE id = ?",
            (int(plan_id),),
        ).fetchone()
        if plan is None:
            raise KeyError(plan_id)

        aggregate = connection.execute(
            """
            SELECT
                COUNT(*) AS item_count,
                SUM(CASE WHEN action='move_same_volume' THEN 1 ELSE 0 END) AS same_volume,
                SUM(CASE WHEN action='copy_cross_volume' THEN 1 ELSE 0 END) AS cross_volume,
                SUM(CASE WHEN action='copy_cross_volume' THEN size ELSE 0 END) AS extra_bytes,
                SUM(CASE WHEN selected=1 THEN 1 ELSE 0 END) AS selected_items,
                SUM(CASE WHEN selected=1 THEN size ELSE 0 END) AS selected_bytes,
                SUM(CASE WHEN selected=1 AND action='copy_cross_volume' THEN 1 ELSE 0 END)
                    AS selected_cross_volume,
                SUM(CASE WHEN selected=1 AND action='copy_cross_volume' THEN size ELSE 0 END)
                    AS selected_extra_bytes,
                SUM(CASE WHEN selected=1 AND layout_verification LIKE '%conforming%' THEN 1 ELSE 0 END)
                    AS layout_conforming,
                SUM(CASE WHEN selected=1 AND layout_verification LIKE '%"status": "drift"%' THEN 1 ELSE 0 END)
                    AS layout_drift,
                SUM(CASE WHEN selected=1 AND layout_verification LIKE '%unavailable%' THEN 1 ELSE 0 END)
                    AS layout_unavailable
            FROM placement_plan_items
            WHERE plan_id=?
            """,
            (int(plan_id),),
        ).fetchone()

        where = "plan_id=?"
        params: list[object] = [int(plan_id)]
        if query:
            where += (
                " AND (source_path LIKE ? COLLATE NOCASE"
                " OR target_path LIKE ? COLLATE NOCASE"
                " OR target_class LIKE ? COLLATE NOCASE)"
            )
            like = f"%{query}%"
            params.extend([like, like, like])

        filtered = connection.execute(
            f"SELECT COUNT(*) AS count FROM placement_plan_items WHERE {where}",
            params,
        ).fetchone()
        rows = connection.execute(
            f"""
            SELECT *
            FROM placement_plan_items
            WHERE {where}
            ORDER BY size DESC, source_path
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        ).fetchall()

    result = dict(plan)
    result["warnings"] = json.loads(result["warnings"] or "[]")
    result["items"] = [_decode_layout_verification(dict(row)) for row in rows]
    result["same_volume_items"] = int(aggregate["same_volume"] or 0)
    result["cross_volume_items"] = int(aggregate["cross_volume"] or 0)
    result["additional_target_bytes"] = int(aggregate["extra_bytes"] or 0)
    result["selected_items"] = int(aggregate["selected_items"] or 0)
    result["selected_bytes"] = int(aggregate["selected_bytes"] or 0)
    result["selected_cross_volume_items"] = int(
        aggregate["selected_cross_volume"] or 0
    )
    result["selected_additional_target_bytes"] = int(
        aggregate["selected_extra_bytes"] or 0
    )
    result["layout_checks"] = {
        "conforming": int(aggregate["layout_conforming"] or 0),
        "drift": int(aggregate["layout_drift"] or 0),
        "unavailable": int(aggregate["layout_unavailable"] or 0),
    }
    result["page"] = {
        "limit": limit,
        "offset": offset,
        "returned": len(rows),
        "filtered": int(filtered["count"] or 0),
        "total": int(aggregate["item_count"] or 0),
        "query": query,
    }
    result["confirmation"] = f"APPLY PLAN {plan_id}"
    return result


def update_plan_selection(
    plan_id: int,
    *,
    selected: bool,
    item_ids: list[int] | None = None,
    all_items: bool = False,
    query: str = "",
) -> dict:
    with connect() as connection:
        plan = connection.execute(
            "SELECT status FROM placement_plans WHERE id = ?",
            (int(plan_id),),
        ).fetchone()
        if plan is None:
            raise KeyError(plan_id)
        if plan["status"] == "running":
            raise ValueError("Cannot change selection while the plan is running")

        value = 1 if selected else 0
        if all_items:
            query = str(query or "").strip()
            if query:
                like = f"%{query}%"
                connection.execute(
                    """
                    UPDATE placement_plan_items
                    SET selected=?
                    WHERE plan_id=?
                      AND (
                        source_path LIKE ? COLLATE NOCASE
                        OR target_path LIKE ? COLLATE NOCASE
                        OR target_class LIKE ? COLLATE NOCASE
                      )
                    """,
                    (value, int(plan_id), like, like, like),
                )
            else:
                connection.execute(
                    "UPDATE placement_plan_items SET selected=? WHERE plan_id=?",
                    (value, int(plan_id)),
                )
        else:
            ids = [int(item_id) for item_id in (item_ids or [])]
            if not ids:
                raise ValueError("item_ids is required unless all_items=true")
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"""
                UPDATE placement_plan_items
                SET selected=?
                WHERE plan_id=? AND id IN ({placeholders})
                """,
                (value, int(plan_id), *ids),
            )
        connection.commit()
    return get_plan_page(plan_id, query=query)


def get_latest_plan(
    scan_id: int | None = None,
    *,
    limit: int = 250,
    offset: int = 0,
    query: str = "",
) -> dict:
    with connect() as connection:
        if scan_id is None:
            row = connection.execute(
                "SELECT id FROM placement_plans ORDER BY id DESC LIMIT 1"
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT id FROM placement_plans WHERE scan_id = ? ORDER BY id DESC LIMIT 1",
                (int(scan_id),),
            ).fetchone()
    if row is None:
        raise KeyError("latest")
    return get_plan_page(
        int(row["id"]),
        limit=limit,
        offset=offset,
        query=query,
    )


def suggest_managed_destination(
    source_name: str,
    source_path: str,
    size: int,
    modified_ns: int | None,
    storage_root: Path,
) -> dict:
    ensure_defaults()
    root = storage_root.expanduser().resolve()
    source_name = str(source_name).strip()
    if not source_name:
        raise ValueError("source_name is required")

    category = classify_path(Path(source_name))
    fake_row = {
        "category": category,
        "extension": Path(source_name).suffix.casefold(),
        "size": int(size or 0),
        "modified_ns": int(modified_ns) if modified_ns else None,
        "parent_path": str(Path(source_path).parent),
    }

    with connect() as connection:
        rules = _rules(connection)
        classes = {
            row["key"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM storage_classes WHERE enabled = 1"
            ).fetchall()
        }

    target_class, reason = choose_storage_class(fake_row, rules)
    class_row = classes.get(target_class, classes["other"])
    folder = _target_folder(root, class_row, fake_row)
    source = Path(source_name)
    target = folder / source.name
    counter = 2
    while target.exists():
        target = folder / f"{source.stem} [{counter}]{source.suffix}"
        counter += 1

    lane, target_band_bytes = _layout_hint(category)
    return {
        "category": category,
        "target_class": target_class,
        "reason": reason,
        "destination": str(target),
        "layout_lane": lane,
        "target_band_bytes": target_band_bytes,
        "storage_root": str(root),
    }
