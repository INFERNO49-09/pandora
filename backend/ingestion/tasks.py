"""
Ingestion Celery tasks.
"""
from __future__ import annotations

from collections import Counter

from loguru import logger

from core.async_utils import run_async
from core.celery_app import celery_app
from core.config import get_settings
from entity_resolution.resolver import EntityResolver
from extraction.engine import extract_batch
from ingestion.batching import queue_paper_batches
from ingestion.dedup import DedupResult, filter_new_papers
from ingestion.sources.arxiv import ArXivClient
from ingestion.sources.openalex import OpenAlexClient
from ingestion.state import get_ingestion_state, update_ingestion_state
from knowledge_graph.graph_writer import GraphWriter
from models.types import RawPaper
from vector_store.indexer import index_batch_extractions


@celery_app.task(
    name="ingestion.tasks.ingest_batch",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def ingest_batch(self, paper_dicts: list[dict]):
    """
    Ingest a batch of papers: deduplicate, extract knowledge, write graph, index vectors.
    """
    try:
        return run_async(_ingest_batch_async(paper_dicts))
    except Exception as exc:
        logger.error(f"Batch ingestion task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(
    name="ingestion.tasks.ingest_paper",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def ingest_paper(self, paper_dict: dict):
    """
    Backward-compatible single-paper task.
    """
    try:
        return run_async(_ingest_batch_async([paper_dict]))
    except Exception as exc:
        logger.error(f"Ingestion task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(name="ingestion.tasks.run_ingestion_cycle")
def run_ingestion_cycle():
    """
    Hourly ingestion: fetch recent papers from enabled sources and queue batches.
    """
    return run_async(_run_ingestion_cycle_async())


@celery_app.task(name="ingestion.tasks.seed_topic")
def seed_topic(topic: str, source: str = "openalex", max_results: int = 1000):
    """
    One-time seed for a topic. Queues batch ingestion tasks.
    """
    return run_async(_seed_topic_async(topic, source, max_results))


async def _ingest_batch_async(paper_dicts: list[dict]) -> dict:
    papers = [RawPaper(**paper_dict) for paper_dict in paper_dicts]
    new_papers, duplicates = await filter_new_papers(papers)

    if not new_papers:
        return {
            "status": "duplicate",
            "papers_received": len(papers),
            "papers_processed": 0,
            "duplicates": _duplicate_summary(duplicates),
        }

    extractions = await extract_batch(new_papers, concurrency=5)
    extractions, resolution_stats = EntityResolver().resolve_batch(extractions)
    items = list(zip(new_papers, extractions))

    writer = GraphWriter()
    paper_ids = await writer.write_batch(items)

    try:
        vector_counts = await index_batch_extractions(items)
    except Exception as exc:
        logger.warning(f"Vector batch indexing failed: {exc}")
        vector_counts = {}

    complete = sum(1 for extraction in extractions if not extraction.error)
    partial = len(extractions) - complete
    for source, count in Counter(paper.source for paper in new_papers).items():
        await update_ingestion_state(
            source,
            checkpoint={"last_batch_processed": count},
            papers_ingested_delta=count,
        )
    logger.info(
        f"Ingested batch: received={len(papers)} processed={len(new_papers)} "
        f"duplicates={len(duplicates)} complete={complete} partial={partial}"
    )
    return {
        "status": "complete" if partial == 0 else "partial",
        "papers_received": len(papers),
        "papers_processed": len(new_papers),
        "duplicates": _duplicate_summary(duplicates),
        "complete": complete,
        "partial": partial,
        "entity_resolution": resolution_stats.__dict__,
        "paper_ids": paper_ids,
        "vectors_indexed": vector_counts,
    }


async def _run_ingestion_cycle_async() -> dict:
    settings = get_settings()
    source = "openalex"
    state = await get_ingestion_state(source)

    client = OpenAlexClient()
    try:
        result = await client.fetch_incremental_papers(
            last_sync_timestamp=state.last_sync_timestamp,
            cursor=state.cursor,
            domains=["machine learning", "artificial intelligence", "deep learning"],
            max_results=settings.MAX_PAPERS_PER_RUN,
        )
    finally:
        await client.close()

    task_ids = queue_paper_batches(
        [paper.model_dump() for paper in result.papers],
        ingest_batch,
        batch_size=settings.INGESTION_BATCH_SIZE,
    )
    await update_ingestion_state(
        source,
        cursor=result.next_cursor,
        last_sync_timestamp=result.fetched_at,
        checkpoint={"queued": len(result.papers), "task_ids": task_ids[-20:]},
    )

    return {
        "source": source,
        "papers_queued": len(result.papers),
        "batches_queued": len(task_ids),
        "next_cursor": result.next_cursor,
    }


async def _seed_topic_async(topic: str, source: str, max_results: int) -> dict:
    settings = get_settings()
    papers: list[RawPaper] = []

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
    else:
        raise ValueError(f"Unsupported ingestion source: {source}")

    task_ids = queue_paper_batches(
        [paper.model_dump() for paper in papers],
        ingest_batch,
        batch_size=settings.INGESTION_BATCH_SIZE,
    )

    logger.info(f"Seeded {len(papers)} papers for topic '{topic}' in {len(task_ids)} batches")
    return {
        "topic": topic,
        "source": source,
        "papers_queued": len(papers),
        "batches_queued": len(task_ids),
        "task_ids": task_ids,
    }


def _duplicate_summary(duplicates: list[DedupResult]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for duplicate in duplicates:
        key = duplicate.matched_on or "unknown"
        summary[key] = summary.get(key, 0) + 1
    return summary
