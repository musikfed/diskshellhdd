from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.storage_lab.service import benchmark_file, query_file_extents, simulate_interleave


bp = Blueprint("storage_lab", __name__, url_prefix="/api/storage-lab")


@bp.get("/simulate/<int:scan_id>")
def simulate(scan_id: int):
    try:
        sequential_mib_s = float(request.args.get("sequential_mib_s", 150))
        seek_ms = float(request.args.get("seek_ms", 10))
        target_seek_overhead = float(request.args.get("target_seek_overhead", 0.02))
        max_layout_extents = int(request.args.get("max_layout_extents", 50000))
        return jsonify(
            simulate_interleave(
                scan_id,
                sequential_mib_s=sequential_mib_s,
                seek_ms=seek_ms,
                target_seek_overhead=target_seek_overhead,
                max_layout_extents=max_layout_extents,
            )
        )
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
