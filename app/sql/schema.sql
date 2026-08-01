-- =============================================================================
-- schema.sql
-- PostgreSQL schema for the Credit Risk Scoring Engine
-- All statements are idempotent (IF NOT EXISTS) so the app can run this on
-- every startup without side effects.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id               SERIAL PRIMARY KEY,
    email            VARCHAR(255) NOT NULL UNIQUE,
    hashed_password  VARCHAR(255) NOT NULL,
    role             VARCHAR(32)  NOT NULL DEFAULT 'user',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Fast login lookup by email
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- ---------------------------------------------------------------------------
-- Applications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS applications (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER      NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    applicant_data  JSONB        NOT NULL,
    score_result    JSONB        NOT NULL,
    status          VARCHAR(32)  NOT NULL DEFAULT 'PENDING',
    model_version   VARCHAR(32)  NOT NULL DEFAULT 'champion-v1',
    ip_address      VARCHAR(64),
    user_agent      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Fast retrieval of all applications for a given user (dashboard queries)
CREATE INDEX IF NOT EXISTS idx_applications_user_id
    ON applications (user_id);

-- Latest-first ordering is the default view — support it efficiently
CREATE INDEX IF NOT EXISTS idx_applications_created_at
    ON applications (created_at DESC);

-- Allow filtering/searching by decision status
CREATE INDEX IF NOT EXISTS idx_applications_status
    ON applications (status);

-- GIN index on JSONB columns for fast key-path queries
CREATE INDEX IF NOT EXISTS idx_applications_applicant_data_gin
    ON applications USING GIN (applicant_data);

CREATE INDEX IF NOT EXISTS idx_applications_score_result_gin
    ON applications USING GIN (score_result);

-- ---------------------------------------------------------------------------
-- Applications — migrate existing tables to add new columns safely
-- ---------------------------------------------------------------------------
ALTER TABLE applications ADD COLUMN IF NOT EXISTS model_version VARCHAR(32)  NOT NULL DEFAULT 'champion-v1';
ALTER TABLE applications ADD COLUMN IF NOT EXISTS ip_address    VARCHAR(64);
ALTER TABLE applications ADD COLUMN IF NOT EXISTS user_agent    TEXT;

-- ---------------------------------------------------------------------------
-- Audit Log (append-only — no UPDATE/DELETE; SR 11-7 / SOX / GDPR)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id              SERIAL PRIMARY KEY,
    event_type      VARCHAR(64)  NOT NULL,
    user_id         INTEGER      REFERENCES users (id) ON DELETE SET NULL,
    application_id  INTEGER      REFERENCES applications (id) ON DELETE SET NULL,
    ip_address      VARCHAR(64),
    user_agent      TEXT,
    payload         JSONB        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Migrate existing audit_log tables that may be missing columns
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent      TEXT;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS payload         JSONB NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_audit_log_event_type
    ON audit_log (event_type);

CREATE INDEX IF NOT EXISTS idx_audit_log_user_id
    ON audit_log (user_id);

CREATE INDEX IF NOT EXISTS idx_audit_log_application_id
    ON audit_log (application_id);

CREATE INDEX IF NOT EXISTS idx_audit_log_created_at
    ON audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_audit_log_payload_gin
    ON audit_log USING GIN (payload);

-- ---------------------------------------------------------------------------
-- Optional: audit / query view
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_application_summary AS
SELECT
    a.id,
    a.user_id,
    u.email                                          AS applicant_email,
    a.applicant_data ->> 'name'                      AS applicant_name,
    (a.applicant_data ->> 'annual_income')::NUMERIC  AS annual_income,
    (a.applicant_data ->> 'loan_amount')::NUMERIC    AS loan_amount,
    (a.score_result   ->> 'risk_score')::INTEGER     AS risk_score,
    a.score_result    ->> 'risk_class'               AS risk_class,
    a.score_result    ->> 'decision'                 AS decision,
    (a.score_result   ->> 'confidence')::NUMERIC     AS confidence,
    a.status,
    a.created_at
FROM applications a
JOIN users u ON u.id = a.user_id;
