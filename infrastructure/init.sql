-- Pandora PostgreSQL schema
-- Runs automatically on first `docker compose up`

-- ── INGESTION TRACKING ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingestion_sources (
    id TEXT PRIMARY KEY,
    cursor TEXT,
    last_sync_timestamp TIMESTAMPTZ,
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
CREATE INDEX IF NOT EXISTS idx_ingestion_sources_sync
    ON ingestion_sources (id, last_sync_timestamp DESC);

CREATE TABLE IF NOT EXISTS ingestion_paper_fingerprints (
    paper_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT,
    openalex_id TEXT,
    arxiv_id TEXT,
    doi TEXT,
    content_hash TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_fingerprint_openalex_id
    ON ingestion_paper_fingerprints (openalex_id)
    WHERE openalex_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_fingerprint_arxiv_id
    ON ingestion_paper_fingerprints (arxiv_id)
    WHERE arxiv_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_fingerprint_doi
    ON ingestion_paper_fingerprints (doi)
    WHERE doi IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_fingerprint_content_hash
    ON ingestion_paper_fingerprints (content_hash)
    WHERE content_hash IS NOT NULL;

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
