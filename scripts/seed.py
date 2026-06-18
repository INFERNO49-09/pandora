#!/usr/bin/env python3
"""
Pandora bootstrap seed script.
Run this once after `docker compose up` to populate the graph
with an initial set of papers.

Usage:
    python scripts/seed.py --topic "machine learning" --source openalex --limit 2000
    python scripts/seed.py --topic "federated learning" --source arxiv --limit 500
    python scripts/seed.py --preset mvp   # seeds 5 foundational topics
"""
import argparse
import asyncio
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from ingestion.sources.openalex import OpenAlexClient
from ingestion.sources.arxiv import ArXivClient
from extraction.engine import KnowledgeExtractor, extract_batch
from knowledge_graph.client import setup_schema
from knowledge_graph.graph_writer import GraphWriter
from vector_store.client import setup_collections, upsert_vectors
from core.nim_client import nim_embed
from loguru import logger

# Core topics for MVP seed — covers major ML/AI domains
MVP_TOPICS = [
    ("machine learning", "openalex", 2000),
    ("deep learning", "openalex", 1000),
    ("natural language processing", "openalex", 1000),
    ("computer vision", "openalex", 1000),
    ("federated learning", "arxiv", 500),
    ("graph neural networks", "arxiv", 500),
    ("drug discovery machine learning", "openalex", 500),
    ("reinforcement learning", "openalex", 500),
]


async def seed_topic(
    topic: str,
    source: str,
    limit: int,
    concurrency: int = 5,
):
    logger.info(f"Seeding: '{topic}' from {source} (limit={limit})")

    # Fetch papers
    if source == "openalex":
        client = OpenAlexClient()
        papers = await client.fetch_papers_by_topic(topic, max_results=limit)
        await client.close()
    elif source == "arxiv":
        client = ArXivClient()
        papers = await client.fetch_papers(query=topic, max_results=limit)
        await client.close()
    else:
        raise ValueError(f"Unknown source: {source}")

    logger.info(f"Fetched {len(papers)} papers")

    # Extract in batches of 20
    writer = GraphWriter()
    total_written = 0
    BATCH = 20

    for i in range(0, len(papers), BATCH):
        batch = papers[i: i + BATCH]
        extractions = await extract_batch(batch, concurrency=concurrency)

        for paper, extraction in zip(batch, extractions):
            try:
                await writer.write_paper_with_extraction(paper, extraction)
                total_written += 1
            except Exception as e:
                logger.warning(f"Write failed for '{paper.title[:50]}': {e}")

        logger.info(f"Progress: {min(i + BATCH, len(papers))}/{len(papers)} papers written")

    logger.success(f"Seed complete: {total_written}/{len(papers)} papers written to graph")
    return total_written


async def embed_all_concepts():
    """After seeding, embed all concepts into Qdrant for similarity search."""
    from knowledge_graph.client import run_query

    logger.info("Embedding all concepts into Qdrant...")

    concepts = await run_query(
        """
        MATCH (c:Concept)
        RETURN c.id AS id, c.canonical_name AS name, c.domain AS domain
        """
    )

    if not concepts:
        logger.warning("No concepts found to embed")
        return

    logger.info(f"Embedding {len(concepts)} concepts...")
    texts = [f"Scientific concept: {c['name']}" for c in concepts]

    BATCH = 96
    total = 0
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
                "id": abs(hash(c["id"])) % (2**63),
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
        total += len(points)
        logger.info(f"Embedded {total}/{len(concepts)} concepts")

    logger.success(f"Embedded {total} concepts into Qdrant")


async def main():
    parser = argparse.ArgumentParser(description="Pandora seed script")
    parser.add_argument("--topic", type=str, help="Topic to seed")
    parser.add_argument("--source", type=str, default="openalex", choices=["openalex", "arxiv"])
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--preset", type=str, choices=["mvp"], help="Use a preset topic set")
    parser.add_argument("--embed", action="store_true", help="Embed concepts after seeding")
    parser.add_argument("--embed-only", action="store_true", help="Only run embedding (skip ingestion)")
    args = parser.parse_args()

    # Initialize schema
    logger.info("Initializing schema...")
    await setup_schema()
    await setup_collections()

    if args.embed_only:
        await embed_all_concepts()
        return

    if args.preset == "mvp":
        total = 0
        for topic, source, limit in MVP_TOPICS:
            count = await seed_topic(topic, source, limit)
            total += count
        logger.success(f"MVP seed complete: {total} papers total")
    elif args.topic:
        await seed_topic(args.topic, args.source, args.limit)
    else:
        parser.print_help()
        sys.exit(1)

    if args.embed or args.preset:
        await embed_all_concepts()


if __name__ == "__main__":
    asyncio.run(main())
