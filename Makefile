.PHONY: up down logs shell seed test lint format

# ── DOCKER ────────────────────────────────────────────────────────────────────

up:
	docker compose up -d --build
	@echo ""
	@echo "Pandora is starting up:"
	@echo "  API:      http://localhost:8000"
	@echo "  Docs:     http://localhost:8000/docs"
	@echo "  Neo4j:    http://localhost:7474"
	@echo "  Qdrant:   http://localhost:6333/dashboard"
	@echo ""
	@echo "Run 'make logs' to follow logs"
	@echo "Run 'make seed' to populate the graph"

down:
	docker compose down

restart:
	docker compose restart api worker

logs:
	docker compose logs -f api worker

logs-all:
	docker compose logs -f

# ── SEED ──────────────────────────────────────────────────────────────────────

seed:
	@echo "Seeding MVP topics (this takes 20-40 minutes depending on NIM latency)..."
	docker compose exec api python /app/../scripts/seed.py --preset mvp --embed

seed-topic:
	@read -p "Topic: " topic; \
	read -p "Source (openalex/arxiv): " source; \
	read -p "Limit: " limit; \
	docker compose exec api python /app/../scripts/seed.py \
		--topic "$$topic" --source "$$source" --limit "$$limit" --embed

embed-only:
	docker compose exec api python /app/../scripts/seed.py --embed-only

# ── DISCOVERY ─────────────────────────────────────────────────────────────────

scan:
	@echo "Running discovery scan manually..."
	docker compose exec worker celery -A core.celery_app call \
		discovery.tasks.run_full_discovery_scan

# ── DEVELOPMENT ───────────────────────────────────────────────────────────────

shell:
	docker compose exec api bash

neo4j-shell:
	docker compose exec neo4j cypher-shell -u neo4j -p pandora_secret

test:
	docker compose exec api pytest tests/unit -v

test-all:
	docker compose exec api pytest tests/ -v

lint:
	docker compose exec api ruff check .

format:
	docker compose exec api ruff format .

# ── STATUS ────────────────────────────────────────────────────────────────────

status:
	@echo "=== Service Status ==="
	@docker compose ps
	@echo ""
	@echo "=== Graph Stats ==="
	@curl -s http://localhost:8000/api/v1/discover/stats | python3 -m json.tool

health:
	curl -s http://localhost:8000/health | python3 -m json.tool

# ── PHASE 3: ML + AUTH ────────────────────────────────────────────────────────

train:
	@echo "Training GraphSAGE on concept-concept edges..."
	docker compose exec api python /app/../scripts/train.py \
		--model graphsage \
		--edge-type Concept__RELATED_TO__Concept \
		--epochs 50

train-all:
	@echo "Training all priority edge types (this takes 2-8 hours)..."
	docker compose exec api python /app/../scripts/train.py --all

train-eval:
	docker compose exec api python /app/../scripts/train.py --eval-only

embed-refresh:
	@echo "Refreshing all node embeddings..."
	docker compose exec api python /app/../scripts/train.py --embed-only

# Run integration tests (requires services running)
test-integration:
	docker compose exec api env INTEGRATION_TESTS=1 pytest tests/integration -v --timeout=60

# Auth helpers
auth-register:
	@read -p "Email: " email; \
	read -p "Password: " password; \
	curl -s -X POST http://localhost:8000/api/v1/auth/register \
		-H "Content-Type: application/json" \
		-d "{\"email\":\"$$email\",\"password\":\"$$password\",\"tier\":\"researcher\"}" \
		| python3 -m json.tool

auth-login:
	@read -p "Email: " email; \
	read -p "Password: " password; \
	curl -s -X POST http://localhost:8000/api/v1/auth/token \
		-H "Content-Type: application/json" \
		-d "{\"email\":\"$$email\",\"password\":\"$$password\"}" \
		| python3 -m json.tool

# DB migration for Phase 3
db-migrate-phase3:
	docker compose exec postgres psql -U pandora -d pandora \
		-f /docker-entrypoint-initdb.d/../init_phase3.sql 2>/dev/null || \
	docker compose exec -T postgres psql -U pandora -d pandora < infrastructure/init_phase3.sql
	@echo "Phase 3 schema applied"
