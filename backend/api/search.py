from __future__ import annotations

from flask import Blueprint, jsonify, request

from backend.search.catalog import catalog_status, search_files


bp = Blueprint("search", __name__, url_prefix="/api/search")


def _optional_int(name: str) -> int | None:
    value = request.args.get(name)
    if value in {None, ""}:
        return None
    return int(value)


@bp.get("/files")
def files():
    try:
        return jsonify(
            search_files(
                request.args.get("q", ""),
                root=request.args.get("root"),
                category=request.args.get("category"),
                extension=request.args.get("extension"),
                min_size=_optional_int("min_size"),
                max_size=_optional_int("max_size"),
                limit=int(request.args.get("limit", "100")),
                offset=int(request.args.get("offset", "0")),
            )
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_search", "message": str(exc)}), 400


@bp.get("/status")
def status():
    return jsonify(catalog_status())
