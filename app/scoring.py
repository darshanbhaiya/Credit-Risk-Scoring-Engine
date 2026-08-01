"""
scoring.py
----------
Core credit-risk processing engine.
Loads the XGBoost model bundle, builds the feature vector from applicant
input, runs inference, computes a 300-850 risk score, and returns a
structured ScoreResult.  SHAP is used for feature attributions when available.
"""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

try:
    import shap
except Exception:
    shap = None

from schemas import ApplicantInput, ScoreResult, TopFeature
from train_model import FEATURES, LOAN_PURPOSES

MODEL_PATH = Path(__file__).with_name("model.pkl")
_MODEL_BUNDLE: dict | None = None

CLASS_LABELS = {0: "LOW", 1: "MEDIUM", 2: "HIGH"}


# ---------------------------------------------------------------------------
# Model loader (singleton)
# ---------------------------------------------------------------------------

def _load_bundle() -> dict:
    global _MODEL_BUNDLE
    if _MODEL_BUNDLE is None:
        if not MODEL_PATH.exists():
            raise RuntimeError(
                "model.pkl not found — run `python train_model.py` first."
            )
        _MODEL_BUNDLE = joblib.load(MODEL_PATH)
    return _MODEL_BUNDLE


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _applicant_frame(applicant: ApplicantInput) -> pd.DataFrame:
    purpose_key = applicant.loan_purpose.lower().replace(" ", "_")
    row = {
        "age": applicant.age,
        "annual_income": applicant.annual_income,
        "employment_years": applicant.employment_years,
        "credit_history_length": applicant.credit_history_length,
        "num_credit_accounts": applicant.num_credit_accounts,
        "debt_to_income_ratio": applicant.debt_to_income_ratio,
        "loan_amount": applicant.loan_amount,
        "loan_purpose_encoded": LOAN_PURPOSES.get(purpose_key, LOAN_PURPOSES["personal"]),
        "num_delinquencies": applicant.num_delinquencies,
        "payment_history_score": applicant.payment_history_score,
    }
    return pd.DataFrame([row], columns=FEATURES)


# ---------------------------------------------------------------------------
# Feature importance
# ---------------------------------------------------------------------------

def _fallback_impacts(frame: pd.DataFrame) -> list[TopFeature]:
    row = frame.iloc[0]
    raw = {
        "payment_history_score": round((row["payment_history_score"] - 72) / 100, 3),
        "debt_to_income_ratio": round(-row["debt_to_income_ratio"], 3),
        "num_delinquencies": round(-row["num_delinquencies"] / 8, 3),
        "credit_history_length": round(row["credit_history_length"] / 40, 3),
        "annual_income": round(min(row["annual_income"] / 250_000, 1), 3),
    }
    return [
        TopFeature(feature=name, impact=val)
        for name, val in sorted(raw.items(), key=lambda x: abs(x[1]), reverse=True)
    ]


def _shap_impacts(model, frame: pd.DataFrame, predicted_class: int) -> list[TopFeature]:
    if shap is None:
        return _fallback_impacts(frame)
    try:
        explainer = shap.TreeExplainer(model)
        values = explainer.shap_values(frame)
        class_vals = (
            values[predicted_class][0]
            if isinstance(values, list)
            else values[0, :, predicted_class]
        )
        pairs = sorted(
            zip(FEATURES, class_vals),
            key=lambda x: abs(float(x[1])),
            reverse=True,
        )[:5]
        return [TopFeature(feature=n, impact=round(float(v), 3)) for n, v in pairs]
    except Exception:
        return _fallback_impacts(frame)


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------

def score_application(applicant: ApplicantInput) -> ScoreResult:
    """
    Run the full credit-risk scoring pipeline for a single applicant.

    Returns a ScoreResult with risk_score (300-850), risk_class, confidence,
    decision, top SHAP feature attributions, and human-readable reasoning.
    """
    bundle = _load_bundle()
    model = bundle["model"]

    frame = _applicant_frame(applicant)
    probabilities: np.ndarray = model.predict_proba(frame)[0]
    predicted_class: int = int(np.argmax(probabilities))

    risk_class: str = CLASS_LABELS[predicted_class]
    confidence: float = round(float(probabilities[predicted_class]) * 100, 1)

    # ------------------------------------------------------------------
    # FICO-style score: base anchored to predicted class, then adjusted
    # using all relevant applicant features (not just 3).
    #
    # Factors and their approximate real-world FICO weight:
    #   payment_history_score  ~35% — most impactful, centred at 75
    #   debt_to_income_ratio   ~30% — higher DTI = more pressure
    #   num_delinquencies      — direct negative mark
    #   credit_history_length  ~15% — longer = more trustworthy, capped at 20 yrs
    #   num_credit_accounts    ~10% — depth of credit, capped at 10 accounts
    #   loan_amount / income   — affordability: large loans vs income = risk
    #   employment_years       — stability proxy, capped at 15 yrs
    # ------------------------------------------------------------------
    base_score = {0: 755, 1: 635, 2: 515}[predicted_class]

    # Loan-to-income ratio — penalise applicants borrowing far beyond their means
    loan_to_income = applicant.loan_amount / max(applicant.annual_income, 1)

    adjustment = int(
        # Payment behaviour (most impactful)
        (applicant.payment_history_score - 75) * 1.3

        # Debt burden
        - applicant.debt_to_income_ratio * 95

        # Delinquency history
        - applicant.num_delinquencies * 18

        # Credit history depth — reward up to 20 years, +1.5 pts/yr
        + min(applicant.credit_history_length, 20) * 1.5

        # Breadth of credit — reward up to 10 accounts, +1.2 pts/account
        + min(applicant.num_credit_accounts, 10) * 1.2

        # Affordability — penalise high loan-to-income ratio
        - loan_to_income * 40

        # Employment stability — reward up to 15 years, +0.8 pts/yr
        + min(applicant.employment_years, 15) * 0.8
    )

    risk_score = int(np.clip(base_score + adjustment, 300, 850))

    # ------------------------------------------------------------------
    # Decision logic — explicit mapping for every meaningful case:
    #
    #   LOW  + score >= 690            → APPROVED
    #          (strong profile, model and score agree)
    #
    #   LOW  + score 580–689           → MANUAL REVIEW
    #          (model says low risk but score is borderline — underwriter check)
    #
    #   MEDIUM + score >= 680          → MANUAL REVIEW
    #          (model is uncertain but score is reasonable — give benefit of doubt)
    #
    #   MEDIUM + score < 680           → MANUAL REVIEW
    #          (mixed signals — underwriter required either way)
    #
    #   HIGH + any score               → REJECTED
    #          (model flags high default probability)
    #
    #   ANY  + score < 580             → REJECTED
    #          (score floor: too risky regardless of class, safety net for
    #           edge cases where class and score disagree)
    # ------------------------------------------------------------------
    if risk_class == "LOW" and risk_score >= 690:
        decision = "APPROVED"
        reasoning = (
            "Strong repayment profile, manageable debt burden, and solid "
            "credit history indicate a low probability of default."
        )
    elif risk_class == "HIGH" or risk_score < 580:
        # HIGH class always rejected; score < 580 is a hard floor safety net
        # (catches borderline MEDIUM applicants with very poor financials)
        decision = "REJECTED"
        reasoning = (
            "Default risk is elevated based on credit behaviour and "
            "affordability signals — DTI, delinquencies, or payment history."
        )
    elif risk_class == "LOW" and risk_score < 690:
        # Model says LOW but score is 580–689: borderline, needs review
        decision = "MANUAL REVIEW"
        reasoning = (
            "Model indicates low risk, but the adjusted credit score sits in "
            "the borderline band (580–689). An underwriter should verify "
            "income stability and debt obligations before approval."
        )
    else:
        # MEDIUM risk class with score >= 580: mixed signals, always review
        decision = "MANUAL REVIEW"
        reasoning = (
            "Applicant presents mixed risk signals — the model indicates "
            "moderate default probability. Underwriter review is required "
            "before a final credit decision can be issued."
        )

    return ScoreResult(
        risk_score=risk_score,
        risk_class=risk_class,
        confidence=confidence,
        decision=decision,
        top_features=_shap_impacts(model, frame, predicted_class),
        reasoning=reasoning,
    )
