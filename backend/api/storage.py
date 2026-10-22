from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from backend.storage_brain.executor import PlanExecutionBlocked, apply_plan, rollback_plan
from backend.storage_brain.jobs import cancel_plan_job, get_plan_job, start_plan_job
from backend.storage_brain.service import (
    capacity_policy,
    create_placement_plan,
    get_latest_plan,
    get_plan_page,
    list_storage_classes,
    update_plan_selection,
)


bp = Blueprint("storage", __name__, url_prefix="/api/storage")


@bp.get("/classes")
def classes():
    return jsonify({"classes": list_storage_classes()})


@bp.get("/capacity")
def capacity():
    raw = request.args.get("path")
    if not raw:
        return jsonify({"error": "missing_path"}), 400
    try:
        policy = capacity_policy(Path(raw))
    except (FileNotFoundError, OSError, ValueError) as exc:
        return jsonify({"error": "capacity_failed", "message": str(exc)}), 400
    return jsonify(
        {
            "total": policy.total,
            "used": policy.used,
            "free": policy.free,
            "reserve": policy.reserve,
            "soft_limit": policy.soft_limit,
            "hard_limit": policy.hard_limit,
            "state": policy.state,
        }
    )


@bp.post("/plans")
def create_plan():
    payload = request.get_json(silent=True) or {}
    try:
        scan_id = int(payload["scan_id"])
        root = Path(str(payload["storage_root"]))
        source_roots = [
            Path(str(item))
            for item in (payload.get("source_roots") or [])
            if str(item).strip()
        ]
        exclude_roots = [
            Path(str(item))
            for item in (payload.get("exclude_roots") or [])
            if str(item).strip()
        ]
        return (
            jsonify(
                create_placement_plan(
                    scan_id,
                    root,
                    source_roots=source_roots,
                    exclude_roots=exclude_roots,
                )
            ),
            201,
        )
    except (KeyError, TypeError, ValueError, FileNotFoundError, OSError) as exc:
        return jsonify({"error": "plan_failed", "message": str(exc)}), 400


@bp.get("/plans/latest")
def latest_plan():
    raw_scan_id = request.args.get("scan_id")
    try:
        scan_id = int(raw_scan_id) if raw_scan_id else None
        limit = int(request.args.get("limit", 250))
        offset = int(request.args.get("offset", 0))
        query = str(request.args.get("q", ""))
        return jsonify(
            get_latest_plan(
                scan_id,
                limit=limit,
                offset=offset,
                query=query,
            )
        )
    except (KeyError, ValueError):
        return jsonify({"error": "plan_not_found"}), 404


@bp.get("/plans/<int:plan_id>")
def plan(plan_id: int):
    try:
        return jsonify(
            get_plan_page(
                plan_id,
                limit=int(request.args.get("limit", 250)),
                offset=int(request.args.get("offset", 0)),
                query=str(request.args.get("q", "")),
            )
        )
    except KeyError:
        return jsonify({"error": "plan_not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": "invalid_pagination", "message": str(exc)}), 400


@bp.post("/plans/<int:plan_id>/apply")
def execute(plan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            apply_plan(
                plan_id,
                str(payload.get("confirmation", "")),
                str(payload.get("verify", "size")),
            )
        )
    except PlanExecutionBlocked as exc:
        return jsonify({"error": "plan_execution_blocked", "message": str(exc)}), 403
    except (KeyError, ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "plan_execution_failed", "message": str(exc)}), 400


@bp.post("/plans/<int:plan_id>/apply-job")
def execute_job(plan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return (
            jsonify(
                start_plan_job(
                    plan_id,
                    str(payload.get("confirmation", "")),
                    str(payload.get("verify", "size")),
                )
            ),
            202,
        )
    except (KeyError, ValueError) as exc:
        return jsonify({"error": "plan_job_failed", "message": str(exc)}), 400


@bp.get("/jobs/<job_id>")
def placement_job(job_id: str):
    try:
        return jsonify(get_plan_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/jobs/<job_id>/cancel")
def cancel_placement_job(job_id: str):
    try:
        return jsonify(cancel_plan_job(job_id))
    except KeyError:
        return jsonify({"error": "job_not_found"}), 404


@bp.post("/plans/<int:plan_id>/rollback")
def rollback(plan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(rollback_plan(plan_id, str(payload.get("confirmation", ""))))
    except PlanExecutionBlocked as exc:
        return jsonify({"error": "plan_rollback_blocked", "message": str(exc)}), 403
    except (KeyError, ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "plan_rollback_failed", "message": str(exc)}), 400


@bp.post("/plans/<int:plan_id>/selection")
def selection(plan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(
            update_plan_selection(
                plan_id,
                selected=bool(payload.get("selected", True)),
                item_ids=[int(item) for item in (payload.get("item_ids") or [])],
                all_items=bool(payload.get("all_items", False)),
                query=str(payload.get("query", "")),
            )
        )
    except KeyError:
        return jsonify({"error": "plan_not_found"}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "selection_failed", "message": str(exc)}), 400
