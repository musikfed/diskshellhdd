from __future__ import annotations

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS

from backend.api.analytics import bp as analytics_bp
from backend.api.commander import bp as commander_bp
from backend.api.content import bp as content_bp
from backend.api.diagnostics import bp as diagnostics_bp
from backend.api.disks import bp as disks_bp
from backend.api.files import bp as files_bp
from backend.api.people import bp as people_bp
from backend.api.recovery import bp as recovery_bp
from backend.api.scans import bp as scans_bp
from backend.api.security import bp as security_bp
from backend.api.storage import bp as storage_bp
from backend.api.storage_lab import bp as storage_lab_bp
from backend.api.vault import bp as vault_bp
from backend.config import settings
from backend.core.database import init_database
from backend.files.write_authorization import file_write_state
from backend.storage_brain.service import ensure_defaults


VERSION = "0.6.3"


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(app, origins=["http://127.0.0.1:5173", "http://localhost:5173"])

    for blueprint in (
        disks_bp,
        diagnostics_bp,
        scans_bp,
        analytics_bp,
        commander_bp,
        storage_bp,
        files_bp,
        people_bp,
        recovery_bp,
        security_bp,
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
                    "file_writes": file_write_state()["allowed"],
                    "file_writes_runtime": file_write_state()["runtime_enabled"],
                    "file_writes_global_override": file_write_state()["global_override"],
                    "vault_writes": settings.allow_vault_writes,
                    "disk_writes": settings.allow_disk_writes,
                    "disk_writes_global_override": settings.allow_disk_writes,
                    "selected_disk_unlocks": True,
                    "selected_disk_write_toggle": "manual_until_restart",
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

    # DiskShell may be started from an elevated Administrator/root shell for
    # raw-disk and storage operations. Never make the Flask interactive
    # debugger the default for that process. DS_DEBUG=0 uses Waitress; debug
    # mode is only for local development and should remain bound to loopback.
    if settings.debug:
        app.run(
            host=settings.host,
            port=settings.port,
            debug=True,
            use_reloader=False,
        )
        return

    from waitress import serve

    serve(app, host=settings.host, port=settings.port, threads=8)


if __name__ == "__main__":
    main()
