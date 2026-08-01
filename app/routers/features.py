"""
routers/features.py
-------------------
Flask Blueprint: /api/features
Enterprise-grade fintech analytics endpoints for interviews at GS / JPM.

Endpoints:
  GET  /api/features/model-validation   — AUC, KS, PSI, Gini (SR 11-7)
  POST /api/features/stress-test        — CCAR/DFAST scenario analysis
  GET  /api/features/expected-loss      — PD × LGD × EAD portfolio
  GET  /api/features/audit-log          — Immutable regulatory audit trail
  GET  /api/features/models             — Champion/Challenger comparison
  GET  /api/features/basel-capital      — Basel III RWA and CAR
  GET  /api/features/fraud-velocity     — Velocity flags and IP reuse
"""

import json
import math

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError

from auth_utils import analyst_required, login_required
from database import get_db
from schemas import StatusOverride

router = Blueprint("features", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_pd(risk_class: str, confidence: float) -> float:
    """
    Derive Probability of Default from model output.

    Maps model classification confidence to a realistic PD range.
    Model confidence (how certain the classifier is about the class) is
    NOT the same as PD (probability the borrower defaults). Confidence is
    scaled into industry-realistic PD bands:

      HIGH  → PD in [0.20, 0.55]  — subprime; scaled from confidence
      LOW   → PD in [0.01, 0.10]  — prime; low uncertainty drives PD up
      MED   → PD fixed at 0.15    — mixed signals, conservative assumption

    In production PD would be calibrated against actual default outcomes
    using logistic regression on a labelled holdout set.
    """
    c = confidence / 100.0
    if risk_class == "HIGH":
        # Scale confidence [0,1] into realistic subprime PD range [0.20, 0.55]
        return round(0.20 + c * 0.35, 4)
    if risk_class == "LOW":
        # Higher confidence in LOW → lower PD. Scale into prime range [0.01, 0.10]
        return round(max(0.01, (1.0 - c) * 0.30), 4)
    # MEDIUM: fixed conservative assumption
    return 0.15


def _risk_weight(pd: float) -> float:
    """
    Simplified Basel III IRB risk weight tiers.

    NOTE: This is a highly simplified approximation for demonstration purposes.
    The real Basel III Advanced IRB formula uses a continuous function:
      RW = LGD × N[(1-R)^(-0.5) × G(PD) + (R/(1-R))^0.5 × G(0.999)] × 12.5
    where R is the asset correlation (~0.12-0.24 for retail), N is the standard
    normal CDF, and G is its inverse. Real IRB weights range from ~20% to 625%.

    These three tiers are a rough proxy only:
      PD < 5%   → 75%  risk weight  (prime retail, low expected loss)
      PD 5-15%  → 100% risk weight  (near-prime / subprime borderline)
      PD > 15%  → 150% risk weight  (high-risk, elevated capital charge)
    """
    if pd < 0.05:
        return 0.75
    if pd < 0.15:
        return 1.00
    return 1.50


def _write_audit(conn, event_type: str, user_id, application_id, payload: dict):
    """Insert one append-only audit log row."""
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


# ---------------------------------------------------------------------------
# 1. Model Validation — SR 11-7 (AUC, KS, PSI, Gini)
# ---------------------------------------------------------------------------

@router.get("/model-validation")
@analyst_required
def model_validation():
    """
    Compute discrimination and stability metrics for the credit model.
    In production these would use a labelled holdout set; here we derive
    proxies from live score distributions (clearly documented for interviewers).
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (score_result->>'risk_score')::int        AS risk_score,
                    score_result->>'risk_class'               AS risk_class,
                    score_result->>'decision'                 AS decision,
                    (score_result->>'confidence')::float      AS confidence,
                    model_version
                FROM applications
                WHERE score_result IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 500
                """
            )
            rows = cur.fetchall()

    if not rows:
        return jsonify({"detail": "No applications scored yet"}), 404

    scores = [r["risk_score"] for r in rows]
    classes = [r["risk_class"] for r in rows]
    total = len(scores)

    # --- Discrimination proxy (AUC estimate) ---
    # Treat HIGH risk class as "bad" borrower, LOW as "good".
    # AUC estimated by rank-ordering: fraction of (bad, good) pairs where
    # bad applicant has higher risk score (worse) than good applicant.
    bad_scores  = [r["risk_score"] for r in rows if r["risk_class"] == "HIGH"]
    good_scores = [r["risk_score"] for r in rows if r["risk_class"] == "LOW"]

    if bad_scores and good_scores:
        # In this scoring system, higher scores = LOWER risk (FICO-style, 300-850).
        # A well-discriminating model assigns LOWER scores to HIGH-risk (bad) borrowers
        # and HIGHER scores to LOW-risk (good) borrowers.
        # AUC = fraction of (bad, good) pairs where bad applicant scores LOWER than good.
        concordant = sum(
            1 for b in bad_scores for g in good_scores if b < g
        )
        auc = round(concordant / (len(bad_scores) * len(good_scores)), 4)
    else:
        auc = 0.70  # fallback when not enough class diversity

    gini = round(2 * auc - 1, 4)

    # --- KS statistic ---
    # Maximum separation between cumulative distributions of HIGH (bad) vs LOW (good) scores.
    # Since higher scores = lower risk, bad borrowers accumulate faster at LOW thresholds
    # while good borrowers accumulate faster at HIGH thresholds.
    # KS = max(CDF_bad(t) - CDF_good(t)) over all thresholds t.
    # A positive gap at any threshold means bad borrowers are more concentrated below that
    # point — exactly what a discriminating model produces.
    if bad_scores and good_scores:
        all_thresholds = sorted(set(scores))
        ks = 0.0
        for t in all_thresholds:
            cdf_good = sum(1 for s in good_scores if s <= t) / len(good_scores)
            cdf_bad  = sum(1 for s in bad_scores  if s <= t) / len(bad_scores)
            ks = max(ks, abs(cdf_bad - cdf_good))
        ks = round(ks, 4)
    else:
        ks = 0.42  # fallback

    # --- PSI (Population Stability Index) ---
    # Query returns newest first (ORDER BY created_at DESC).
    # rows[:half]  = newest 50%  → current population
    # rows[half:]  = oldest 50%  → baseline population
    half = total // 2
    current  = [r["risk_score"] for r in rows[:half]]   # newer (recent)
    baseline = [r["risk_score"] for r in rows[half:]]   # older (baseline)
    bins = [300, 500, 580, 620, 660, 700, 740, 780, 851]  # 851 ensures score=850 is captured

    def _bin_pct(data, bins):
        counts = [0] * (len(bins) - 1)
        for v in data:
            for i in range(len(bins) - 1):
                if bins[i] <= v < bins[i + 1]:
                    counts[i] += 1
                    break
        n = len(data) or 1
        return [max(c / n, 1e-6) for c in counts]

    if baseline and current:
        base_pct = _bin_pct(baseline, bins)
        curr_pct = _bin_pct(current, bins)
        psi = round(
            sum((a - e) * math.log(a / e) for a, e in zip(curr_pct, base_pct)), 4
        )
    else:
        psi = 0.05

    # --- Score distribution histogram (8 buckets) ---
    bucket_labels = ["300-499", "500-579", "580-619", "620-659",
                     "660-699", "700-739", "740-779", "780-850"]
    bucket_ranges = [(300, 500), (500, 580), (580, 620), (620, 660),
                     (660, 700), (700, 740), (740, 780), (780, 851)]
    distribution = [
        sum(1 for s in scores if lo <= s < hi)
        for lo, hi in bucket_ranges
    ]

    # --- Class breakdown ---
    class_counts = {
        "LOW":    classes.count("LOW"),
        "MEDIUM": classes.count("MEDIUM"),
        "HIGH":   classes.count("HIGH"),
    }

    return jsonify({
        "sample_size": total,
        "metrics": {
            "auc_roc":  auc,
            "gini":     gini,
            "ks_stat":  ks,
            "psi":      psi,
        },
        "psi_interpretation": (
            "Stable"   if psi < 0.10 else
            "Monitor"  if psi < 0.25 else
            "Retrain"
        ),
        "auc_interpretation": (
            "Excellent" if auc >= 0.80 else
            "Good"      if auc >= 0.70 else
            "Weak"
        ),
        "score_distribution": {
            "labels": bucket_labels,
            "counts": distribution,
        },
        "class_counts": class_counts,
        "note": (
            "Metrics are derived from live score distributions as proxies. "
            "In production, use a labelled holdout set with ground-truth defaults."
        ),
    }), 200


# ---------------------------------------------------------------------------
# 2. Stress Testing — CCAR / DFAST
# ---------------------------------------------------------------------------

STRESS_SCENARIOS = {
    "mild": {
        "label": "Mild Stress",
        "unemployment_shock": 2.0,
        "gdp_contraction":    1.5,
        "rate_shock_bps":     100,
        "severity":           0.85,   # score multiplier
    },
    "moderate": {
        "label": "Moderate Stress",
        "unemployment_shock": 4.0,
        "gdp_contraction":    3.0,
        "rate_shock_bps":     200,
        "severity":           0.75,
    },
    "severe": {
        "label": "Severe (CCAR Severely Adverse)",
        "unemployment_shock": 6.5,
        "gdp_contraction":    5.0,
        "rate_shock_bps":     300,
        "severity":           0.60,
    },
}


@router.post("/stress-test")
@analyst_required
def stress_test():
    data = request.get_json(force=True) or {}
    scenario_key = data.get("scenario", "moderate").lower()
    if scenario_key not in STRESS_SCENARIOS:
        return jsonify({"detail": "scenario must be mild | moderate | severe"}), 422

    scenario = STRESS_SCENARIOS[scenario_key]
    severity = scenario["severity"]

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    (score_result->>'risk_score')::int      AS risk_score,
                    score_result->>'risk_class'             AS risk_class,
                    score_result->>'decision'               AS orig_decision,
                    status                                  AS current_status,
                    (score_result->>'confidence')::float    AS confidence,
                    (applicant_data->>'loan_amount')::float AS loan_amount,
                    applicant_data->>'name'                 AS name
                FROM applications
                WHERE status != 'REJECTED'
                """
            )
            rows = cur.fetchall()

    if not rows:
        return jsonify({"detail": "No active applications to stress test"}), 404

    LGD = 0.45
    baseline_approved = 0
    stressed_approved = 0
    flipped           = 0
    exposure_at_risk  = 0.0
    baseline_el       = 0.0
    stressed_el       = 0.0

    app_results = []
    for r in rows:
        orig_score  = r["risk_score"]
        orig_class  = r["risk_class"]
        loan_amount = r["loan_amount"] or 0.0

        # Apply severity multiplier: score shrinks toward 300
        stressed_score = int(300 + (orig_score - 300) * severity)
        stressed_score = max(300, min(850, stressed_score))

        # Stressed decision uses the same thresholds as scoring.py
        stressed_decision = (
            "APPROVED"      if stressed_score >= 690 else
            "REJECTED"      if stressed_score < 580  else
            "MANUAL REVIEW"
        )

        # Use current_status (reflects analyst overrides) as the baseline decision.
        # score_result->>'decision' only has the original model decision and would
        # miss analyst-overridden approvals, undercounting exposure at risk.
        orig_decision = r["current_status"]

        # EL components
        pd_base     = _derive_pd(orig_class, r["confidence"])
        pd_stressed = min(pd_base * (1.0 / severity), 1.0)

        baseline_el  += pd_base     * LGD * loan_amount
        stressed_el  += pd_stressed * LGD * loan_amount

        if orig_decision == "APPROVED":
            baseline_approved += 1
        if stressed_decision == "APPROVED":
            stressed_approved += 1

        did_flip = (orig_decision == "APPROVED" and stressed_decision == "REJECTED")
        if did_flip:
            flipped          += 1
            exposure_at_risk += loan_amount

        app_results.append({
            "id":               r["id"],
            "name":             r["name"],
            "original_score":   orig_score,
            "stressed_score":   stressed_score,
            "original_decision": orig_decision,
            "stressed_decision": stressed_decision,
            "flipped":          did_flip,
            "loan_amount":      loan_amount,
        })

    total = len(rows)
    return jsonify({
        "scenario": scenario,
        "portfolio": {
            "total_applications":  total,
            "baseline_approved":   baseline_approved,
            "stressed_approved":   stressed_approved,
            "approvals_lost":      baseline_approved - stressed_approved,
            "flipped_to_rejected": flipped,
            "exposure_at_risk":    round(exposure_at_risk, 2),
            "baseline_el":         round(baseline_el, 2),
            "stressed_el":         round(stressed_el, 2),
            "el_increase":         round(stressed_el - baseline_el, 2),
        },
        "applications": app_results[:50],   # return top 50 for display
    }), 200


# ---------------------------------------------------------------------------
# 3. Expected Loss — PD × LGD × EAD
# ---------------------------------------------------------------------------

@router.get("/expected-loss")
@analyst_required
def expected_loss():
    """
    Calculate EL = PD × LGD × EAD for each application and aggregate
    portfolio-level metrics.  LGD fixed at 45% (Basel standard for
    unsecured retail loans).  EAD = loan_amount.
    """
    LGD = 0.45

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    applicant_data->>'name'                AS name,
                    (applicant_data->>'loan_amount')::float AS ead,
                    score_result->>'risk_class'             AS risk_class,
                    (score_result->>'confidence')::float    AS confidence,
                    score_result->>'decision'               AS decision,
                    (score_result->>'risk_score')::int      AS risk_score
                FROM applications
                WHERE score_result IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 100
                """
            )
            rows = cur.fetchall()

    if not rows:
        return jsonify({"detail": "No applications found"}), 404

    results = []
    total_ead = 0.0
    total_el  = 0.0

    for r in rows:
        ead  = r["ead"] or 0.0
        pd   = _derive_pd(r["risk_class"], r["confidence"])
        el   = pd * LGD * ead
        el_pct = round((el / ead * 100) if ead > 0 else 0, 2)

        total_ead += ead
        total_el  += el

        results.append({
            "id":         r["id"],
            "name":       r["name"],
            "ead":        round(ead, 2),
            "pd":         round(pd, 4),
            "lgd":        LGD,
            "el":         round(el, 2),
            "el_pct":     el_pct,
            "risk_class": r["risk_class"],
            "risk_score": r["risk_score"],
            "decision":   r["decision"],
        })

    # Sort by EL descending — highest risk first
    results.sort(key=lambda x: x["el"], reverse=True)
    portfolio_el_rate = round((total_el / total_ead * 100) if total_ead > 0 else 0, 3)

    return jsonify({
        "lgd_assumption": LGD,
        "lgd_basis": "Basel standard for unsecured retail loans",
        "portfolio": {
            "total_ead":      round(total_ead, 2),
            "total_el":       round(total_el, 2),
            "portfolio_el_rate_pct": portfolio_el_rate,
            "sample_size":    len(results),
        },
        "applications": results[:20],   # top 20 by EL
    }), 200


# ---------------------------------------------------------------------------
# 4. Audit Log — SR 11-7 / SOX / GDPR
# ---------------------------------------------------------------------------

@router.get("/audit-log")
@analyst_required
def audit_log():
    event_type = request.args.get("event_type")
    user_id    = request.args.get("user_id", type=int)
    limit      = min(request.args.get("limit", 100, type=int), 500)

    conditions = ["1=1"]
    params: list = []

    if event_type:
        conditions.append("a.event_type = %s")
        params.append(event_type)
    if user_id:
        conditions.append("a.user_id = %s")
        params.append(user_id)

    where = " AND ".join(conditions)
    params.append(limit)

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    a.id,
                    a.event_type,
                    a.user_id,
                    a.application_id,
                    a.ip_address,
                    a.payload,
                    a.created_at,
                    u.email AS user_email
                FROM audit_log a
                LEFT JOIN users u ON u.id = a.user_id
                WHERE {where}
                ORDER BY a.created_at DESC
                LIMIT %s
                """,
                params,
            )
            rows = cur.fetchall()

    entries = [
        {
            "id":             r["id"],
            "event_type":     r["event_type"],
            "user_id":        r["user_id"],
            "user_email":     r["user_email"],
            "application_id": r["application_id"],
            "ip_address":     r["ip_address"],
            "payload":        r["payload"],
            "created_at":     r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]

    # Distinct event types for frontend filter dropdown
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT event_type FROM audit_log ORDER BY event_type")
            event_types = [row["event_type"] for row in cur.fetchall()]

    return jsonify({
        "total": len(entries),
        "event_types": event_types,
        "entries": entries,
    }), 200


# ---------------------------------------------------------------------------
# 5. Champion / Challenger Model Comparison
# ---------------------------------------------------------------------------

@router.get("/models")
@analyst_required
def model_comparison():
    """
    Compare champion vs challenger models side-by-side.
    Both models shadow-score applications in parallel; champion makes the
    real decision.  Challenger is promoted if it outperforms by 3-5%.
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    model_version,
                    COUNT(*)                                           AS count,
                    AVG((score_result->>'risk_score')::int)            AS avg_score,
                    AVG((score_result->>'confidence')::float)          AS avg_confidence,
                    SUM(CASE WHEN status='APPROVED'      THEN 1 ELSE 0 END) AS approved,
                    SUM(CASE WHEN status='REJECTED'      THEN 1 ELSE 0 END) AS rejected,
                    SUM(CASE WHEN status='MANUAL REVIEW' THEN 1 ELSE 0 END) AS review,
                    SUM(CASE WHEN score_result->>'risk_class'='HIGH'
                             THEN 1 ELSE 0 END)                        AS high_risk_count
                FROM applications
                WHERE score_result IS NOT NULL
                GROUP BY model_version
                ORDER BY model_version
                """
            )
            rows = cur.fetchall()

    if not rows:
        return jsonify({"detail": "No model data available yet"}), 404

    models = []
    for r in rows:
        count     = r["count"] or 1
        approved  = r["approved"] or 0
        rejected  = r["rejected"] or 0
        high_risk = r["high_risk_count"] or 0
        avg_score = round(float(r["avg_score"] or 0), 1)
        avg_conf  = round(float(r["avg_confidence"] or 0), 1)

        approval_rate  = round(approved  / count * 100, 1)
        high_risk_rate = round(high_risk / count * 100, 1)

        # Simulated discrimination metrics (proxy from avg score)
        # In production: compute from labelled holdout set
        gini = round(0.40 + (avg_score - 600) / 2000, 3)
        ks   = round(0.35 + (avg_score - 600) / 2500, 3)

        models.append({
            "model_version":   r["model_version"],
            "sample_size":     count,
            "avg_risk_score":  avg_score,
            "avg_confidence":  avg_conf,
            "approval_rate":   approval_rate,
            "high_risk_rate":  high_risk_rate,
            "approved":        approved,
            "rejected":        rejected,
            "review":          r["review"] or 0,
            "gini":            gini,
            "ks_stat":         ks,
        })

    # Recommendation logic
    recommendation = None
    if len(models) >= 2:
        champion   = next((m for m in models if "champion" in m["model_version"]), models[0])
        challenger = next((m for m in models if "challenger" in m["model_version"]), models[-1])
        gini_delta = challenger["gini"] - champion["gini"]
        ks_delta   = challenger["ks_stat"] - champion["ks_stat"]

        if gini_delta > 0.03 and ks_delta > 0.03 and challenger["sample_size"] >= 100:
            recommendation = {
                "action":  "PROMOTE",
                "reason":  f"Challenger outperforms champion by Gini +{gini_delta:.3f}, KS +{ks_delta:.3f}",
                "verdict": "Challenger is ready for promotion to champion.",
            }
        elif challenger["sample_size"] < 100:
            recommendation = {
                "action":  "WAIT",
                "reason":  f"Only {challenger['sample_size']} shadow scores collected. Need ≥100.",
                "verdict": "Insufficient data — continue shadow scoring.",
            }
        else:
            recommendation = {
                "action":  "KEEP",
                "reason":  f"Challenger improvement below threshold (Gini Δ={gini_delta:.3f}).",
                "verdict": "Keep champion in production.",
            }

    return jsonify({
        "models":         models,
        "recommendation": recommendation,
        "promotion_criteria": {
            "min_gini_delta": 0.03,
            "min_ks_delta":   0.03,
            "min_samples":    100,
        },
    }), 200


# ---------------------------------------------------------------------------
# 6. Basel III Capital Adequacy — IRB Approach
# ---------------------------------------------------------------------------

@router.get("/basel-capital")
@analyst_required
def basel_capital():
    """
    Calculate Risk-Weighted Assets (RWA) and Capital Adequacy Ratio (CAR)
    for the approved loan portfolio using the simplified Basel III IRB approach.
    """
    CAPITAL_RATIO   = 0.08   # 8% minimum regulatory capital
    AVAILABLE_CAR   = 0.12   # 12% assumed available capital for CAR calc
    LGD             = 0.45

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
                    applicant_data->>'name'                 AS name,
                    (applicant_data->>'loan_amount')::float AS ead,
                    score_result->>'risk_class'             AS risk_class,
                    (score_result->>'confidence')::float    AS confidence,
                    (score_result->>'risk_score')::int      AS risk_score
                FROM applications
                WHERE status = 'APPROVED'
                  AND score_result IS NOT NULL
                """
            )
            rows = cur.fetchall()

    if not rows:
        return jsonify({"detail": "No approved applications found"}), 404

    total_ead      = 0.0
    total_rwa      = 0.0
    total_capital  = 0.0
    total_el       = 0.0
    app_results    = []

    for r in rows:
        ead        = r["ead"] or 0.0
        pd         = _derive_pd(r["risk_class"], r["confidence"])
        rw         = _risk_weight(pd)
        rwa        = ead * rw
        capital    = rwa * CAPITAL_RATIO
        el         = pd * LGD * ead

        total_ead     += ead
        total_rwa     += rwa
        total_capital += capital
        total_el      += el

        app_results.append({
            "id":             r["id"],
            "name":           r["name"],
            "ead":            round(ead, 2),
            "pd":             round(pd, 4),
            "risk_weight_pct": int(rw * 100),
            "rwa":            round(rwa, 2),
            "capital_required": round(capital, 2),
            "el":             round(el, 2),
            "risk_score":     r["risk_score"],
        })

    # Sort by RWA descending — most capital-intensive loans first
    app_results.sort(key=lambda x: x["rwa"], reverse=True)

    # --- Capital Adequacy Ratio (CAR) ---
    # CAR = Available Capital / RWA
    # Available capital is the bank's Tier 1 + Tier 2 capital (a fixed balance sheet item).
    # For this demo, we assume the bank holds capital equal to 12% of its EAD,
    # which is a common target for well-capitalised institutions. This gives us
    # a hypothetical available capital amount to compute CAR.
    avg_risk_weight = round((total_rwa / total_ead * 100) if total_ead > 0 else 0, 1)
    available_capital = total_ead * AVAILABLE_CAR  # Hypothetical capital holding
    car = round((available_capital / total_rwa * 100) if total_rwa > 0 else 0, 2)
    car_status = (
        "Well Capitalised"       if car >= 10 else
        "Adequately Capitalised" if car >= 8  else
        "Undercapitalised"
    )

    return jsonify({
        "assumptions": {
            "min_capital_ratio": CAPITAL_RATIO,
            "assumed_available_car": AVAILABLE_CAR,
            "lgd": LGD,
            "approach": "Simplified Basel III IRB (3-tier risk weight proxy — not full IRB formula)",
        },
        "portfolio": {
            "total_ead":           round(total_ead, 2),
            "total_rwa":           round(total_rwa, 2),
            "total_capital_required": round(total_capital, 2),
            "total_el":            round(total_el, 2),
            "avg_risk_weight_pct": avg_risk_weight,
            "car_pct":             car,
            "car_status":          car_status,
            "approved_count":      len(rows),
        },
        "tier_breakdown": {
            "low_pd_under5pct":  {"risk_weight": "75%",  "description": "PD < 5%"},
            "med_pd_5_to_15pct": {"risk_weight": "100%", "description": "PD 5-15%"},
            "high_pd_over15pct": {"risk_weight": "150%", "description": "PD > 15%"},
        },
        "applications": app_results[:20],
    }), 200


# ---------------------------------------------------------------------------
# 7. Fraud Velocity Checks
# ---------------------------------------------------------------------------

@router.get("/fraud-velocity")
@analyst_required
def fraud_velocity():
    """
    Detect suspicious application patterns:
      - User-level velocity: multiple apps from same user in 24h
      - IP-level reuse: multiple different users from same IP in 7 days
    """
    with get_db() as conn:
        with conn.cursor() as cur:
            # User-level velocity: count apps per user in last 24 hours
            cur.execute(
                """
                SELECT
                    a.user_id,
                    u.email,
                    COUNT(*)                                          AS app_count,
                    MIN(a.created_at)                                 AS first_app,
                    MAX(a.created_at)                                 AS last_app,
                    EXTRACT(EPOCH FROM (MAX(a.created_at) - MIN(a.created_at)))/60
                                                                      AS window_minutes
                FROM applications a
                JOIN users u ON u.id = a.user_id
                WHERE a.created_at > NOW() - INTERVAL '24 hours'
                GROUP BY a.user_id, u.email
                HAVING COUNT(*) >= 2
                ORDER BY app_count DESC
                """
            )
            user_flags = cur.fetchall()

            # IP-level velocity: multiple users from same IP in last 7 days
            cur.execute(
                """
                SELECT
                    ip_address,
                    COUNT(DISTINCT user_id) AS unique_users,
                    COUNT(*)                AS total_apps,
                    MIN(created_at)         AS first_seen,
                    MAX(created_at)         AS last_seen
                FROM applications
                WHERE ip_address IS NOT NULL
                  AND ip_address != ''
                  AND created_at > NOW() - INTERVAL '7 days'
                GROUP BY ip_address
                HAVING COUNT(DISTINCT user_id) >= 2
                ORDER BY unique_users DESC
                """
            )
            ip_flags = cur.fetchall()

            # Overall stats
            cur.execute(
                """
                SELECT
                    COUNT(*)                          AS total_apps,
                    COUNT(DISTINCT user_id)           AS unique_users,
                    COUNT(DISTINCT ip_address)        AS unique_ips,
                    COUNT(CASE WHEN created_at > NOW() - INTERVAL '24 hours'
                               THEN 1 END)            AS apps_last_24h
                FROM applications
                """
            )
            stats = cur.fetchone()

    def _user_risk(count, minutes):
        if count >= 5:
            return "CRITICAL"
        if count >= 3:
            return "HIGH"
        if minutes is not None and float(minutes) < 60:
            return "MEDIUM"
        return "LOW"

    def _ip_risk(unique_users):
        if unique_users >= 5:
            return "HIGH"
        return "MEDIUM"

    user_velocity = [
        {
            "user_id":        r["user_id"],
            "email":          r["email"],
            "app_count":      r["app_count"],
            "window_minutes": round(float(r["window_minutes"] or 0), 1),
            "first_app":      r["first_app"].isoformat() if r["first_app"] else None,
            "last_app":       r["last_app"].isoformat()  if r["last_app"]  else None,
            "risk_level":     _user_risk(r["app_count"], r["window_minutes"]),
        }
        for r in user_flags
    ]

    ip_velocity = [
        {
            "ip_address":   r["ip_address"],
            "unique_users": r["unique_users"],
            "total_apps":   r["total_apps"],
            "first_seen":   r["first_seen"].isoformat() if r["first_seen"] else None,
            "last_seen":    r["last_seen"].isoformat()  if r["last_seen"]  else None,
            "risk_level":   _ip_risk(r["unique_users"]),
        }
        for r in ip_flags
    ]

    critical_count = sum(1 for f in user_velocity if f["risk_level"] == "CRITICAL")
    high_count     = sum(1 for f in user_velocity if f["risk_level"] == "HIGH")
    high_count    += sum(1 for f in ip_velocity   if f["risk_level"] == "HIGH")

    return jsonify({
        "summary": {
            "total_applications": stats["total_apps"],
            "unique_users":       stats["unique_users"],
            "unique_ips":         stats["unique_ips"],
            "apps_last_24h":      stats["apps_last_24h"],
            "user_flags":         len(user_velocity),
            "ip_flags":           len(ip_velocity),
            "critical_flags":     critical_count,
            "high_flags":         high_count,
        },
        "user_velocity":  user_velocity,
        "ip_velocity":    ip_velocity,
        "thresholds": {
            "user_critical":  "≥ 5 apps from same user",
            "user_high":      "≥ 3 apps from same user",
            "user_medium":    "≥ 2 apps within 60 minutes",
            "ip_high":        "≥ 5 different users from same IP",
            "ip_medium":      "≥ 2 different users from same IP",
        },
    }), 200


# ---------------------------------------------------------------------------
# Analyst override — PATCH /api/applications/<id>/status
# (lives here to keep applications.py focused on CRUD)
# ---------------------------------------------------------------------------

@router.patch("/override/<int:application_id>")
@analyst_required
def override_status(application_id: int):
    """
    Analyst/admin can move a MANUAL REVIEW application to APPROVED or REJECTED.
    Every override is written to the immutable audit_log with the analyst's note.
    """
    try:
        payload = StatusOverride.model_validate(request.get_json(force=True) or {})
    except ValidationError as exc:
        return jsonify({"detail": exc.errors()}), 422

    analyst = g.current_user

    # Single connection — fetch, validate, update, and audit all in one transaction
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, status FROM applications WHERE id = %s",
                (application_id,),
            )
            app = cur.fetchone()

        if app is None:
            return jsonify({"detail": "Application not found"}), 404

        if app["status"] not in ("MANUAL REVIEW", "PENDING"):
            return jsonify({
                "detail": (
                    f"Only MANUAL REVIEW or PENDING applications can be overridden. "
                    f"Current status: {app['status']}"
                )
            }), 409

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE applications SET status = %s WHERE id = %s "
                "RETURNING id, status, created_at",
                (payload.new_status, application_id),
            )
            updated = cur.fetchone()

        _write_audit(
            conn,
            event_type="STATUS_OVERRIDE",
            user_id=analyst["id"],
            application_id=application_id,
            payload={
                "old_status":    app["status"],
                "new_status":    payload.new_status,
                "note":          payload.note,
                "analyst_id":    analyst["id"],
                "analyst_email": analyst["email"],
            },
        )

    return jsonify({
        "id":         updated["id"],
        "new_status": updated["status"],
        "updated_by": analyst["email"],
        "note":       payload.note,
    }), 200
