# Credit Risk Scoring Engine

An automated credit risk scoring system built with Python, Flask, PostgreSQL, and XGBoost. It takes a loan applicant's financial data, runs it through a trained ML model, and returns a structured credit decision with a FICO-style risk score, SHAP-based explainability, and a full suite of enterprise-grade analytics used in real financial institutions.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, Flask 3.x |
| Database | PostgreSQL 14+, psycopg2, raw parameterised SQL |
| ML Model | XGBoost (gradient boosted trees, multi-class softprob) |
| Explainability | SHAP TreeExplainer |
| Authentication | JWT (PyJWT), bcrypt |
| Validation | Pydantic v2 |
| Frontend | Jinja2 templates, vanilla HTML/CSS/JS, Chart.js 4 |

No Node.js or frontend build step required.

---

## Prerequisites

| Tool | Minimum version | Download |
|---|---|---|
| Python | 3.11+ | https://www.python.org/downloads |
| PostgreSQL | 14+ | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads |

---

## First-Time Setup

### Step 1 — Create the database

```powershell
psql -U postgres -c "CREATE DATABASE credit_risk;"
```

If `psql` is not recognised, add PostgreSQL to your PATH and open a new terminal:

```
C:\Program Files\PostgreSQL\16\bin
```

---

### Step 2 — Configure environment variables

Open `.env` in the project root and set your PostgreSQL password:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/credit_risk
JWT_SECRET=change-me-in-production
FLASK_DEBUG=true
PORT=5000
```

---

### Step 3 — Create a virtual environment

```powershell
cd app
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, run this once then retry:

```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
```

---

### Step 4 — Install dependencies

```powershell
pip install -r requirements.txt
```

---

### Step 5 — Train the ML model

```powershell
python train_model.py
```

Generates `model.pkl`. Only needed once. Re-run if you modify `train_model.py`.

---

### Step 6 — Start the app

```powershell
python main.py
```

On first run the app automatically creates all database tables and seeds a default admin account. Open your browser at `http://localhost:5000` and log in with:

| Field | Value |
|---|---|
| Email | `admin@riskengine.com` |
| Password | `password123` |

---

## Running the App (after setup)

```powershell
cd app
.venv\Scripts\Activate.ps1
python main.py
```

Open **http://localhost:5000** and log in.

---

## Screenshots

### Dashboard

The dashboard shows portfolio KPIs, score distribution by band, a live credit score trend line, risk class breakdown, and decision outcome counts.

![Dashboard](Images/image4.png)

---

### New Scoring Application

A 3-step form (Personal, Credit, Loan) with quick presets for common borrower profiles.

![New Application Form](Images/image1.png)

---

### Evaluation Report

Every scored application gets a full report: FICO-style gauge, decision banner, SHAP feature contribution chart, and a complete financial profile of the applicant.

![Evaluation Report - Score and SHAP](Images/image2.png)

![Evaluation Report - Financial Profile](Images/image3.png)

---

### Risk Analytics — Model Validation

SR 11-7 compliance metrics computed from live scored applications: AUC-ROC, Gini coefficient, KS statistic, and PSI.

![Model Validation](Images/image5.png)

---

### Risk Analytics — Stress Testing

CCAR/DFAST adverse scenarios applied to the portfolio. Shows approvals lost, exposure at risk, and expected loss increase per scenario.

![Stress Testing](Images/image6.png)

---

### Risk Analytics — Expected Loss

PD x LGD x EAD calculation per application. LGD fixed at 45% (Basel standard for unsecured retail). Ranked by expected loss exposure.

![Expected Loss](Images/image7.png)

---

### Risk Analytics — Audit Trail

Immutable append-only log of every application scored, login, override, and role change. Compliant with SR 11-7, SOX, and GDPR.

![Audit Trail](Images/image8.png)

---

### Risk Analytics — Champion / Challenger

Side-by-side comparison of the production champion model against a shadow challenger. Displays Gini, KS, approval rate, and promotion criteria.

![Champion Challenger](Images/image9.png)

---

### Risk Analytics — Basel III Capital

Risk-Weighted Assets, Capital Required, and Capital Adequacy Ratio for the approved portfolio using IRB approach risk weight tiers.

![Basel III Capital](Images/image10.png)

---

### Risk Analytics — Fraud Velocity

User-level velocity flags (multiple applications in 24h) and IP-level reuse detection (multiple accounts from the same IP in 7 days).

![Fraud Velocity](Images/image11.png)

---

### Admin Panel — User Management

Manage users and change roles directly from the Users tab. All role changes are recorded in the audit trail.

![Admin Panel Users](Images/image12.png)

---

### Admin Panel — Invite Links

Generate single-use invite links to onboard analysts. The invited user sets their own password and the account activates immediately.

![Admin Panel Invite](Images/image13.png)

---

### Admin Panel — Role Definitions

Full breakdown of what each role (Admin, Analyst, User) can access and do within the platform.

![Admin Panel Roles](Images/image14.png)

---

## How the Scoring Works

### Step 1 — Input

14 fields are collected from the applicant:

| Field | Description |
|---|---|
| `name`, `age`, `employment_type` | Personal information |
| `annual_income`, `employment_years` | Income and job stability |
| `credit_history_length`, `num_credit_accounts` | Credit depth |
| `debt_to_income_ratio`, `existing_loans` | Debt burden |
| `num_delinquencies`, `payment_history_score` | Repayment behaviour |
| `loan_amount`, `loan_purpose`, `tenure` | Loan details |

### Step 2 — ML Classification

10 numerical features are extracted and passed to a trained XGBoost classifier (multi:softprob, 160 estimators, max depth 4). The model outputs a probability across three classes:

- Class 0 = LOW risk
- Class 1 = MEDIUM risk
- Class 2 = HIGH risk

The predicted class is whichever has the highest probability. Confidence is that probability as a percentage.

### Step 3 — FICO-Style Score (300-850)

Base score by predicted class: LOW = 755, MEDIUM = 635, HIGH = 515

```
adjustment = (payment_history_score - 75) * 1.3
           - debt_to_income_ratio * 95
           - num_delinquencies * 18
           + min(credit_history_length, 20) * 1.5
           + min(num_credit_accounts, 10) * 1.2
           - (loan_amount / annual_income) * 40
           + min(employment_years, 15) * 0.8

final_score = base_score + adjustment, clamped to [300, 850]
```

Score bands: 300-579 = Poor, 580-669 = Fair, 670-739 = Good, 740-850 = Excellent

### Step 4 — Decision

| Condition | Decision |
|---|---|
| LOW risk AND score >= 690 | APPROVED |
| HIGH risk OR score < 580 | REJECTED |
| Everything else | MANUAL REVIEW |

### Step 5 — SHAP Explainability

The top 5 features that most influenced the prediction are identified using SHAP TreeExplainer. Positive impact means the feature reduced risk; negative means it increased it.

---

## Example API Response

```json
{
  "risk_score": 768,
  "risk_class": "LOW",
  "confidence": 94.2,
  "decision": "APPROVED",
  "top_features": [
    { "feature": "annual_income",         "impact":  0.54  },
    { "feature": "credit_history_length", "impact":  0.475 },
    { "feature": "payment_history_score", "impact":  0.25  },
    { "feature": "debt_to_income_ratio",  "impact": -0.16  },
    { "feature": "num_delinquencies",     "impact":  0.0   }
  ],
  "reasoning": "Strong repayment profile and manageable debt burden indicate low probability of default."
}
```

---

## Enterprise Analytics

Available to analyst and admin roles via the **Risk Analytics** page (7 tabs):

| Tab | Description |
|---|---|
| Model Validation | AUC-ROC, Gini, KS statistic, PSI — SR 11-7 compliance metrics |
| Stress Testing | CCAR/DFAST adverse scenarios (Mild / Moderate / Severe) on the live portfolio |
| Expected Loss | PD x LGD x EAD calculation per application and portfolio totals |
| Audit Trail | Immutable append-only log of every scored application, login, override, and role change |
| Champion / Challenger | Side-by-side production vs. shadow model comparison with auto promotion recommendation |
| Basel III Capital | Risk-Weighted Assets, Capital Adequacy Ratio, capitalisation status |
| Fraud Velocity | User-level multi-application flags and IP-level multi-account detection |

---

## User Roles

| Feature | User | Analyst | Admin |
|---|---|---|---|
| Submit applications | Yes | Yes | Yes |
| View own applications | Yes | Yes | Yes |
| View all applications | No | Yes | Yes |
| Risk Analytics (7 tabs) | No | Yes | Yes |
| Override MANUAL REVIEW | No | Yes | Yes |
| Export CSV | No | Yes | Yes |
| Manage users and roles | No | No | Yes |
| Generate invite links | No | No | Yes |

### Creating analyst accounts

**Option A — Promote an existing user**

1. Have the person register at `/register`
2. Log in as admin > **Admin Panel** > **Users** tab
3. Change their role to `analyst` > **Save**

**Option B — Invite link**

1. Log in as admin > **Admin Panel** > Overview
2. Enter their email, select `Analyst` role > **Generate Invite Link**
3. Send them the link — they set their own password and the account activates immediately

---

## Project Structure

```
Credit-Risk-Scoring-Engine-main/
├── app/
│   ├── routers/
│   │   ├── auth.py           # Login, register, invite, role management
│   │   ├── applications.py   # Submit, list, view, export applications
│   │   ├── score.py          # Stateless scoring endpoint (no auth required)
│   │   └── features.py       # 7 enterprise analytics endpoints
│   ├── sql/
│   │   └── schema.sql        # PostgreSQL schema — tables, indexes, migrations
│   ├── static/
│   │   └── style.css         # Full CSS design system
│   ├── templates/
│   │   ├── base.html             # Shared sidebar layout, role-aware navigation
│   │   ├── landing.html          # Public landing page
│   │   ├── login.html            # Login form
│   │   ├── register.html         # Self-registration
│   │   ├── invite.html           # Analyst invite acceptance page
│   │   ├── dashboard.html        # KPI cards, charts, recent applications
│   │   ├── new_application.html  # Credit application form
│   │   ├── applications.html     # Applications list with override controls
│   │   ├── results.html          # Score gauge, SHAP chart, decision detail
│   │   ├── features.html         # 7-tab Risk Analytics page
│   │   └── admin.html            # Admin Panel — users, roles, invites
│   ├── auth_utils.py         # JWT helpers, bcrypt, role-based decorators
│   ├── database.py           # psycopg2 connection pool, get_db() context manager
│   ├── main.py               # Flask app factory, admin seed, page routes
│   ├── schemas.py            # Pydantic v2 models for all request/response types
│   ├── scoring.py            # XGBoost inference, FICO score, SHAP attributions
│   ├── train_model.py        # Synthetic dataset generation, model training
│   ├── model.pkl             # Trained model bundle (git-ignored, generate locally)
│   └── requirements.txt      # Python dependencies
├── Images/                   # Screenshots used in README
├── .env                      # Local configuration (never commit this)
├── .env.example              # Template for .env
├── README.md                 # This file
└── SETUP.md                  # Detailed setup reference
```

---

## API Reference

### Auth

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/register` | No | Register a new user account |
| POST | `/api/auth/login` | No | Login, returns JWT token |
| GET | `/api/auth/me` | Yes | Current user profile and role |
| GET | `/api/auth/users` | Admin | List all users |
| PATCH | `/api/auth/users/<id>/role` | Admin | Change a user's role |
| POST | `/api/auth/invite` | Admin | Generate a single-use invite link |
| POST | `/api/auth/register-analyst` | Token | Accept invite and set password |
| GET | `/api/auth/invite/<token>` | No | Validate invite token |

### Applications

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/applications` | Yes | Score and save an application |
| GET | `/api/applications` | Yes | List applications |
| GET | `/api/applications/<id>` | Yes | Single application with full result |
| GET | `/api/applications/export` | Analyst+ | Download all applications as CSV |

### Scoring

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/score` | No | Score without saving (stateless) |

### Enterprise Features (analyst/admin only)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/features/model-validation` | AUC, KS, PSI, Gini |
| POST | `/api/features/stress-test` | CCAR/DFAST scenario analysis |
| GET | `/api/features/expected-loss` | PD x LGD x EAD portfolio |
| GET | `/api/features/audit-log` | Regulatory audit trail |
| GET | `/api/features/models` | Champion/Challenger comparison |
| GET | `/api/features/basel-capital` | Basel III RWA and capital adequacy |
| GET | `/api/features/fraud-velocity` | Velocity flags and IP reuse detection |
| PATCH | `/api/features/override/<id>` | Analyst override with audit note |

### System

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/health` | Service health check |

---

## Troubleshooting

**`psql` is not recognised**

Add `C:\Program Files\PostgreSQL\16\bin` to your PATH, then open a new terminal.

**`password authentication failed`**

The password in `DATABASE_URL` must exactly match what you set during PostgreSQL installation.

**`Activate.ps1` cannot be loaded**

Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force` once, then retry.

**`model.pkl` not found**

Run `python train_model.py` from inside the `app/` folder with the virtual environment active.

**PostgreSQL is not running**

```powershell
Start-Service -Name postgresql*
```

**Port 5000 is already in use**

Set `PORT=5001` in `.env` and restart.

**Login fails after dropping tables**

The admin seed only runs when the `users` table is empty. Drop all tables and restart — the account is recreated automatically.
