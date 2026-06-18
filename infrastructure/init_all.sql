-- Pandora PostgreSQL schema
-- Runs automatically on first `docker compose up`

-- ── INGESTION TRACKING ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingestion_sources (
    id TEXT PRIMARY KEY,
    last_checkpoint JSONB DEFAULT '{}',
    papers_ingested BIGINT DEFAULT 0,
    last_run_at TIMESTAMPTZ,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO ingestion_sources (id) VALUES ('openalex'), ('arxiv'), ('pubmed')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT REFERENCES ingestion_sources(id),
    paper_doi TEXT,
    paper_arxiv_id TEXT,
    paper_title TEXT,
    status TEXT DEFAULT 'queued' CHECK (status IN (
        'queued','fetching','extracting','resolving',
        'embedding','graph_write','complete','failed','duplicate'
    )),
    extraction_result JSONB,
    entity_count INTEGER DEFAULT 0,
    relation_count INTEGER DEFAULT 0,
    error_message TEXT,
    processing_time_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON ingestion_jobs(created_at DESC);

-- ── ML MODEL REGISTRY ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ml_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name TEXT NOT NULL,
    model_type TEXT CHECK (model_type IN (
        'embedding_similarity','node2vec','graphsage','gat',
        'transe','rotate','complex','seal','ensemble'
    )),
    relation_type TEXT,
    train_mrr FLOAT,
    val_mrr FLOAT,
    test_mrr FLOAT,
    hits_at_1 FLOAT,
    hits_at_10 FLOAT,
    hyperparameters JSONB DEFAULT '{}',
    model_artifact_s3_key TEXT,
    is_active BOOLEAN DEFAULT FALSE,
    trained_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

INSERT INTO ml_models (model_name, model_type, relation_type, is_active, trained_at)
VALUES ('embedding_similarity_v1', 'embedding_similarity', 'RELATED_TO', TRUE, NOW())
ON CONFLICT DO NOTHING;

-- ── LINK PREDICTIONS ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS link_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id UUID REFERENCES ml_models(id),
    source_node_id TEXT NOT NULL,
    source_node_type TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    target_node_type TEXT NOT NULL,
    predicted_relation_type TEXT NOT NULL,
    confidence_score FLOAT NOT NULL,
    opportunity_score FLOAT,
    status TEXT DEFAULT 'predicted' CHECK (status IN (
        'predicted','validated','dismissed','published'
    )),
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_predictions_score
    ON link_predictions(confidence_score DESC);
CREATE INDEX IF NOT EXISTS idx_predictions_status
    ON link_predictions(status);

-- ── RESEARCH OPPORTUNITIES ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS research_opportunities (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    domain_a TEXT NOT NULL,
    domain_b TEXT NOT NULL,
    bridge_concepts TEXT[] DEFAULT '{}',
    opportunity_score FLOAT NOT NULL,
    novelty_score FLOAT DEFAULT 0,
    impact_score FLOAT DEFAULT 0,
    feasibility_score FLOAT DEFAULT 0,
    velocity_score FLOAT DEFAULT 0,
    hypothesis TEXT,
    hypothesis_rationale TEXT,
    experimental_approach TEXT,
    status TEXT DEFAULT 'active' CHECK (status IN (
        'active','validated','dismissed','in_progress','published'
    )),
    view_count INTEGER DEFAULT 0,
    bookmark_count INTEGER DEFAULT 0,
    generated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_opportunities_score
    ON research_opportunities(opportunity_score DESC);
CREATE INDEX IF NOT EXISTS idx_opportunities_domains
    ON research_opportunities(domain_a, domain_b);

-- ── CONTRADICTION REPORTS ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contradiction_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_a_id TEXT NOT NULL,
    paper_b_id TEXT NOT NULL,
    dataset_id TEXT,
    metric_id TEXT,
    paper_a_value FLOAT,
    paper_b_value FLOAT,
    confidence_score FLOAT NOT NULL,
    explanation TEXT,
    contradiction_type TEXT CHECK (contradiction_type IN (
        'quantitative','qualitative','methodological','reproducibility'
    )),
    detected_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── AUDIT LOG ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    resource_type TEXT,
    resource_id TEXT,
    metadata JSONB DEFAULT '{}',
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
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
