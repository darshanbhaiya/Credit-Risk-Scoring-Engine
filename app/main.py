"""
main.py
-------
Flask application factory — Credit Risk Scoring Engine.

Stack : Python · Flask · PostgreSQL (psycopg2) · XGBoost
Frontend : Jinja2 templates + vanilla HTML/CSS/JS (no React, no Node)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (one level above app/)
load_dotenv(Path(__file__).parent.parent / ".env")

from flask import Flask, jsonify, redirect, render_template, url_for
from flask_cors import CORS

from database import execute_sql_file, init_pool, get_db
from auth_utils import hash_password as _hash
from routers.applications import router as applications_bp
from routers.auth import router as auth_bp
from routers.features import router as features_bp
from routers.score import router as score_bp


def _seed_admin() -> None:
    """
    Ensure a default admin account exists on every startup.
    Username: admin   Password: admin
    Only created when zero users are in the database — safe to run repeatedly.
    Change the password via Admin Panel after first login.
    """
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM users")
                if cur.fetchone()["cnt"] == 0:
                    cur.execute(
                        """
                        INSERT INTO users (email, hashed_password, role)
                        VALUES (%s, %s, 'admin')
                        """,
                        ("admin@riskengine.com", _hash("password123")),
                    )
    except Exception:
        pass  # DB not ready yet — will seed on next request


def create_app() -> Flask:
    app = Flask(__name__)

    # ── CORS (API routes only) ──────────────────────────────────────
    CORS(
        app,
        resources={r"/api/*": {"origins": os.getenv("ALLOWED_ORIGINS", "*")}},
        supports_credentials=True,
    )

    # ── PostgreSQL pool ─────────────────────────────────────────────
    init_pool()

    # ── Bootstrap schema ────────────────────────────────────────────
    schema_path = Path(__file__).parent / "sql" / "schema.sql"
    if schema_path.exists():
        execute_sql_file(str(schema_path))

    # ── Seed default admin account ───────────────────────────────────
    # Creates admin/admin on first run if no users exist.
    # Change credentials via Admin Panel → Users tab after first login.
    _seed_admin()

    # ── API blueprints ──────────────────────────────────────────────
    app.register_blueprint(auth_bp,         url_prefix="/api/auth")
    app.register_blueprint(applications_bp, url_prefix="/api/applications")
    app.register_blueprint(score_bp,        url_prefix="/api/score")
    app.register_blueprint(features_bp,     url_prefix="/api/features")

    # ── API health ──────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok", "service": "credit-risk-flask", "version": "3.0.0"})

    # ── Page routes (Jinja2 templates) ──────────────────────────────
    @app.get("/")
    def landing():
        return render_template("landing.html")

    @app.get("/login")
    def login():
        return render_template("login.html")

    @app.get("/register")
    def register():
        return render_template("register.html")

    @app.get("/dashboard")
    def dashboard():
        return render_template("dashboard.html", active="dashboard")

    @app.get("/applications/new")
    def new_application():
        return render_template("new_application.html", active="new")

    @app.get("/applications")
    def applications():
        return render_template("applications.html", active="applications")

    @app.get("/applications/<int:app_id>")
    def application_result(app_id: int):
        return render_template("results.html", active="applications")

    @app.get("/features")
    def features():
        return render_template("features.html", active="features")

    @app.get("/admin")
    def admin():
        return render_template("admin.html", active="admin")

    @app.get("/invite")
    def invite():
        return render_template("invite.html")

    return app


if __name__ == "__main__":
    flask_app = create_app()
    flask_app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
