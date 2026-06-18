-- Phase 3 schema additions
-- Appended to infrastructure/init.sql

-- ── USER ACCOUNTS ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pandora_users (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email            TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    full_name        TEXT,
    institution      TEXT,
    research_domains TEXT[] DEFAULT '{}',
    tier             TEXT DEFAULT 'free' CHECK (tier IN ('free', 'researcher', 'admin')),
    is_active        BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON pandora_users(email);

-- ── API KEYS ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS api_keys (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES pandora_users(id) ON DELETE CASCADE,
    key_hash    TEXT NOT NULL UNIQUE,   -- SHA-256 of the raw key
    key_prefix  TEXT NOT NULL,          -- First 12 chars, shown in UI
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    is_active   BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user   ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash   ON api_keys(key_hash);

-- ── BOOKMARKS ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS user_bookmarks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES pandora_users(id) ON DELETE CASCADE,
    entity_type     TEXT CHECK (entity_type IN ('opportunity', 'paper', 'concept', 'domain')),
    entity_id       TEXT NOT NULL,
    entity_title    TEXT,
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON user_bookmarks(user_id);

-- ── QUERY HISTORY ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS query_history (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID REFERENCES pandora_users(id) ON DELETE SET NULL,
    query_text   TEXT NOT NULL,
    query_type   TEXT CHECK (query_type IN ('copilot', 'predict', 'gap', 'search')),
    response_ms  INTEGER,
    agents_used  TEXT[],
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_query_history_user ON query_history(user_id, created_at DESC);

-- ── ML MODEL REGISTRY UPDATES ─────────────────────────────────────────────────
-- Extend existing ml_models table with Phase 3 fields

ALTER TABLE ml_models ADD COLUMN IF NOT EXISTS
    training_duration_s INTEGER;

ALTER TABLE ml_models ADD COLUMN IF NOT EXISTS
    graph_node_count INTEGER;

ALTER TABLE ml_models ADD COLUMN IF NOT EXISTS
    graph_edge_count INTEGER;

ALTER TABLE ml_models ADD COLUMN IF NOT EXISTS
    split_year INTEGER DEFAULT 2022;

ALTER TABLE ml_models ADD COLUMN IF NOT EXISTS
    val_mrr FLOAT;

-- ── SCHEDULED JOB LOG ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS job_log (
    id           BIGSERIAL PRIMARY KEY,
    job_name     TEXT NOT NULL,
    job_type     TEXT CHECK (job_type IN ('training', 'embedding', 'discovery', 'ingestion')),
    celery_task_id TEXT,
    status       TEXT DEFAULT 'running' CHECK (status IN ('running', 'complete', 'failed')),
    result       JSONB,
    error        TEXT,
    started_at   TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_job_log_name   ON job_log(job_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_job_log_status ON job_log(status);

-- Create default admin user (change password immediately!)
-- Password: pandora_admin_2024  (bcrypt hash)
INSERT INTO pandora_users (email, password_hash, full_name, tier)
VALUES (
    'admin@pandora.ai',
    '$2b$12$LQv3c1yqBwEHxPnFOFNrWOLBP4F.3aqJJf0mOixOFdXv.KYD6K8Ki',
    'Pandora Admin',
    'admin'
) ON CONFLICT DO NOTHING;
