"""
routers/auth.py
---------------
Flask Blueprint: /auth
Endpoints:
  POST  /api/auth/register
  POST  /api/auth/login
  GET   /api/auth/me
  POST  /api/auth/invite              — admin generates a single-use invite token
  POST  /api/auth/register-analyst    — analyst self-registers with invite token
  GET   /api/auth/users               — admin lists all users
  PATCH /api/auth/users/<id>/role     — admin changes a user's role
"""

import json
import os
import secrets

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from auth_utils import (
    admin_required,
    create_access_token,
    hash_password,
    login_required,
    verify_password,
)
from database import get_db
from schemas import Token, UserCreate, UserLogin, UserRead

router = Blueprint("auth", __name__)

# In-memory invite token store  {token: {"email": str, "role": str}}
# In production replace with a DB table with expiry.
_invite_tokens: dict[str, dict] = {}


def _write_audit(conn, event_type: str, user_id, payload: dict):
    """Append one immutable audit log row."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ua = request.headers.get("User-Agent", "")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log
                (event_type, user_id, application_id, ip_address, user_agent, payload)
            VALUES (%s, %s, NULL, %s, %s, %s::jsonb)
            """,
            (event_type, user_id, ip, ua, json.dumps(payload)),
        )


# ---------------------------------------------------------------------------
# Standard register / login / me
# ---------------------------------------------------------------------------

@router.post("/register")
def register():
    try:
        payload = UserCreate.model_validate(request.get_json(force=True) or {})
    except ValidationError as exc:
        return jsonify({"detail": exc.errors()}), 422

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (payload.email,))
            if cur.fetchone():
                return jsonify({"detail": "Email is already registered"}), 409

            # Use INSERT ... ON CONFLICT to atomically handle the race condition
            # where two requests check simultaneously and both see count == 0.
            # First registered user (id=1 due to SERIAL) becomes admin.
            cur.execute("SELECT COUNT(*) AS cnt FROM users")
            count = cur.fetchone()["cnt"]
            role = "admin" if count == 0 else "user"

            cur.execute(
                """
                INSERT INTO users (email, hashed_password, role)
                VALUES (%s, %s, %s)
                RETURNING id, email, role, created_at
                """,
                (payload.email, hash_password(payload.password), role),
            )
            row = cur.fetchone()

        _write_audit(conn, "USER_REGISTERED", row["id"], {
            "email": payload.email,
            "role":  role,
        })

    return jsonify(UserRead(**row).model_dump(mode="json")), 201


@router.post("/login")
def login():
    try:
        payload = UserLogin.model_validate(request.get_json(force=True) or {})
    except ValidationError as exc:
        return jsonify({"detail": exc.errors()}), 422

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, hashed_password, role, created_at "
                "FROM users WHERE email = %s",
                (payload.email,),
            )
            row = cur.fetchone()

    if row is None or not verify_password(payload.password, row["hashed_password"]):
        return jsonify({"detail": "Invalid email or password"}), 401

    token = Token(access_token=create_access_token(row["email"]))

    with get_db() as conn:
        _write_audit(conn, "USER_LOGIN", row["id"], {
            "email": row["email"],
            "role":  row["role"],
        })

    return jsonify(token.model_dump()), 200


@router.get("/me")
@login_required
def me():
    user = g.current_user
    return jsonify(
        UserRead(
            id=user["id"],
            email=user["email"],
            role=user["role"],
            created_at=user["created_at"],
        ).model_dump(mode="json")
    ), 200


# ---------------------------------------------------------------------------
# Admin: list all users
# ---------------------------------------------------------------------------

@router.get("/users")
@admin_required
def list_users():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, role, created_at FROM users ORDER BY created_at DESC"
            )
            rows = cur.fetchall()

    return jsonify([
        UserRead(
            id=r["id"],
            email=r["email"],
            role=r["role"],
            created_at=r["created_at"],
        ).model_dump(mode="json")
        for r in rows
    ]), 200


# ---------------------------------------------------------------------------
# Admin: change a user's role
# ---------------------------------------------------------------------------

@router.patch("/users/<int:user_id>/role")
@admin_required
def change_role(user_id: int):
    data = request.get_json(force=True) or {}
    new_role = data.get("role", "").lower()

    if new_role not in ("user", "analyst", "admin"):
        return jsonify({"detail": "role must be user | analyst | admin"}), 422

    admin = g.current_user
    if user_id == admin["id"] and new_role != "admin":
        return jsonify({"detail": "Admins cannot demote themselves"}), 409

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, email, role FROM users WHERE id = %s", (user_id,))
            target = cur.fetchone()
            if target is None:
                return jsonify({"detail": "User not found"}), 404

            old_role = target["role"]
            cur.execute(
                "UPDATE users SET role = %s WHERE id = %s "
                "RETURNING id, email, role, created_at",
                (new_role, user_id),
            )
            updated = cur.fetchone()

        _write_audit(conn, "ROLE_CHANGED", admin["id"], {
            "target_user_id":    user_id,
            "target_email":      target["email"],
            "old_role":          old_role,
            "new_role":          new_role,
            "changed_by_email":  admin["email"],
        })

    return jsonify(UserRead(**updated).model_dump(mode="json")), 200


# ---------------------------------------------------------------------------
# Admin: generate a single-use invite link for analyst registration
# ---------------------------------------------------------------------------

@router.post("/invite")
@admin_required
def create_invite():
    data     = request.get_json(force=True) or {}
    email    = data.get("email", "").strip().lower()
    role     = data.get("role", "analyst").lower()

    if role not in ("analyst", "user"):
        return jsonify({"detail": "Invite role must be analyst or user"}), 422

    if not email or "@" not in email:
        return jsonify({"detail": "A valid target email is required"}), 422

    # Check email not already registered
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                return jsonify({"detail": "That email is already registered"}), 409

    token = secrets.token_urlsafe(32)
    _invite_tokens[token] = {"email": email, "role": role}

    invite_url = f"{request.host_url.rstrip('/')}/invite?token={token}"

    with get_db() as conn:
        _write_audit(conn, "INVITE_CREATED", g.current_user["id"], {
            "invited_email": email,
            "role":          role,
            "created_by":    g.current_user["email"],
        })

    return jsonify({
        "token":      token,
        "invite_url": invite_url,
        "email":      email,
        "role":       role,
    }), 201


# ---------------------------------------------------------------------------
# Analyst self-registration via invite token
# ---------------------------------------------------------------------------

@router.post("/register-analyst")
def register_analyst():
    data  = request.get_json(force=True) or {}
    token = data.get("token", "").strip()
    password = data.get("password", "")

    if not token or token not in _invite_tokens:
        return jsonify({"detail": "Invalid or expired invite token"}), 401

    invite   = _invite_tokens[token]
    email    = invite["email"]
    role     = invite["role"]

    if len(password) < 8:
        return jsonify({"detail": "Password must be at least 8 characters"}), 422

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                del _invite_tokens[token]
                return jsonify({"detail": "Email is already registered"}), 409

            cur.execute(
                """
                INSERT INTO users (email, hashed_password, role)
                VALUES (%s, %s, %s)
                RETURNING id, email, role, created_at
                """,
                (email, hash_password(password), role),
            )
            row = cur.fetchone()

        _write_audit(conn, "ANALYST_REGISTERED", row["id"], {
            "email": email,
            "role":  role,
        })

    # Consume the token — single use
    del _invite_tokens[token]

    return jsonify(UserRead(**row).model_dump(mode="json")), 201


# ---------------------------------------------------------------------------
# Validate an invite token (used by the invite page to pre-fill email)
# ---------------------------------------------------------------------------

@router.get("/invite/<token>")
def validate_invite(token: str):
    if token not in _invite_tokens:
        return jsonify({"detail": "Invalid or expired invite token"}), 401
    invite = _invite_tokens[token]
    return jsonify({"email": invite["email"], "role": invite["role"]}), 200
