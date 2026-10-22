from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from backend.storage_brain.executor import PlanExecutionBlocked, apply_plan, rollback_plan
from backend.storage_brain.service import capacity_policy, create_placement_plan, get_plan, list_storage_classes


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
    return jsonify({"total": policy.total, "used": policy.used, "free": policy.free, "reserve": policy.reserve, "soft_limit": policy.soft_limit, "hard_limit": policy.hard_limit, "state": policy.state})


@bp.post("/plans")
def create_plan():
    payload = request.get_json(silent=True) or {}
    try:
        scan_id = int(payload["scan_id"])
        root = Path(str(payload["storage_root"]))
        return jsonify(create_placement_plan(scan_id, root)), 201
    except (KeyError, TypeError, ValueError, FileNotFoundError, OSError) as exc:
        return jsonify({"error": "plan_failed", "message": str(exc)}), 400


@bp.get("/plans/<int:plan_id>")
def plan(plan_id: int):
    try:
        return jsonify(get_plan(plan_id))
    except KeyError:
        return jsonify({"error": "plan_not_found"}), 404


@bp.post("/plans/<int:plan_id>/apply")
def execute(plan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(apply_plan(plan_id, str(payload.get("confirmation", "")), str(payload.get("verify", "size"))))
    except PlanExecutionBlocked as exc:
        return jsonify({"error": "plan_execution_blocked", "message": str(exc)}), 403
    except (KeyError, ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "plan_execution_failed", "message": str(exc)}), 400


@bp.post("/plans/<int:plan_id>/rollback")
def rollback(plan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(rollback_plan(plan_id, str(payload.get("confirmation", ""))))
    except PlanExecutionBlocked as exc:
        return jsonify({"error": "plan_rollback_blocked", "message": str(exc)}), 403
    except (KeyError, ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        return jsonify({"error": "plan_rollback_failed", "message": str(exc)}), 400
