"""
schemas.py
----------
Pydantic v2 models for request validation and response serialisation.
Used directly in Flask routes via model.model_validate(request.get_json()).
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserRead(BaseModel):
    id: int
    email: EmailStr
    role: str
    created_at: datetime

    model_config = {"from_attributes": True}


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------------------
# Scoring input
# ---------------------------------------------------------------------------

class ApplicantInput(BaseModel):
    name: str = Field(min_length=2)
    age: int = Field(ge=18, le=85)
    employment_type: str
    annual_income: float = Field(gt=0)
    employment_years: float = Field(ge=0, default=3)
    credit_history_length: float = Field(ge=0)
    num_credit_accounts: int = Field(ge=0, default=4)
    debt_to_income_ratio: float = Field(ge=0, le=1)
    existing_loans: int = Field(ge=0)
    num_delinquencies: int = Field(ge=0)
    payment_history_score: float = Field(ge=0, le=100, default=82)
    loan_amount: float = Field(gt=0)
    loan_purpose: str
    tenure: int = Field(ge=6, le=480)


# ---------------------------------------------------------------------------
# Scoring output
# ---------------------------------------------------------------------------

class TopFeature(BaseModel):
    feature: str
    impact: float


class ScoreResult(BaseModel):
    risk_score: int
    risk_class: Literal["LOW", "MEDIUM", "HIGH"]
    confidence: float
    decision: Literal["APPROVED", "REJECTED", "MANUAL REVIEW"]
    top_features: list[TopFeature]
    reasoning: str


# ---------------------------------------------------------------------------
# Application record
# ---------------------------------------------------------------------------

class ApplicationRead(BaseModel):
    id: int
    user_id: int
    applicant_data: dict[str, Any]
    score_result: dict[str, Any]
    status: str
    model_version: str = "champion-v1"
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Analyst override
# ---------------------------------------------------------------------------

class StatusOverride(BaseModel):
    """
    Request body for PATCH /api/applications/<id>/status.
    Only analyst and admin roles may call this endpoint.
    Allows moving a MANUAL REVIEW application to APPROVED or REJECTED
    with a mandatory analyst note for the audit trail.
    """
    new_status: Literal["APPROVED", "REJECTED"]
    note: str = Field(min_length=5, max_length=1000)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class AuditLogRead(BaseModel):
    id: int
    event_type: str
    user_id: Optional[int]
    application_id: Optional[int]
    ip_address: Optional[str]
    user_agent: Optional[str]
    payload: dict[str, Any]
    created_at: datetime
    user_email: Optional[str] = None   # joined from users table

    model_config = {"from_attributes": True}
