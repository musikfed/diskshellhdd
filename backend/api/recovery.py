from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.recovery.service import (
    create_recovery_snapshot,
    latest_recovery_snapshot,
    list_recovery_snapshots,
    probe_disk_signatures,
)
from backend.services.storage.windows_disks import DiskDetectionError, list_windows_disks


bp = Blueprint("recovery", __name__, url_prefix="/api/recovery")


@bp.get("/inventory")
def inventory():
    try:
        return jsonify({"disks": list_windows_disks()})
    except DiskDetectionError as exc:
        return jsonify({"error": "inventory_failed", "message": str(exc)}), 500


@bp.post("/snapshots")
def create_snapshot():
    try:
        return jsonify(create_recovery_snapshot()), 201
    except DiskDetectionError as exc:
        return jsonify({"error": "snapshot_failed", "message": str(exc)}), 500


@bp.get("/snapshots")
def snapshots():
    try:
        limit = int(request.args.get("limit", 20))
        return jsonify({"snapshots": list_recovery_snapshots(limit)})
    except ValueError as exc:
        return jsonify({"error": "invalid_limit", "message": str(exc)}), 400


@bp.get("/snapshots/latest")
def latest_snapshot():
    try:
        return jsonify(latest_recovery_snapshot())
    except KeyError:
        return jsonify({"error": "snapshot_not_found"}), 404


@bp.get("/disks/<int:disk_number>/signatures")
def signatures(disk_number: int):
    try:
        return jsonify(probe_disk_signatures(disk_number))
    except (ValueError, DiskDetectionError) as exc:
        return jsonify({"error": "signature_probe_failed", "message": str(exc)}), 400
