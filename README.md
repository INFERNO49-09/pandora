# 🌌 Pandora — AI Discovery Engine for Scientific Research

[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-black?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org/)
[![Neo4j](https://img.shields.io/badge/Neo4j-008CC1?style=for-the-badge&logo=neo4j&logoColor=white)](https://neo4j.com/)
[![Qdrant](https://img.shields.io/badge/Qdrant-EC2754?style=for-the-badge&logo=qdrant&logoColor=white)](https://qdrant.tech/)

> *Find the connections science has not made yet.*

Pandora is a revolutionary scientific discovery engine. It ingests millions of scientific papers to build a highly structured, multidimensional knowledge graph. Using this graph, Pandora surfaces **research opportunities**—domain pairs that are semantically close but bibliographically disconnected.

Beyond simple search, Pandora actively drives discovery by generating testable hypotheses, detecting cross-paper scientific contradictions, predicting missing links using sophisticated Graph ML (GraphSAGE / TransE), and providing a multi-agent copilot for dynamic scientific reasoning.

---

## 🏛 Architecture

```text
Sources (OpenAlex, arXiv)
        │
        ▼
Ingestion Pipeline (Celery)
  → LLM Extraction (concepts, methods, relations)
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
        ├── Contradiction Detector  →  Scientific Disagreements & Edge Persistence
        ├── Graph ML (GraphSAGE)    →  Link Prediction
        └── LangGraph Agents        →  Copilot (streamed SSE)
        │
        ▼
FastAPI Backend (12 routers) + Next.js Frontend
```

---

## 🚀 Quick Start

### 1. Prerequisites
- Docker + Docker Compose
- An LLM provider:
  - **Local Model (Recommended):** [Ollama](https://ollama.com) running locally for unlimited free extractions.
  - **Cloud:** NVIDIA NIM API key (from [build.nvidia.com](https://build.nvidia.com)).

### 2. Configure Environment
```bash
cp .env.example .env
```
Edit `.env` to configure your LLM setup (see **Local LLM Support** below).

### 3. Start the Ecosystem
```bash
make up
# Starts Neo4j, Qdrant, PostgreSQL, Redis, FastAPI backend, Celery worker+beat, and the Next.js frontend.
```

### 4. Health Check
```bash
make health
# Expected: {"status": "ok", "neo4j": "connected"}
```

### 5. Seed the Knowledge Graph
```bash
make seed          # Seeds foundational ML/AI topics
# or for an interactive CLI:
make seed-topic
```

### 6. Run Discovery & Contradiction Scans
```bash
make scan          # Runs CARGS scan for research opportunities
```

### 7. Access Interfaces
- **Frontend App:** http://localhost:3000
- **API Docs:** http://localhost:8000/docs
- **Neo4j Browser:** http://localhost:7474 (credentials: `neo4j` / `pandora_secret`)
- **Qdrant Dashboard:** http://localhost:6333/dashboard

---

## 🧩 Services Overview

| Service      | Port | Purpose                                   |
|--------------|------|-------------------------------------------|
| **Next.js**  | 3000 | Frontend UI application                   |
| **FastAPI**  | 8000 | Core API backend routing & orchestration  |
| **Neo4j**    | 7687 | Primary Knowledge Graph                   |
| **Qdrant**   | 6333 | Vector similarity index for embeddings    |
| **PostgreSQL**| 5432| User management, logs, contradiction reports|
| **Redis**    | 6379 | Celery task broker & caching              |

---

## 🛠 Local LLM Setup (Ollama / Windows)

Pandora allows you to run purely local inference using Ollama, bypassing costly cloud APIs.

**Setup Instructions:**
1. Install [Ollama](https://ollama.com).
2. Pull the required models:
   ```bash
   ollama pull llama3
   ollama pull nomic-embed-text
   ```
3. Update your `.env` file for **Docker Desktop on Windows/WSL2**:
   ```env
   LLM_PROVIDER=local
   
   # Use host.docker.internal to bridge the container to your host machine's Ollama!
   LOCAL_LLM_BASE_URL=http://host.docker.internal:11434/v1
   LOCAL_CHAT_MODEL=llama3
   LOCAL_EMBED_MODEL=nomic-embed-text
   LOCAL_EMBED_DIM=768
   ```

**Important Notes:**
- Switching between NIM and local LLMs changes your embedding dimensions (NIM uses 1024-dim, Nomic uses 768-dim). If you switch, you should clear your Qdrant volumes to avoid dimension mismatches.

---

## 🤖 Graph ML & Link Prediction

Pandora includes Graph ML models (GraphSAGE) to predict previously unseen connections between nodes.

**Training CLI:**
```bash
# Train GraphSAGE on concept relationships
python scripts/train.py --model graphsage --edge-type Concept__RELATED_TO__Concept --epochs 50

# Display the model registry
python scripts/train.py --eval-only
```

---

## 🕵️ Contradiction Detection

Pandora automatically scans the literature graph for scientific contradictions. 
- **Tabular Persistence**: Stores contradiction reports to PostgreSQL for auditing.
- **Graph Edges**: Creates explicit `[:CONTRADICTS]` edges in Neo4j between contradicting papers, tagged with confidence scores and extraction evidence, providing an immediate visual map of academic disputes.

---

## 🕒 Background Jobs (Celery Beat)

| Schedule        | Task Description                          |
|-----------------|-------------------------------------------|
| **Hourly**      | Ingest recent papers from OpenAlex        |
| **2:00 AM**     | Full CARGS discovery scan                 |
| **3:00 AM**     | Weekly model training (Sundays only)      |
| **3:30 AM**     | Embedding refresh for new nodes           |
| **4:00 AM**     | Contradiction detection & persistence scan|

---

## 🔐 Authentication

A default admin account is created automatically upon database initialization.
- **Email:** `admin@pandora.ai`
- **Password:** `pandora_admin_2024` *(Please change immediately in production)*

Tiers:
- `free`: Limited copilot queries
- `researcher`: Unlimited queries and API key generation
- `admin`: Full system control (including Graph ML training triggers)

---

*Pandora is open-source software built to accelerate human discovery.*
