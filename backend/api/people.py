from __future__ import annotations

import io

from flask import Blueprint, jsonify, request, send_file

from backend.people.service import (
    PeopleEngineUnavailable,
    analyze_scan,
    capabilities,
    face_thumbnail,
    list_people,
    person_photos,
    rename_person,
    similar_faces,
)


bp = Blueprint("people", __name__, url_prefix="/api/people")


@bp.get("/capabilities")
def get_capabilities():
    return jsonify(capabilities())


@bp.post("/analyze/<int:scan_id>")
def analyze(scan_id: int):
    payload = request.get_json(silent=True) or {}
    limit = payload.get("limit")
    try:
        parsed_limit = None if limit in {None, ""} else min(max(1, int(limit)), 100_000)
        return jsonify(analyze_scan(scan_id, limit=parsed_limit))
    except (PeopleEngineUnavailable, ValueError, OSError) as exc:
        return jsonify({"error": "people_analysis_failed", "message": str(exc)}), 400


@bp.get("")
def people():
    try:
        scan_id = int(request.args["scan_id"])
        return jsonify({"scan_id": scan_id, "people": list_people(scan_id)})
    except (KeyError, ValueError) as exc:
        return jsonify({"error": "invalid_scan_id", "message": str(exc)}), 400


@bp.patch("/<int:person_id>")
def rename(person_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        return jsonify(rename_person(person_id, str(payload.get("name", ""))))
    except KeyError:
        return jsonify({"error": "person_not_found"}), 404
    except ValueError as exc:
        return jsonify({"error": "invalid_name", "message": str(exc)}), 400


@bp.get("/<int:person_id>/photos")
def photos(person_id: int):
    try:
        mode = request.args.get("mode", "all")
        return jsonify({"person_id": person_id, "mode": mode, "photos": person_photos(person_id, mode)})
    except ValueError as exc:
        return jsonify({"error": "invalid_mode", "message": str(exc)}), 400


@bp.get("/faces/<int:face_id>/thumbnail")
def thumbnail(face_id: int):
    try:
        data = face_thumbnail(face_id)
    except (KeyError, FileNotFoundError, OSError, ValueError):
        return jsonify({"error": "face_not_found"}), 404
    return send_file(io.BytesIO(data), mimetype="image/jpeg", max_age=60)



@bp.get("/faces/<int:face_id>/similar")
def similar(face_id: int):
    try:
        return jsonify(
            {
                "face_id": face_id,
                "matches": similar_faces(
                    face_id,
                    limit=int(request.args.get("limit", "50")),
                    min_score=float(request.args.get("min_score", "0.35")),
                ),
            }
        )
    except KeyError:
        return jsonify({"error": "face_not_found"}), 404
    except (PeopleEngineUnavailable, TypeError, ValueError) as exc:
        return jsonify({"error": "face_similarity_failed", "message": str(exc)}), 400
