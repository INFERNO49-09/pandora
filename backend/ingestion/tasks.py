"""
Ingestion Celery tasks.
"""
import asyncio
from loguru import logger
from core.celery_app import celery_app
from ingestion.sources.openalex import OpenAlexClient
from ingestion.sources.arxiv import ArXivClient
from extraction.engine import KnowledgeExtractor
from knowledge_graph.graph_writer import GraphWriter
from models.types import RawPaper


def run_async(coro):
    """Run async coroutine in Celery (sync) context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="ingestion.tasks.ingest_paper",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def ingest_paper(self, paper_dict: dict):
    """
    Ingest a single paper: extract knowledge + write to graph.
    Accepts a serialized RawPaper dict.
    """
    try:
        paper = RawPaper(**paper_dict)
        return run_async(_ingest_paper_async(paper))
    except Exception as exc:
        logger.error(f"Ingestion task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(name="ingestion.tasks.run_ingestion_cycle")
def run_ingestion_cycle():
    """
    Hourly ingestion: fetch recent papers from all sources.
    """
    return run_async(_run_ingestion_cycle_async())


@celery_app.task(name="ingestion.tasks.seed_topic")
def seed_topic(topic: str, source: str = "openalex", max_results: int = 1000):
    """
    One-time seed: ingest papers for a specific topic.
    Useful for bootstrapping the graph with a domain.
    """
    return run_async(_seed_topic_async(topic, source, max_results))


async def _ingest_paper_async(paper: RawPaper) -> dict:
    extractor = KnowledgeExtractor()
    writer = GraphWriter()

    extraction = await extractor.extract(paper)

    if extraction.error:
        logger.warning(f"Extraction error for '{paper.title[:60]}': {extraction.error}")
        # Still write the paper node even if extraction failed
        await writer.write_paper_with_extraction(paper, extraction)
        return {"status": "partial", "paper_id": extraction.paper_id, "error": extraction.error}

    paper_id = await writer.write_paper_with_extraction(paper, extraction)

    return {
        "status": "complete",
        "paper_id": paper_id,
        "concepts_extracted": len(extraction.concepts),
        "methods_extracted": len(extraction.methods),
        "relations_extracted": len(extraction.relations),
    }


async def _run_ingestion_cycle_async():
    """Fetch and queue recent papers from enabled sources."""
    client = OpenAlexClient()
    try:
        papers = await client.fetch_recent_papers(
            days_back=7,
            domains=["machine learning", "artificial intelligence", "deep learning"],
            max_results=500,
        )
    finally:
        await client.close()

    # Queue each paper as a separate task
    for paper in papers:
        ingest_paper.apply_async(
            args=[paper.model_dump()],
            queue="ingestion",
        )

    logger.info(f"Queued {len(papers)} papers for ingestion")
    return {"papers_queued": len(papers)}


async def _seed_topic_async(
    topic: str,
    source: str,
    max_results: int,
) -> dict:
    """Seed the graph with papers on a specific topic."""
    papers = []

    if source == "openalex":
        client = OpenAlexClient()
        try:
            papers = await client.fetch_papers_by_topic(topic, max_results=max_results)
        finally:
            await client.close()
    elif source == "arxiv":
        client = ArXivClient()
        try:
            papers = await client.fetch_papers(query=topic, max_results=max_results)
        finally:
            await client.close()

    for paper in papers:
        ingest_paper.apply_async(
            args=[paper.model_dump()],
            queue="ingestion",
        )

    logger.info(f"Seeded {len(papers)} papers for topic '{topic}'")
    return {"topic": topic, "papers_queued": len(papers)}
