"""
Pandora Discovery Engine — FastAPI main application.
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import get_settings
from knowledge_graph.client import setup_schema, close_driver
from vector_store.client import setup_collections
from api.v1 import discovery, ingestion, graph, link_prediction, trends, contradictions, copilot, auth
from api.v1 import models as models_api
from api.v1 import bookmarks, query_history, system

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Pandora starting up...")

    provider_label = "LOCAL" if settings.is_local_llm else "NVIDIA NIM"
    logger.info(
        f"LLM provider: {provider_label} "
        f"(chat={settings.active_chat_model}, embed={settings.active_embed_model}, "
        f"dim={settings.active_embed_dim})"
    )

    # Initialize Neo4j schema
    try:
        await setup_schema()
        logger.info("Neo4j schema ready")
    except Exception as e:
        logger.error(f"Neo4j schema setup failed: {e}")

    # Initialize Qdrant collections
    try:
        await setup_collections()
        logger.info("Qdrant collections ready")
    except Exception as e:
        logger.error(f"Qdrant setup failed: {e}")

    logger.info("Pandora ready")
    yield

    # Shutdown
    await close_driver()
    logger.info("Pandora shut down")


app = FastAPI(
    title="Pandora Discovery Engine",
    description="AI-powered scientific discovery via knowledge graph analysis",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
PREFIX = settings.API_PREFIX
app.include_router(discovery.router, prefix=PREFIX)
app.include_router(ingestion.router, prefix=PREFIX)
app.include_router(graph.router, prefix=PREFIX)
app.include_router(link_prediction.router, prefix=PREFIX)
app.include_router(trends.router, prefix=PREFIX)
app.include_router(contradictions.router, prefix=PREFIX)
app.include_router(copilot.router, prefix=PREFIX)
app.include_router(auth.router, prefix=PREFIX)
app.include_router(models_api.router, prefix=PREFIX)
app.include_router(bookmarks.router, prefix=PREFIX)
app.include_router(query_history.router, prefix=PREFIX)
app.include_router(system.router, prefix=PREFIX)


@app.get("/health")
async def health():
    """Health check endpoint."""
    from knowledge_graph.client import run_query
    try:
        result = await run_query("RETURN 1 AS ok")
        neo4j_ok = bool(result)
    except Exception:
        neo4j_ok = False

    return {
        "status": "ok" if neo4j_ok else "degraded",
        "neo4j": "connected" if neo4j_ok else "disconnected",
        "version": "1.0.0",
    }


@app.get("/health/detailed")
async def health_detailed():
    """Detailed health check — probes all services."""
    import time

    checks: dict[str, dict] = {}

    # Neo4j
    try:
        from knowledge_graph.client import run_query
        t0 = time.monotonic()
        await run_query("RETURN 1 AS ok")
        checks["neo4j"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        checks["neo4j"] = {"status": "error", "detail": str(e)}

    # Qdrant
    try:
        from qdrant_client import AsyncQdrantClient
        t0 = time.monotonic()
        client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
        await client.get_collections()
        checks["qdrant"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        checks["qdrant"] = {"status": "error", "detail": str(e)}

    # PostgreSQL
    try:
        import asyncpg
        t0 = time.monotonic()
        conn = await asyncpg.connect(settings.POSTGRES_DSN.replace("+asyncpg", ""))
        await conn.fetchval("SELECT 1")
        await conn.close()
        checks["postgres"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        checks["postgres"] = {"status": "error", "detail": str(e)}

    # Redis
    try:
        import redis.asyncio as aioredis
        t0 = time.monotonic()
        r = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await r.ping()
        await r.aclose()
        checks["redis"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)}

    # LLM provider (NIM or local)
    try:
        from core.nim_client import check_llm_health
        llm_health = await check_llm_health()
        checks["llm"] = {
            "status": "ok" if llm_health["status"] == "ok" else "error",
            "provider": llm_health["provider"],
            "model": llm_health["chat_model"],
            "latency_ms": llm_health.get("latency_ms"),
            "detail": llm_health.get("error") or llm_health.get("warning"),
        }
    except Exception as e:
        checks["llm"] = {"status": "error", "detail": str(e)}

    overall = "ok" if all(v["status"] == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "version": "1.0.0", "services": checks}


@app.get("/")
async def root():
    return {
        "name": "Pandora Discovery Engine",
        "docs": "/docs",
        "health": "/health",
    }
