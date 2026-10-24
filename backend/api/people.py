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
from backend.vision.subjects import (
    SubjectEngineUnavailable,
    analyze_subjects,
    capabilities as subject_capabilities,
    search_subjects,
    top_subjects,
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



@bp.get("/subjects/capabilities")
def get_subject_capabilities():
    return jsonify(subject_capabilities())


@bp.post("/subjects/analyze/<int:scan_id>")
def analyze_subject_index(scan_id: int):
    payload = request.get_json(silent=True) or {}
    try:
        raw_limit = payload.get("limit")
        return jsonify(
            analyze_subjects(
                scan_id,
                limit=None if raw_limit in {None, ""} else min(max(1, int(raw_limit)), 100_000),
                top_k=min(max(1, int(payload.get("top_k", 8))), 50),
                min_score=max(0.0, min(1.0, float(payload.get("min_score", 0.03)))),
            )
        )
    except (SubjectEngineUnavailable, TypeError, ValueError, OSError) as exc:
        return jsonify({"error": "subject_analysis_failed", "message": str(exc)}), 400


@bp.get("/subjects/search")
def subject_search():
    try:
        scan_id = int(request.args["scan_id"])
        query = str(request.args.get("q") or "")
        return jsonify(
            {
                "scan_id": scan_id,
                "query": query,
                "photos": search_subjects(
                    scan_id,
                    query,
                    min_score=float(request.args.get("min_score", "0.05")),
                    limit=int(request.args.get("limit", "200")),
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_subject_search", "message": str(exc)}), 400


@bp.get("/subjects/top")
def subject_top():
    try:
        scan_id = int(request.args["scan_id"])
        return jsonify(
            {
                "scan_id": scan_id,
                "subjects": top_subjects(
                    scan_id,
                    limit=int(request.args.get("limit", "50")),
                ),
            }
        )
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": "invalid_subject_query", "message": str(exc)}), 400
