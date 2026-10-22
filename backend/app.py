from __future__ import annotations

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from backend.api.analytics import bp as analytics_bp
from backend.api.content import bp as content_bp
from backend.api.disks import bp as disks_bp
from backend.api.files import bp as files_bp
from backend.api.scans import bp as scans_bp
from backend.api.storage import bp as storage_bp
from backend.api.storage_lab import bp as storage_lab_bp
from backend.api.vault import bp as vault_bp
from backend.config import settings
from backend.core.database import init_database
from backend.storage_brain.service import ensure_defaults


VERSION = "0.3.0"


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, origins=["http://127.0.0.1:5173", "http://localhost:5173"])

    for blueprint in (
        disks_bp,
        scans_bp,
        analytics_bp,
        storage_bp,
        files_bp,
        content_bp,
        vault_bp,
        storage_lab_bp,
    ):
        app.register_blueprint(blueprint)

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "application": "DiskShell",
                "version": VERSION,
                "python_only": True,
                "safety": {
                    "file_writes": settings.allow_file_writes,
                    "vault_writes": settings.allow_vault_writes,
                    "disk_writes": settings.allow_disk_writes,
                    "extent_moves": settings.allow_extent_moves,
                },
            }
        )

    frontend_dist = settings.project_root / "frontend" / "dist"

    @app.get("/")
    def root():
        if (frontend_dist / "index.html").exists():
            return send_from_directory(frontend_dist, "index.html")
        return jsonify(
            {
                "application": "DiskShell",
                "version": VERSION,
                "message": "Backend is running. Build frontend with: cd frontend; npm install; npm run build",
                "health": "/api/health",
            }
        )

    @app.get("/<path:path>")
    def frontend(path: str):
        candidate = frontend_dist / path
        if frontend_dist.exists() and candidate.exists() and candidate.is_file():
            return send_from_directory(frontend_dist, path)
        if (frontend_dist / "index.html").exists():
            return send_from_directory(frontend_dist, "index.html")
        return jsonify({"error": "not_found"}), 404

    return app


app = create_app()


def main() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_database()
    ensure_defaults()
    app.run(host=settings.host, port=settings.port, debug=settings.debug, use_reloader=False)


if __name__ == "__main__":
    main()
