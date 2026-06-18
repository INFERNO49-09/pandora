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

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Pandora starting up...")

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


@app.get("/")
async def root():
    return {
        "name": "Pandora Discovery Engine",
        "docs": "/docs",
        "health": "/health",
    }
