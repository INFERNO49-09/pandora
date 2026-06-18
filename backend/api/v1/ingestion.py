"""
Ingestion API — paper upload and topic seeding.
"""
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from knowledge_graph.client import run_query
from ingestion.tasks import seed_topic, ingest_paper

router = APIRouter(prefix="/ingest", tags=["ingestion"])


class SeedTopicRequest(BaseModel):
    topic: str
    source: str = "openalex"    # "openalex" or "arxiv"
    max_results: int = 1000


class SinglePaperRequest(BaseModel):
    title: str
    abstract: str
    authors: list[str] = []
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    venue: str | None = None
    citation_count: int = 0


@router.post("/seed")
async def seed_papers(req: SeedTopicRequest):
    """
    Seed the knowledge graph with papers on a topic.
    Queues an async Celery job. Returns job ID for tracking.
    """
    if req.max_results > 10_000:
        raise HTTPException(status_code=400, detail="max_results cannot exceed 10,000")

    if req.source not in ["openalex", "arxiv"]:
        raise HTTPException(status_code=400, detail="source must be 'openalex' or 'arxiv'")

    task = seed_topic.apply_async(
        args=[req.topic, req.source, req.max_results],
        queue="ingestion",
    )

    return {
        "job_id": task.id,
        "status": "queued",
        "message": f"Seeding {req.max_results} papers on '{req.topic}' from {req.source}",
        "status_url": f"/api/v1/ingest/jobs/{task.id}",
    }


@router.post("/paper")
async def ingest_single_paper(req: SinglePaperRequest):
    """
    Ingest a single paper manually.
    """
    from models.types import RawPaper
    import hashlib

    paper = RawPaper(
        source="manual",
        source_id=hashlib.sha256(req.title.encode()).hexdigest()[:16],
        title=req.title,
        abstract=req.abstract,
        authors=req.authors,
        year=req.year,
        doi=req.doi,
        arxiv_id=req.arxiv_id,
        venue=req.venue,
        citation_count=req.citation_count,
    )

    task = ingest_paper.apply_async(
        args=[paper.model_dump()],
        queue="ingestion",
    )

    return {
        "job_id": task.id,
        "status": "queued",
        "status_url": f"/api/v1/ingest/jobs/{task.id}",
    }


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str):
    """Poll status of an async ingestion job."""
    from core.celery_app import celery_app
    from celery.result import AsyncResult

    result = AsyncResult(job_id, app=celery_app)

    response = {
        "job_id": job_id,
        "status": result.status,
    }

    if result.ready():
        if result.successful():
            response["result"] = result.get()
        else:
            response["error"] = str(result.info)

    return response


@router.get("/sources")
async def list_sources():
    """List available ingestion sources."""
    return {
        "sources": [
            {
                "id": "openalex",
                "name": "OpenAlex",
                "description": "250M+ works, fully open, no auth required",
                "rate_limit": "100,000 requests/day (polite pool)",
            },
            {
                "id": "arxiv",
                "name": "arXiv",
                "description": "CS, Physics, Math preprints with full abstracts",
                "rate_limit": "3 requests/second",
            },
        ]
    }


@router.get("/status")
async def ingestion_status():
    """Current ingestion pipeline status."""
    result = await run_query(
        """
        MATCH (p:Paper)
        RETURN count(p) AS total_papers,
               count(CASE WHEN p.year = date().year THEN 1 END) AS this_year,
               max(p.year) AS most_recent_year
        """
    )

    stats = result[0] if result else {}
    return {
        "papers_in_graph": stats.get("total_papers", 0),
        "papers_this_year": stats.get("this_year", 0),
        "most_recent_year": stats.get("most_recent_year"),
    }
