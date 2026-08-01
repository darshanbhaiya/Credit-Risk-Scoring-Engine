# How to Run — Credit Risk Scoring Engine

**Stack:** Python · Flask · PostgreSQL · XGBoost  
**Frontend:** Pure HTML/CSS/JavaScript via Flask Jinja2 templates — no Node.js required.

---

## What you need

| Tool | Minimum version | Download |
|---|---|---|
| Python | 3.11+ | https://www.python.org/downloads |
| PostgreSQL | 14+ | https://www.enterprisedb.com/downloads/postgres-postgresql-downloads |

---

## Step 1 — Install PostgreSQL

1. Download and run the installer
2. Keep all defaults, set a password for the `postgres` user — **remember it**
3. Keep port **5432**
4. Confirm it works:

```powershell
psql --version
```

---

## Step 2 — Create the database

```powershell
psql -U postgres -c "CREATE DATABASE credit_risk;"
```

---

## Step 3 — Configure the .env file

Open `.env` in the project root and set your PostgreSQL password:

```env
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/credit_risk
JWT_SECRET=change-me-in-production
FLASK_DEBUG=true
PORT=5000
```

---

## Step 4 — Create a Python virtual environment

```powershell
cd d:\Projects\Credit-Risk-Scoring-Engine-main\app
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script:
```powershell
Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
```

---

## Step 5 — Install Python packages

```powershell
pip install -r requirements.txt
```

---

## Step 6 — Train the ML model (one time only)

```powershell
python train_model.py
```

Generates `model.pkl`. Only needed once. Re-run if you modify `train_model.py`.

---

## Step 7 — Start the app

```powershell
python main.py
```

Flask starts on **http://localhost:5000** and automatically:
- Creates all PostgreSQL tables on first run
- Seeds the default admin account (see below)
- Serves all pages as Jinja2 templates

---

## Step 8 — Log in

Go to **http://localhost:5000/login**

The app seeds a default admin account on first startup:

| Field | Value |
|---|---|
| Email | `admin@riskengine.com` |
| Password | `password123` |

> Change these credentials via **Admin Panel → Users** after first login.

---

## Step 9 — Create analyst accounts

Analysts can view all applications, access all Risk Analytics tabs, and override
`MANUAL REVIEW` decisions. There are two ways to create them:

**Option A — Promote an existing user (Admin Panel → Users tab):**
1. Have the person register at `/register` with any email/password
2. Log in as admin → **Admin Panel** → **Users** tab
3. Change their role dropdown from `user` to `analyst` → **Save**

**Option B — Invite link (Admin Panel → Overview tab):**
1. Log in as admin → **Admin Panel** → Overview
2. Enter their email, select `Analyst` role → **Generate Invite Link**
3. Send them the link — they set their own password, account activates immediately

---

## Starting again next time

```powershell
cd d:\Projects\Credit-Risk-Scoring-Engine-main\app
.venv\Scripts\Activate.ps1
python main.py
```

Open **http://localhost:5000**.

---

## Reset the database (start fresh)

Run in psql or pgAdmin:

```sql
DROP VIEW  IF EXISTS v_application_summary;
DROP TABLE IF EXISTS audit_log    CASCADE;
DROP TABLE IF EXISTS applications CASCADE;
DROP TABLE IF EXISTS users        CASCADE;
```

Then restart `python main.py` — tables and the admin account are recreated automatically.

---

## Project structure

```
Credit-Risk-Scoring-Engine-main/
├── app/
│   ├── routers/
│   │   ├── auth.py          # /api/auth/* — login, register, invite, role management
│   │   ├── applications.py  # /api/applications/* — CRUD + CSV export
│   │   ├── score.py         # /api/score — stateless scoring endpoint
│   │   └── features.py      # /api/features/* — 7 enterprise analytics endpoints
│   ├── sql/
│   │   └── schema.sql       # PostgreSQL DDL (tables, indexes, migrations)
│   ├── static/
│   │   └── style.css        # Full CSS design system
│   ├── templates/
│   │   ├── base.html             # Shared sidebar layout + role-aware nav
│   │   ├── landing.html          # Public landing page
│   │   ├── login.html            # Login form
│   │   ├── register.html         # Self-registration form
│   │   ├── invite.html           # Analyst invite acceptance page
│   │   ├── dashboard.html        # KPI cards + charts + recent applications
│   │   ├── new_application.html  # 3-step credit application form
│   │   ├── applications.html     # Filterable applications list + override modal
│   │   ├── results.html          # Score gauge + SHAP bars + applicant data
│   │   ├── features.html         # 7-tab Risk Analytics page
│   │   └── admin.html            # Admin Panel (Overview / Users / Roles tabs)
│   ├── auth_utils.py        # JWT + bcrypt + login_required / analyst_required decorators
│   ├── database.py          # psycopg2 connection pool + get_db() context manager
│   ├── main.py              # Flask app factory + admin seed + page routes
│   ├── schemas.py           # Pydantic v2 validation models
│   ├── scoring.py           # XGBoost inference + SHAP explanations
│   ├── train_model.py       # Synthetic dataset generation + model training
│   ├── model.pkl            # Trained model bundle (generated by train_model.py)
│   └── requirements.txt     # Python dependencies
├── .env                     # Local config — DB URL, JWT secret (never committed)
├── .env.example             # Template for .env
├── SETUP.md                 # This file
└── .gitignore
```

---

## Role permissions

| Feature | User | Analyst | Admin |
|---|---|---|---|
| Submit applications | ✓ | ✓ | ✓ |
| View own applications | ✓ | ✓ | ✓ |
| View ALL applications | ✗ | ✓ | ✓ |
| Risk Analytics (7 tabs) | ✗ | ✓ | ✓ |
| Override MANUAL REVIEW | ✗ | ✓ | ✓ |
| Export CSV | ✗ | ✓ | ✓ |
| Manage users / roles | ✗ | ✗ | ✓ |
| Generate invite links | ✗ | ✗ | ✓ |

---

## API endpoints

### Auth
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/auth/register` | No | Self-register (gets `user` role) |
| POST | `/api/auth/login` | No | Login, returns JWT |
| GET | `/api/auth/me` | Yes | Current user profile |
| GET | `/api/auth/users` | Admin | List all users |
| PATCH | `/api/auth/users/<id>/role` | Admin | Change a user's role |
| POST | `/api/auth/invite` | Admin | Generate single-use invite link |
| POST | `/api/auth/register-analyst` | No | Accept invite + set password |
| GET | `/api/auth/invite/<token>` | No | Validate invite token |

### Applications
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/applications` | Yes | Score + save application |
| GET | `/api/applications` | Yes | List applications (own / all for analyst+admin) |
| GET | `/api/applications/<id>` | Yes | Single application result |
| GET | `/api/applications/export` | Analyst+ | Download CSV |

### Scoring
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/score` | No | Score without saving (stateless) |

### Enterprise Features (analyst/admin only)
| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/features/model-validation` | AUC, KS, PSI, Gini — SR 11-7 metrics |
| POST | `/api/features/stress-test` | CCAR/DFAST portfolio stress scenarios |
| GET | `/api/features/expected-loss` | PD × LGD × EAD calculation |
| GET | `/api/features/audit-log` | Immutable regulatory audit trail |
| GET | `/api/features/models` | Champion/Challenger model comparison |
| GET | `/api/features/basel-capital` | Basel III RWA and capital adequacy |
| GET | `/api/features/fraud-velocity` | Velocity flags and IP reuse detection |
| PATCH | `/api/features/override/<id>` | Analyst override of MANUAL REVIEW decision |

### System
| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/api/health` | No | Service health check |

---

## Troubleshooting

**`psql` not recognised**
Add `C:\Program Files\PostgreSQL\16\bin` to your PATH, then open a new terminal.

**`password authentication failed`**
The password in `DATABASE_URL` must match your PostgreSQL installation password.

**`Activate.ps1` blocked**
Run `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser -Force` once, then retry.

**`model.pkl not found`**
Run `python train_model.py` from inside `app/` with the virtual environment active.

**PostgreSQL not running**
```powershell
Start-Service -Name postgresql*
```

**Port 5000 in use**
Set `PORT=5001` in `.env` and restart Flask.

**Login fails with "Invalid email or password"**
The admin seed only runs when the `users` table is empty. If you already have users,
use the credentials you registered with. To reset, drop all tables (see above) and restart.
