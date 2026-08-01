"""
routers/score.py
----------------
Flask Blueprint: /score
Endpoint: POST /score — standalone scoring endpoint (no persistence).
"""

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from schemas import ApplicantInput
from scoring import score_application

router = Blueprint("score", __name__)


@router.post("")
def score():
    try:
        payload = ApplicantInput.model_validate(request.get_json(force=True) or {})
    except ValidationError as exc:
        return jsonify({"detail": exc.errors()}), 422

    try:
        result = score_application(payload)
    except RuntimeError as exc:
        return jsonify({"detail": str(exc)}), 503

    return jsonify(result.model_dump()), 200
