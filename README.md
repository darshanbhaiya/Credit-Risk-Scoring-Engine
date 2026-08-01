# Credit Risk Scoring Engine

An automated credit risk scoring system built with Python, Flask, PostgreSQL, and XGBoost. Takes a loan applicant's financial data, runs it through a trained ML model, and returns a structured credit decision with a FICO-style risk score, explainability via SHAP, and a full suite of enterprise-grade analytics used in real financial institutions.

Built to demonstrate credit risk engineering knowledge relevant to roles at Goldman Sachs, JPMorgan, and similar firms.

---

## First-Time Setup

Do this once. After setup is complete, skip to the **Running the App** section.

### Prerequisites

You need two things installed before starting:

| Tool | Version | Download |
|---|---|---|
| Python | 3.11 or higher | https://www.python.org/downloads |
| PostgreSQL | 14 or higher | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads |

When installing PostgreSQL, keep all defaults. Set a password for the `postgres` user and remember it — you will need it in Step 3.

---

### Step 1 — Create the database

Open a terminal and run:

```
psql -U postgres -c "CREATE DATABASE credit_risk;"
```

If `psql` is not recognised, add PostgreSQL to your PATH first:

```
C:\Program Files\PostgreSQL\16\bin
```

Then open a new terminal and try again.

---

### Step 2 — Configure environment variables

Open the `.env` file in the project root. Replace `YOUR_PASSWORD` with your PostgreSQL password:

```
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/credit_risk
JWT_SECRET=change-me-in-production
FLASK_DEBUG=true
PORT=5000
```

---

### Step 3 — Create a virtual environment

```
cd app
python -m venv .venv
```

Activate it:

```
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, run this once then retry:

```
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
```

---

### Step 4 — Install dependencies

```
pip install -r requirements.txt
```

---

### Step 5 — Train the ML model

```
python train_model.py
```

This generates `model.pkl`. It only needs to run once. If you ever modify `train_model.py`, run it again.

---

### Step 6 — Start the app

```
python main.py
```

On first run the app automatically creates all database tables and seeds a default admin account. Open your browser at:

```
http://localhost:5000
```

Log in with:

```
Email:    admin@riskengine.com
Password: password123
```

---

## Running the App

Once setup is done, this is all you need each time:

```
cd app
.venv\Scripts\Activate.ps1
python main.py
```

Open `http://localhost:5000` and log in.

---

## Troubleshooting

**psql is not recognised**
Add `C:\Program Files\PostgreSQL\16\bin` to your system PATH, then open a new terminal.

**Password authentication failed**
The password in `DATABASE_URL` must exactly match what you set during PostgreSQL installation.

**Activate.ps1 cannot be loaded**
Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force` once, then retry activation.

**model.pkl not found**
Run `python train_model.py` from inside the `app/` folder with the virtual environment active.

**PostgreSQL is not running**
```
Start-Service -Name postgresql*
```

**Port 5000 is already in use**
Change `PORT=5001` in `.env` and restart.

**Login fails after dropping tables**
Drop all tables, restart the app. The admin account is re-created automatically only when the users table is empty.

---

## Project Overview

### What It Does

This system takes financial and demographic information about a loan applicant and produces:

- A **risk score** on a 300–850 FICO-style scale
- A **risk classification** — LOW, MEDIUM, or HIGH
- A **lending decision** — APPROVED, REJECTED, or MANUAL REVIEW
- **Feature attributions** — the top 5 factors that drove the decision, using SHAP values
- A **human-readable explanation** of the outcome

All applications and results are stored in PostgreSQL. An analyst or admin can view the full portfolio, override flagged decisions, and run enterprise-grade analytics.

---

### How the Scoring Works

**Step 1 — Input**

14 fields are collected from the applicant:

| Field | Description |
|---|---|
| name, age, employment_type | Personal information |
| annual_income, employment_years | Income and job stability |
| credit_history_length, num_credit_accounts | Credit depth |
| debt_to_income_ratio, existing_loans | Debt burden |
| num_delinquencies, payment_history_score | Repayment behaviour |
| loan_amount, loan_purpose, tenure | Loan details |

**Step 2 — ML Classification**

10 numerical features are extracted and passed to a trained XGBoost gradient boosted tree classifier. The model outputs a probability distribution across three classes:

- Class 0 → LOW risk
- Class 1 → MEDIUM risk
- Class 2 → HIGH risk

The predicted class is whichever has the highest probability. Confidence is that probability expressed as a percentage.

**Step 3 — FICO-Style Score (300–850)**

A score is calculated on top of the ML classification using a weighted formula:

```
Base score:   LOW → 755    MEDIUM → 635    HIGH → 515

Adjustment =  (payment_history_score - 75) × 1.3
            - debt_to_income_ratio × 95
            - num_delinquencies × 18
            + min(credit_history_length, 20) × 1.5
            + min(num_credit_accounts, 10) × 1.2
            - (loan_amount / annual_income) × 40
            + min(employment_years, 15) × 0.8

Final score = base + adjustment, clamped to [300, 850]
```

**Step 4 — Decision**

| Condition | Decision |
|---|---|
| LOW risk AND score ≥ 690 | APPROVED |
| HIGH risk OR score < 580 | REJECTED |
| Everything else | MANUAL REVIEW |

**Step 5 — SHAP Explainability**

The top 5 features that most influenced the prediction are identified using SHAP TreeExplainer. Each feature gets an impact value — positive means it reduced risk, negative means it increased risk.

---

### Enterprise Analytics Features

All accessible via the **Risk Analytics** page (analyst and admin only).

**Model Validation — SR 11-7 Compliance**
Computes AUC-ROC, Gini coefficient, KS statistic, and PSI (Population Stability Index) from live scored applications. These are the standard metrics used by Goldman Sachs Model Risk Group and JPMorgan QRCS to validate credit models before production deployment.

**Stress Testing — CCAR / DFAST**
Applies macroeconomic adverse scenarios to the loan portfolio and measures how many approvals flip to rejections and by how much Expected Loss increases. Three scenarios: Mild, Moderate, and Severe (matching Federal Reserve CCAR severely adverse parameters).

**Expected Loss — PD × LGD × EAD**
Calculates the fundamental credit risk formula for every application. PD is derived from model output, LGD is fixed at 45% (Basel standard for unsecured retail), and EAD equals the loan amount. Aggregates to portfolio-level total expected loss and EL rate.

**Audit Trail — SR 11-7 / SOX / GDPR**
An immutable append-only log that records every significant event: every application scored, every login, every analyst override, every role change, every invite created. No UPDATE or DELETE is ever run against this table. Filterable by event type and user.

**Champion / Challenger**
Compares the production model (champion) against a shadow model (challenger) side by side. Tracks approval rate, high-risk rate, average score, and simulated discrimination metrics. Generates an automatic promotion recommendation based on Gini and KS delta thresholds.

**Basel III Capital Adequacy**
Calculates Risk-Weighted Assets (RWA = EAD × Risk Weight) and Capital Adequacy Ratio for the approved portfolio using simplified IRB approach risk weight tiers (75% / 100% / 150% based on PD). Flags whether the portfolio is Well Capitalised, Adequately Capitalised, or Undercapitalised against the 8% Basel minimum.

**Fraud Velocity Detection**
Detects suspicious application patterns. User-level: flags users with multiple applications in a 24-hour window with CRITICAL / HIGH / MEDIUM risk levels. IP-level: flags IP addresses associated with multiple different user accounts in a 7-day window.

---

### User Roles

Three roles control access:

| Feature | User | Analyst | Admin |
|---|---|---|---|
| Submit applications | ✓ | ✓ | ✓ |
| View own applications | ✓ | ✓ | ✓ |
| View all applications | ✗ | ✓ | ✓ |
| Risk Analytics (7 tabs) | ✗ | ✓ | ✓ |
| Override MANUAL REVIEW | ✗ | ✓ | ✓ |
| Export CSV | ✗ | ✓ | ✓ |
| Manage users and roles | ✗ | ✗ | ✓ |
| Generate invite links | ✗ | ✗ | ✓ |

**Creating an analyst account** — two ways:

1. Admin Panel → Users tab → change any existing user's role to Analyst
2. Admin Panel → Overview → Generate Invite Link → send to the person → they set their own password

---

### Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, Flask 3.x |
| Database | PostgreSQL 14+, psycopg2, raw parameterised SQL |
| ML Model | XGBoost (gradient boosted trees, multi-class softprob) |
| Explainability | SHAP TreeExplainer |
| Authentication | JWT (PyJWT), bcrypt password hashing |
| Validation | Pydantic v2 |
| Frontend | Jinja2 templates, vanilla HTML/CSS/JavaScript, Chart.js 4 |

---

### Project Structure

```
Credit-Risk-Scoring-Engine-main/
│
├── app/
│   ├── routers/
│   │   ├── auth.py           Login, register, invite system, role management
│   │   ├── applications.py   Submit, list, view, export applications
│   │   ├── score.py          Stateless scoring endpoint (no auth required)
│   │   └── features.py       7 enterprise analytics endpoints
│   │
│   ├── sql/
│   │   └── schema.sql        PostgreSQL schema — tables, indexes, migrations
│   │
│   ├── static/
│   │   └── style.css         Full CSS design system
│   │
│   ├── templates/
│   │   ├── base.html             Shared sidebar layout, role-aware navigation
│   │   ├── landing.html          Public landing page
│   │   ├── login.html            Login form
│   │   ├── register.html         Self-registration
│   │   ├── invite.html           Analyst invite acceptance page
│   │   ├── dashboard.html        KPI cards, charts, recent applications
│   │   ├── new_application.html  Credit application form
│   │   ├── applications.html     Applications list with override controls
│   │   ├── results.html          Score gauge, SHAP chart, decision detail
│   │   ├── features.html         7-tab Risk Analytics page
│   │   └── admin.html            Admin Panel — users, roles, invites
│   │
│   ├── auth_utils.py         JWT helpers, bcrypt, role-based decorators
│   ├── database.py           PostgreSQL connection pool, get_db() context manager
│   ├── main.py               Flask app factory, admin seed, page routes
│   ├── schemas.py            Pydantic v2 models for all request/response types
│   ├── scoring.py            XGBoost inference, FICO score, SHAP attributions
│   ├── train_model.py        Synthetic dataset generation, model training
│   ├── model.pkl             Trained model bundle (git-ignored, generate locally)
│   └── requirements.txt      Python dependencies
│
├── .env                      Local configuration (never commit this)
├── .env.example              Template for .env
├── README.md                 This file
├── SETUP.md                  Detailed setup reference
└── NEW_FEATURES.txt          Full documentation of enterprise features with logic review
```

---

### API Reference

**Authentication**

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/register` | No | Register a new user account |
| POST | `/api/auth/login` | No | Login, returns JWT token |
| GET | `/api/auth/me` | Yes | Current user profile and role |
| GET | `/api/auth/users` | Admin | List all users |
| PATCH | `/api/auth/users/<id>/role` | Admin | Change a user's role |
| POST | `/api/auth/invite` | Admin | Generate a single-use invite link |
| POST | `/api/auth/register-analyst` | Token | Accept invite and set password |

**Applications**

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/applications` | Yes | Score and save an application |
| GET | `/api/applications` | Yes | List applications |
| GET | `/api/applications/<id>` | Yes | Single application with full result |
| GET | `/api/applications/export` | Analyst+ | Download all applications as CSV |

**Scoring**

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/score` | No | Score without saving (stateless) |

**Enterprise Features**

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/features/model-validation` | AUC, KS, PSI, Gini |
| POST | `/api/features/stress-test` | CCAR/DFAST scenario analysis |
| GET | `/api/features/expected-loss` | PD × LGD × EAD portfolio |
| GET | `/api/features/audit-log` | Regulatory audit trail |
| GET | `/api/features/models` | Champion/Challenger comparison |
| GET | `/api/features/basel-capital` | Basel III RWA and CAR |
| GET | `/api/features/fraud-velocity` | Velocity flags and IP reuse |
| PATCH | `/api/features/override/<id>` | Analyst override with audit note |

**System**

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Service health check |
#   C r e d i t - R i s k - S c o r i n g - E n g i n e  
 