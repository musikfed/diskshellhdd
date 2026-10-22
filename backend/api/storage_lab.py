from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.storage_lab.service import benchmark_file, query_file_extents, simulate_interleave


bp = Blueprint("storage_lab", __name__, url_prefix="/api/storage-lab")


@bp.get("/simulate/<int:scan_id>")
def simulate(scan_id: int):
    try:
        chunk_size = int(request.args.get("chunk_size", 8 * 1024 * 1024))
        return jsonify(simulate_interleave(scan_id, chunk_size=chunk_size))
    except ValueError as exc:
        return jsonify({"error": "simulation_failed", "message": str(exc)}), 400


@bp.get("/extents")
def extents():
    path = request.args.get("path")
    if not path:
        return jsonify({"error": "missing_path"}), 400
    try:
        return jsonify(query_file_extents(path))
    except (FileNotFoundError, OSError, ValueError) as exc:
        return jsonify({"error": "extent_query_failed", "message": str(exc)}), 400


@bp.post("/benchmark")
def benchmark():
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(benchmark_file(str(payload["path"]), int(payload.get("block_size", 4 * 1024 * 1024)), int(payload.get("samples", 48))))
    except (KeyError, FileNotFoundError, OSError, ValueError) as exc:
        return jsonify({"error": "benchmark_failed", "message": str(exc)}), 400
