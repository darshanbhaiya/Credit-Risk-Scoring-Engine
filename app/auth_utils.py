"""
auth_utils.py
-------------
JWT authentication helpers for Flask.
Uses PyJWT for token encoding/decoding and bcrypt for password hashing.

Role hierarchy:
  user     — can submit applications and view own results
  analyst  — read-only access to all applications; can override MANUAL REVIEW
  admin    — full access including user management
"""

import os
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Callable

import bcrypt
import jwt
from flask import g, jsonify, request

from database import get_db

SECRET_KEY: str = os.getenv("JWT_SECRET", "change-me-in-production")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(subject: str) -> str:
    """Create a signed JWT with the given subject (email) and 8-hour expiry."""
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": subject, "exp": expires_at},
        SECRET_KEY,
        algorithm=ALGORITHM,
    )


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ---------------------------------------------------------------------------
# Internal token resolver (shared by all decorators)
# ---------------------------------------------------------------------------

def _resolve_user() -> dict | None:
    """
    Reads the Bearer token from the Authorization header, decodes it,
    and returns the matching user row from the DB, or None on any failure.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(token)
        email: str = payload.get("sub", "")
        if not email:
            return None
    except (jwt.PyJWTError, ValueError):
        return None

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, email, hashed_password, role, created_at "
                "FROM users WHERE email = %s",
                (email,),
            )
            row = cur.fetchone()

    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Flask route decorators
# ---------------------------------------------------------------------------

def login_required(f: Callable) -> Callable:
    """
    Validates the Bearer token and attaches the user to g.current_user.
    Any authenticated role (user / analyst / admin) is accepted.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _resolve_user()
        if user is None:
            return jsonify({"detail": "Could not validate credentials"}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def analyst_required(f: Callable) -> Callable:
    """
    Allows access only to analyst and admin roles.
    Used for read-all and override endpoints that regular users cannot reach.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _resolve_user()
        if user is None:
            return jsonify({"detail": "Could not validate credentials"}), 401
        if user["role"] not in ("analyst", "admin"):
            return jsonify({"detail": "Analyst or admin role required"}), 403
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper


def admin_required(f: Callable) -> Callable:
    """
    Allows access only to admin role.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        user = _resolve_user()
        if user is None:
            return jsonify({"detail": "Could not validate credentials"}), 401
        if user["role"] != "admin":
            return jsonify({"detail": "Admin role required"}), 403
        g.current_user = user
        return f(*args, **kwargs)
    return wrapper
