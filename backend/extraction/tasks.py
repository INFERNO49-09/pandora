"""
Extraction Celery tasks.
Separated from ingestion tasks so the extraction worker
can be scaled independently from the fetching worker.
"""
import asyncio
from loguru import logger
from core.celery_app import celery_app
from extraction.engine import KnowledgeExtractor
from knowledge_graph.graph_writer import GraphWriter
from models.types import RawPaper, ExtractionResult


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="extraction.tasks.extract_and_write",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def extract_and_write(self, paper_dict: dict) -> dict:
    """
    Extract knowledge from a paper and write to graph.
    Designed to be called after PDF parsing / metadata fetch.
    """
    try:
        paper = RawPaper(**paper_dict)
        return run_async(_extract_and_write_async(paper))
    except Exception as exc:
        logger.error(f"Extract+write task failed: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(name="extraction.tasks.embed_concepts")
def embed_and_index_concepts(domain: str | None = None) -> dict:
    """
    Embed all concept nodes and upsert into Qdrant.
    Run after a batch ingestion to keep vector index fresh.
    """
    return run_async(_embed_concepts_async(domain))


async def _extract_and_write_async(paper: RawPaper) -> dict:
    extractor = KnowledgeExtractor()
    writer = GraphWriter()

    extraction = await extractor.extract(paper)
    paper_id = await writer.write_paper_with_extraction(paper, extraction)

    return {
        "paper_id": paper_id,
        "concepts": len(extraction.concepts),
        "methods": len(extraction.methods),
        "relations": len(extraction.relations),
        "error": extraction.error,
    }


async def _embed_concepts_async(domain: str | None) -> dict:
    """
    Fetch all concepts from Neo4j, embed them via NIM, store in Qdrant.
    """
    from knowledge_graph.client import run_query
    from vector_store.client import upsert_vectors
    from core.nim_client import nim_embed

    domain_filter = ""
    params: dict = {}
    if domain:
        domain_filter = "WHERE c.domain = $domain"
        params["domain"] = domain

    concepts = await run_query(
        f"""
        MATCH (c:Concept)
        {domain_filter}
        RETURN c.id AS id, c.canonical_name AS name, c.domain AS domain
        LIMIT 10000
        """,
        params=params,
    )

    if not concepts:
        return {"embedded": 0}

    # Batch embed
    texts = [f"Scientific concept: {c['name']}" for c in concepts]
    BATCH = 96
    total_embedded = 0

    for i in range(0, len(texts), BATCH):
        batch_texts = texts[i: i + BATCH]
        batch_concepts = concepts[i: i + BATCH]

        try:
            vectors = await nim_embed(batch_texts)
        except Exception as e:
            logger.error(f"Embedding batch {i} failed: {e}")
            continue

        points = [
            {
                "id": abs(hash(c["id"])) % (2**63),  # Qdrant needs uint64
                "vector": vec,
                "payload": {
                    "node_id": c["id"],
                    "name": c["name"],
                    "domain": c.get("domain"),
                    "type": "concept",
                },
            }
            for c, vec in zip(batch_concepts, vectors)
        ]

        await upsert_vectors("concepts", points)
        total_embedded += len(points)

    logger.info(f"Embedded {total_embedded} concepts into Qdrant")
    return {"embedded": total_embedded, "domain": domain}
