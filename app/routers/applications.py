"""
routers/applications.py
-----------------------
Flask Blueprint: /api/applications
Endpoints:
  POST   /api/applications          — score and persist a new application
  GET    /api/applications          — list applications (all for admin/analyst, own for user)
  GET    /api/applications/<id>     — fetch a single application with auth guard
  GET    /api/applications/export   — CSV export (analyst/admin only)
"""

import csv
import io
import json

from flask import Blueprint, g, jsonify, make_response, request
from pydantic import ValidationError

from auth_utils import analyst_required, login_required
from database import get_db
from schemas import ApplicationRead, ApplicantInput
from scoring import score_application

router = Blueprint("applications", __name__)


def _serialize_app(row: dict) -> dict:
    """Convert a DB row to a JSON-serialisable dict (handle datetime)."""
    app = ApplicationRead(
        id=row["id"],
        user_id=row["user_id"],
        applicant_data=row["applicant_data"],
        score_result=row["score_result"],
        status=row["status"],
        model_version=row.get("model_version", "champion-v1"),
        created_at=row["created_at"],
    )
    return app.model_dump(mode="json")


def _write_audit(conn, event_type: str, user_id, application_id, payload: dict):
    """Append one row to the immutable audit_log."""
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ua = request.headers.get("User-Agent", "")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log
                (event_type, user_id, application_id, ip_address, user_agent, payload)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (event_type, user_id, application_id, ip, ua, json.dumps(payload)),
        )


@router.post("")
@login_required
def create_application():
    try:
        payload = ApplicantInput.model_validate(request.get_json(force=True) or {})
    except ValidationError as exc:
        return jsonify({"detail": exc.errors()}), 422

    result = score_application(payload)
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    ua = request.headers.get("User-Agent", "")

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO applications
                    (user_id, applicant_data, score_result, status,
                     model_version, ip_address, user_agent)
                VALUES (%s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
                RETURNING id, user_id, applicant_data, score_result,
                          status, model_version, created_at
                """,
                (
                    g.current_user["id"],
                    json.dumps(payload.model_dump()),
                    json.dumps(result.model_dump()),
                    result.decision,
                    "champion-v1",
                    ip,
                    ua,
                ),
            )
            row = cur.fetchone()

        # Immutable audit entry for every scoring event
        _write_audit(
            conn,
            event_type="APPLICATION_SCORED",
            user_id=g.current_user["id"],
            application_id=row["id"],
            payload={
                "decision":    result.decision,
                "risk_class":  result.risk_class,
                "risk_score":  result.risk_score,
                "confidence":  result.confidence,
                "loan_amount": payload.loan_amount,
                "applicant":   payload.name,
            },
        )

    return jsonify(_serialize_app(row)), 201


@router.get("")
@login_required
def list_applications():
    user = g.current_user
    with get_db() as conn:
        with conn.cursor() as cur:
            if user["role"] in ("admin", "analyst"):
                cur.execute(
                    "SELECT id, user_id, applicant_data, score_result, "
                    "status, model_version, created_at "
                    "FROM applications ORDER BY created_at DESC"
                )
            else:
                cur.execute(
                    "SELECT id, user_id, applicant_data, score_result, "
                    "status, model_version, created_at "
                    "FROM applications WHERE user_id = %s ORDER BY created_at DESC",
                    (user["id"],),
                )
            rows = cur.fetchall()

    return jsonify([_serialize_app(r) for r in rows]), 200


@router.get("/export")
@analyst_required
def export_csv():
    """
    Export all applications as CSV.  Analyst/admin only.
    Supports optional query params: ?decision=APPROVED&risk_class=LOW
    """
    decision_filter   = request.args.get("decision")
    risk_class_filter = request.args.get("risk_class")

    conditions = ["1=1"]
    params: list = []
    if decision_filter:
        conditions.append("status = %s")
        params.append(decision_filter.upper())
    if risk_class_filter:
        # Whitelist valid values — never interpolate user input into SQL
        allowed = {"LOW", "MEDIUM", "HIGH"}
        if risk_class_filter.upper() not in allowed:
            return jsonify({"detail": "risk_class must be LOW | MEDIUM | HIGH"}), 422
        conditions.append("score_result->>'risk_class' = %s")
        params.append(risk_class_filter.upper())

    where = " AND ".join(conditions)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    applicant_data->>'name'                  AS name,
                    (applicant_data->>'annual_income')::float AS annual_income,
                    (applicant_data->>'loan_amount')::float   AS loan_amount,
                    applicant_data->>'loan_purpose'           AS loan_purpose,
                    (score_result->>'risk_score')::int        AS risk_score,
                    score_result->>'risk_class'               AS risk_class,
                    score_result->>'decision'                 AS decision,
                    (score_result->>'confidence')::float      AS confidence,
                    status,
                    model_version,
                    created_at
                FROM applications
                WHERE """ + where + """
                ORDER BY created_at DESC
                """,
                params,
            )
            rows = cur.fetchall()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "id", "name", "annual_income", "loan_amount", "loan_purpose",
        "risk_score", "risk_class", "decision", "confidence",
        "status", "model_version", "created_at",
    ])
    writer.writeheader()
    for r in rows:
        writer.writerow({
            "id":            r["id"],
            "name":          r["name"],
            "annual_income": r["annual_income"],
            "loan_amount":   r["loan_amount"],
            "loan_purpose":  r["loan_purpose"],
            "risk_score":    r["risk_score"],
            "risk_class":    r["risk_class"],
            "decision":      r["decision"],
            "confidence":    r["confidence"],
            "status":        r["status"],
            "model_version": r["model_version"],
            "created_at":    r["created_at"],
        })

    response = make_response(output.getvalue())
    response.headers["Content-Type"]        = "text/csv"
    response.headers["Content-Disposition"] = "attachment; filename=applications.csv"
    return response


@router.get("/<int:application_id>")
@login_required
def get_application(application_id: int):
    user = g.current_user
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, applicant_data, score_result, "
                "status, model_version, created_at "
                "FROM applications WHERE id = %s",
                (application_id,),
            )
            row = cur.fetchone()

    if row is None:
        return jsonify({"detail": "Application not found"}), 404

    if user["role"] not in ("admin", "analyst") and row["user_id"] != user["id"]:
        return jsonify({"detail": "Not authorised to view this application"}), 403

    return jsonify(_serialize_app(row)), 200
