from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request

from .db import close_db, init_app_database, register_cli
from .routes import api
from .runtime_paths import data_directory


def create_app(test_config: dict | None = None) -> Flask:
    data_root = data_directory()
    app = Flask(__name__, instance_path=str(data_root), static_folder="static", static_url_path="/static")
    app.config.from_mapping(
        DATABASE=str(data_root / "student_analysis.db"),
        UPLOAD_FOLDER=str(data_root / "uploads"),
        EXPORT_FOLDER=str(data_root / "exports"),
        MAX_CONTENT_LENGTH=100 * 1024 * 1024,
        JSON_AS_ASCII=False,
    )
    if test_config:
        app.config.update(test_config)

    @app.before_request
    def require_local_request():
        # No accounts: accept only this computer and this page's origin.
        # Host validation also blocks DNS rebinding to the local listener.
        origin = request.host_url.rstrip("/")
        if (request.remote_addr not in {"127.0.0.1", "::1"}
                or urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1"}
                or request.headers.get("Origin", origin) != origin
                or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none")):
            return jsonify(error="仅允许本机页面操作"), 403

    @app.after_request
    def local_response_headers(response):
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    for key in ("UPLOAD_FOLDER", "EXPORT_FOLDER"):
        Path(app.config[key]).mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)
    app.register_blueprint(api)
    register_cli(app)
    with app.app_context():
        init_app_database()
    return app
