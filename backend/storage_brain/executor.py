from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core.database import connect
from backend.files.write_authorization import file_writes_allowed
from backend.storage_brain.service import (
    capacity_policy,
    get_plan,
    get_plan_for_execution,
    get_plan_layout_summary,
    plan_has_remaining_items,
)
from backend.storage_lab.service import query_file_extents


class PlanExecutionBlocked(RuntimeError):
    pass


class PlanExecutionCancelled(RuntimeError):
    pass


CancelCallback = Callable[[], bool]
ProgressCallback = Callable[[dict[str, Any]], None]


def _check_cancel(cancel_callback: CancelCallback | None) -> None:
    if cancel_callback is not None and cancel_callback():
        raise PlanExecutionCancelled("Placement execution cancelled by operator")


def _digest(path: Path, cancel_callback: CancelCallback | None = None) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            _check_cancel(cancel_callback)
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _copy_with_cancel(
    source: Path,
    target: Path,
    cancel_callback: CancelCallback | None,
    byte_callback: Callable[[int], None] | None = None,
) -> None:
    with source.open("rb") as src, target.open("xb") as dst:
        while True:
            _check_cancel(cancel_callback)
            chunk = src.read(8 * 1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
            if byte_callback is not None:
                byte_callback(len(chunk))
        dst.flush()
        os.fsync(dst.fileno())
    shutil.copystat(source, target, follow_symlinks=False)


def _verify(
    source_size: int,
    target: Path,
    expected_digest: str | None,
    cancel_callback: CancelCallback | None = None,
) -> str:
    _check_cancel(cancel_callback)
    actual_size = target.stat().st_size
    if actual_size != source_size:
        raise OSError(f"Verification failed: target size {actual_size} != {source_size}")
    if expected_digest is not None:
        actual_digest = _digest(target, cancel_callback)
        if actual_digest != expected_digest:
            raise OSError("Verification failed: SHA-256 mismatch")
        return f"sha256:{actual_digest}"
    return f"size:{actual_size}"


def _verify_layout(item: dict[str, Any], target: Path) -> dict[str, Any]:
    """Compare actual NTFS-visible extents with the planned macro-band target.

    This does NOT inspect hidden platter/head/angular geometry and it does not
    move extents. It is a read-only conformance check for the logical layout
    policy that a future managed writer/rebalancer may enforce.
    """
    target_band = int(item.get("target_band_bytes") or 0)
    if target_band <= 0:
        return {
            "status": "unavailable",
            "reason": "No target band is defined for this item",
        }

    result = query_file_extents(target)
    if not result.get("supported"):
        return {
            "status": "unavailable",
            "reason": result.get("reason") or "NTFS extent query unavailable",
        }

    actual = int(result.get("extent_count") or 0)
    size = max(0, int(item.get("size") or 0))
    expected = max(1, int(round(size / target_band))) if size else 1
    tolerance = max(1, int(math.ceil(expected * 0.25)))
    delta = abs(actual - expected)
    status = "conforming" if actual > 0 and delta <= tolerance else "drift"

    return {
        "status": status,
        "actual_extents": actual,
        "expected_extents": expected,
        "tolerance": tolerance,
        "target_band_bytes": target_band,
        "layout_lane": item.get("layout_lane"),
        "note": (
            "NTFS logical extent check only; HDD firmware physical geometry is hidden."
        ),
    }


def _journal(
    connection,
    plan_id: int,
    item_id: int,
    operation: str,
    source: Path,
    target: Path,
    status: str,
    detail: str = "",
) -> None:
    connection.execute(
        """
        INSERT INTO operation_journal
            (plan_id, plan_item_id, operation, source_path, target_path, status, detail)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (plan_id, item_id, operation, str(source), str(target), status, detail),
    )


def _set_plan_status(plan_id: int, status: str) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE placement_plans
            SET status=?, completed_at=CASE
                WHEN ? IN ('completed','partial','failed','cancelled','rolled_back')
                THEN CURRENT_TIMESTAMP ELSE completed_at END
            WHERE id=?
            """,
            (status, status, plan_id),
        )
        connection.commit()


def apply_plan(
    plan_id: int,
    confirmation: str,
    verify: str = "size",
    cancel_callback: CancelCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    if not file_writes_allowed():
        raise PlanExecutionBlocked("File writes are locked")
    if confirmation != f"APPLY PLAN {plan_id}":
        raise PlanExecutionBlocked("Typed confirmation does not match")
    if verify not in {"size", "sha256"}:
        raise ValueError("verify must be 'size' or 'sha256'")

    plan = get_plan_for_execution(plan_id)
    if plan["status"] not in {"draft", "failed", "partial", "cancelled"}:
        raise PlanExecutionBlocked(f"Plan status is {plan['status']}")

    selected_items = plan["items"]
    if not selected_items:
        raise PlanExecutionBlocked("No placement items are selected")

    # Capacity is checked against the current selected batch, not the whole
    # draft plan. This lets an operator safely apply only a checked subset.
    policy = capacity_policy(Path(plan["storage_root"]))
    selected_target_bytes = sum(
        int(item.get("size") or 0)
        for item in selected_items
        if item["action"] == "copy_cross_volume"
        and item["status"] != "completed"
    )
    if policy.free - selected_target_bytes < policy.reserve:
        raise PlanExecutionBlocked(
            "Selected items violate the configured working-space reserve"
        )

    with connect() as connection:
        connection.execute(
            "UPDATE placement_plans SET status='running', started_at=CURRENT_TIMESTAMP, completed_at=NULL WHERE id=?",
            (plan_id,),
        )
        connection.commit()

    completed = 0
    failed = 0
    copied = 0
    moved = 0
    total = len(selected_items)
    total_bytes = sum(int(item.get("size") or 0) for item in selected_items)
    processed_bytes = 0
    active_item_bytes = 0

    def report(current: dict[str, Any] | None = None) -> None:
        if progress_callback is None:
            return
        progress_callback(
            {
                "plan_id": plan_id,
                "completed": completed,
                "failed": failed,
                "copied": copied,
                "moved": moved,
                "total": total,
                "total_bytes": total_bytes,
                "processed_bytes": processed_bytes + active_item_bytes,
                "progress_percent": (
                    min(100.0, (processed_bytes + active_item_bytes) * 100.0 / total_bytes)
                    if total_bytes > 0
                    else None
                ),
                "current": current,
            }
        )

    report()

    try:
        for item in selected_items:
            _check_cancel(cancel_callback)
            active_item_bytes = 0
            if item["status"] == "completed":
                completed += 1
                processed_bytes += int(item.get("size") or 0)
                report(item)
                continue

            source = Path(item["source_path"])
            target = Path(item["target_path"])
            try:
                if not source.exists():
                    if target.exists() and target.is_file() and target.stat().st_size == item["size"]:
                        verification = _verify(item["size"], target, None, cancel_callback)
                        layout_verification = _verify_layout(item, target)
                        with connect() as connection:
                            connection.execute(
                                """
                                UPDATE placement_plan_items
                                SET status='completed', verification=?,
                                    layout_verification=?, error=NULL
                                WHERE id=?
                                """,
                                (
                                    verification,
                                    json.dumps(layout_verification, ensure_ascii=False),
                                    item["id"],
                                ),
                            )
                            _journal(
                                connection,
                                plan_id,
                                item["id"],
                                item["action"],
                                source,
                                target,
                                "completed",
                                "Source already absent; target verified",
                            )
                            connection.commit()
                        completed += 1
                        processed_bytes += int(item.get("size") or 0)
                        report(item)
                        continue
                    raise FileNotFoundError(source)
                if not source.is_file():
                    raise ValueError("Placement executor currently handles files only")
                if target.exists():
                    raise FileExistsError(target)

                source_size = source.stat().st_size
                if source_size != item["size"]:
                    raise OSError("Source changed since the scan; rebuild the plan")

                expected_digest = (
                    _digest(source, cancel_callback) if verify == "sha256" else None
                )
                target.parent.mkdir(parents=True, exist_ok=True)

                if item["action"] == "move_same_volume":
                    os.replace(source, target)
                    try:
                        verification = _verify(
                            source_size,
                            target,
                            expected_digest,
                            cancel_callback,
                        )
                    except Exception:
                        if target.exists() and not source.exists():
                            os.replace(target, source)
                        raise
                    moved += 1
                    active_item_bytes = source_size
                    report(item)
                else:
                    partial = target.with_name(
                        f".{target.name}.diskshell-partial-{uuid.uuid4().hex}"
                    )
                    try:
                        def add_bytes(count: int) -> None:
                            nonlocal active_item_bytes
                            active_item_bytes += count
                            report(item)

                        _copy_with_cancel(
                            source,
                            partial,
                            cancel_callback,
                            byte_callback=add_bytes,
                        )
                        verification = _verify(
                            source_size,
                            partial,
                            expected_digest,
                            cancel_callback,
                        )
                        _check_cancel(cancel_callback)
                        os.replace(partial, target)
                    finally:
                        if partial.exists():
                            partial.unlink(missing_ok=True)
                    copied += 1

                layout_verification = _verify_layout(item, target)
                with connect() as connection:
                    connection.execute(
                        """
                        UPDATE placement_plan_items
                        SET status='completed', verification=?,
                            layout_verification=?, error=NULL
                        WHERE id=?
                        """,
                        (
                            verification,
                            json.dumps(layout_verification, ensure_ascii=False),
                            item["id"],
                        ),
                    )
                    _journal(
                        connection,
                        plan_id,
                        item["id"],
                        item["action"],
                        source,
                        target,
                        "completed",
                        verification,
                    )
                    connection.commit()
                completed += 1
                processed_bytes += source_size
                active_item_bytes = 0
                report(item)

            except PlanExecutionCancelled:
                raise
            except (OSError, ValueError) as exc:
                failed += 1
                active_item_bytes = 0
                with connect() as connection:
                    connection.execute(
                        "UPDATE placement_plan_items SET status='failed', error=? WHERE id=?",
                        (str(exc), item["id"]),
                    )
                    _journal(
                        connection,
                        plan_id,
                        item["id"],
                        item["action"],
                        source,
                        target,
                        "failed",
                        str(exc),
                    )
                    connection.commit()
                report(item)

    except PlanExecutionCancelled:
        _set_plan_status(plan_id, "cancelled")
        raise

    remaining = plan_has_remaining_items(plan_id)
    status = (
        "failed"
        if failed and completed == 0
        else "partial"
        if failed or remaining
        else "completed"
    )
    _set_plan_status(plan_id, status)

    return {
        "plan_id": plan_id,
        "status": status,
        "completed": completed,
        "failed": failed,
        "same_volume_moves": moved,
        "verified_cross_volume_copies": copied,
        "cross_volume_source_policy": "kept",
        "layout_verification": get_plan_layout_summary(plan_id),
        "note": (
            "Cross-volume originals are intentionally kept. Integrity is verified; "
            "layout verification checks NTFS-visible extents against the planned "
            "macro-band target and does not claim physical platter geometry."
        ),
    }


def rollback_plan(plan_id: int, confirmation: str) -> dict:
    if not file_writes_allowed():
        raise PlanExecutionBlocked("File writes are locked")
    if confirmation != f"ROLLBACK PLAN {plan_id}":
        raise PlanExecutionBlocked("Typed confirmation does not match")

    plan = get_plan(plan_id)
    restored = 0
    skipped = 0
    for item in reversed(plan["items"]):
        if item["action"] != "move_same_volume" or item["status"] != "completed":
            skipped += 1
            continue
        source = Path(item["source_path"])
        target = Path(item["target_path"])
        if source.exists() or not target.exists():
            skipped += 1
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        os.replace(target, source)
        with connect() as connection:
            connection.execute(
                "UPDATE placement_plan_items SET status='rolled_back', error=NULL WHERE id=?",
                (item["id"],),
            )
            _journal(
                connection,
                plan_id,
                item["id"],
                "rollback",
                target,
                source,
                "completed",
            )
            connection.commit()
        restored += 1

    _set_plan_status(plan_id, "rolled_back")
    return {
        "plan_id": plan_id,
        "status": "rolled_back",
        "restored": restored,
        "skipped": skipped,
    }
