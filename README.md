# Pandora — AI Discovery Engine for Scientific Research

> Find the connections science has not made yet.

Pandora ingests millions of scientific papers, builds a structured knowledge
graph, and surfaces **research opportunities** — domain pairs that are
semantically close but bibliographically disconnected. It then generates
testable hypotheses, detects scientific contradictions, predicts missing links
using graph ML, and answers discovery questions via a multi-agent copilot.

---

## Architecture

```
Sources (OpenAlex, arXiv)
        │
        ▼
Ingestion Pipeline (Celery)
  → NIM extraction (concepts, methods, relations)
  → Entity resolution
  → Neo4j graph write (MERGE, idempotent)
  → Qdrant vector index (BGE embeddings)
        │
        ▼
Knowledge Graph (Neo4j)
  Nodes: Paper, Concept, Domain, Method, Author, ResearchOpportunity
  Edges: USES, CITES, IN_DOMAIN, RELATED_TO, IMPROVES, CONTRADICTS …
        │
        ├── CARGS Discovery Engine  →  Research Opportunities
        ├── Contradiction Detector  →  Scientific Disagreements
        ├── Graph ML (GraphSAGE / TransE)  →  Link Prediction
        └── LangGraph Agents  →  Copilot (streamed SSE)
        │
        ▼
FastAPI (12 endpoint groups) + Next.js (12 pages)
```

---

## Quick Start

### 1. Prerequisites
- Docker + Docker Compose
- NVIDIA NIM API key — free at https://build.nvidia.com

### 2. Configure
```bash
cp .env.example .env
# Set NVIDIA_NIM_API_KEY and SECRET_KEY in .env
```

### 3. Start all services
```bash
make up
# Starts: Neo4j, Qdrant, PostgreSQL, Redis, FastAPI, Celery worker+beat, Next.js
```

### 4. Check health
```bash
make health
# → {"status": "ok", "neo4j": "connected"}
```

### 5. Seed the graph
```bash
make seed          # Seeds 8 foundational ML/AI topics (~30–60 min)
# or faster:
make seed-topic    # Interactive: choose topic + source + limit
```

### 6. Run discovery
```bash
make scan          # CARGS scan → generates research opportunities
```

### 7. Open the UI
- **Frontend:**   http://localhost:3000
- **API Docs:**   http://localhost:8000/docs
- **Neo4j:**      http://localhost:7474  (neo4j / pandora_secret)
- **Qdrant:**     http://localhost:6333/dashboard

---

## Services

| Service   | Port | Purpose                          |
|-----------|------|----------------------------------|
| Next.js   | 3000 | Frontend UI                      |
| FastAPI   | 8000 | API gateway (12 router groups)   |
| Neo4j     | 7474/7687 | Knowledge graph            |
| Qdrant    | 6333 | Vector similarity index          |
| PostgreSQL| 5432 | Jobs, users, model registry      |
| Redis     | 6379 | Celery broker + cache            |

---

## Frontend Pages (12 routes)

| Route             | Page                 | Description                                  |
|-------------------|----------------------|----------------------------------------------|
| `/`               | Overview             | Stats, top opportunities, graph health       |
| `/discover`       | Opportunities        | Ranked research gaps with CARGS scores       |
| `/discover/[id]`  | Opportunity Detail   | Hypothesis, rationale, experimental approach |
| `/map`            | Science Map          | Cytoscape.js force-directed domain graph     |
| `/trends`         | Trends               | Domain growth, emerging intersections        |
| `/predict`        | Link Prediction      | Node search → predictions + domain scorer   |
| `/contradictions` | Contradictions       | Scientific disagreements + evidence          |
| `/copilot`        | Discovery Copilot    | Streaming agent chat with citations          |
| `/models`         | Model Registry       | GraphSAGE/TransE metrics + training form     |
| `/ingest`         | Ingestion            | Paper seeding + live job status              |

---

## API Endpoints

```
/api/v1/discover/opportunities     GET   Ranked research opportunities
/api/v1/discover/opportunities/:id GET   Full detail + hypothesis
/api/v1/discover/domain-map        GET   Domain graph for visualization
/api/v1/discover/score             POST  On-demand CARGS scoring
/api/v1/discover/stats             GET   Graph statistics

/api/v1/predict/links              POST  Predict missing links from a node
/api/v1/predict/missing-connections GET  Missing concept links in domain

/api/v1/trends/concepts            GET   Fastest-growing concepts
/api/v1/trends/domains             GET   Domain publication velocity
/api/v1/trends/emerging-intersections GET Newly forming domain bridges
/api/v1/trends/publication-timeline GET  Year-by-year domain chart

/api/v1/contradictions             GET   Detected contradictions
/api/v1/contradictions/scan        POST  Trigger async scan
/api/v1/contradictions/live        GET   Synchronous live scan

/api/v1/copilot/query              POST  Streaming SSE agent response
/api/v1/copilot/history/:thread    GET   Conversation history

/api/v1/graph/subgraph             POST  Subgraph for visualization
/api/v1/graph/search               GET   Full-text graph search
/api/v1/graph/node/:id             GET   Node detail + relationships
/api/v1/graph/domains              GET   All domains with paper counts

/api/v1/ingest/seed                POST  Seed papers for a topic (async)
/api/v1/ingest/paper               POST  Ingest single paper manually
/api/v1/ingest/jobs/:id            GET   Poll ingestion job status

/api/v1/models                     GET   Model registry
/api/v1/models/active              GET   Active model per relation type
/api/v1/models/metrics             GET   MRR time series for dashboard
/api/v1/models/train               POST  Trigger training (admin)
/api/v1/models/embed               POST  Trigger embedding refresh (admin)
/api/v1/models/:id/activate        POST  Promote model to active (admin)

/api/v1/auth/register              POST  Create account
/api/v1/auth/token                 POST  Login → JWT
/api/v1/auth/me                    GET   Profile + usage stats
/api/v1/auth/api-key               POST  Generate API key (researcher+)
```

---

## Development Commands

```bash
make up              # Start all services
make down            # Stop all services
make logs            # Follow API + worker logs
make shell           # Bash into API container
make test            # Unit tests
make test-integration # Integration tests (requires INTEGRATION_TESTS=1)

make seed            # Seed MVP topics
make seed-topic      # Seed a single custom topic
make embed-only      # Refresh all node embeddings
make scan            # Run discovery scan

make train           # Train GraphSAGE (concept-concept)
make train-all       # Train all priority edge types
make train-eval      # Print model registry

make auth-register   # Register a new user via CLI
make auth-login      # Login + print JWT

make db-migrate-phase3  # Apply Phase 3 DB schema
make neo4j-shell     # Cypher REPL
make health          # Check service health
make status          # Service status + graph stats
```

---

## Scheduled Jobs (Celery Beat)

| Schedule       | Task                                     |
|----------------|------------------------------------------|
| Every hour     | Ingest recent papers from OpenAlex       |
| Nightly 2 AM   | Full CARGS discovery scan                |
| Nightly 3 AM   | Weekly model training (Sundays only)     |
| Nightly 3:30 AM| Embedding refresh for new nodes          |
| Nightly 4 AM   | Contradiction detection scan             |

---

## Graph ML

GraphSAGE and TransE models trained on the knowledge graph for link prediction.

Train via CLI:
```bash
# Train GraphSAGE on concept-concept relationships
python scripts/train.py --model graphsage \
  --edge-type Concept__RELATED_TO__Concept \
  --epochs 50

# Train all priority edge types
python scripts/train.py --all

# Refresh embeddings after training
python scripts/train.py --embed-only

# Show model registry
python scripts/train.py --eval-only
```

Or via API (admin token required):
```bash
curl -X POST http://localhost:8000/api/v1/models/train \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"model_type":"graphsage","edge_type":"Concept__RELATED_TO__Concept","epochs":50}'
```

---

## Auth

Default admin account (change password immediately):
- Email: `admin@pandora.ai`
- Password: `pandora_admin_2024`

User tiers:
- `free` — 50 copilot queries/month
- `researcher` — unlimited queries, API key access
- `admin` — full access + training triggers

---

## Environment Variables

```bash
NVIDIA_NIM_API_KEY=nvapi-...          # Required
NIM_CHAT_MODEL=meta/llama-3.1-70b-instruct
NIM_EMBED_MODEL=nvidia/nv-embedqa-e5-v5

NEO4J_PASSWORD=pandora_secret
POSTGRES_PASSWORD=pandora_secret
SECRET_KEY=<32-byte hex>              # openssl rand -hex 32

# Optional Supabase production auth
# SUPABASE_JWT_SECRET=...
```

---

## Project Structure

```
pandora/
├── backend/
│   ├── agents/           # LangGraph multi-agent system
│   ├── api/v1/           # FastAPI routers (10 modules)
│   ├── auth/             # JWT middleware, rate limiting
│   ├── core/             # Config, Celery, NIM client
│   ├── discovery/        # CARGS, hypothesis gen, contradictions
│   ├── extraction/       # NIM-based knowledge extraction
│   ├── graph_ml/         # GraphSAGE, TransE, training, inference
│   ├── ingestion/        # OpenAlex + arXiv clients
│   ├── knowledge_graph/  # Neo4j client, schema, graph writer
│   ├── models/           # Pydantic types
│   ├── tests/            # Unit + integration tests
│   └── vector_store/     # Qdrant client
├── frontend/
│   ├── app/              # Next.js App Router pages (12 routes)
│   ├── components/       # Sidebar, UI primitives, graph explorer
│   └── lib/              # API client, utilities
├── infrastructure/
│   └── init_all.sql      # Complete PostgreSQL schema
├── scripts/
│   ├── seed.py           # Graph bootstrap
│   └── train.py          # ML training CLI
├── docker-compose.yml
├── Makefile
└── .env.example
```
