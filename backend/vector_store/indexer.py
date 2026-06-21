"""
Helpers for indexing graph entities into Qdrant.
"""
from __future__ import annotations

import hashlib

from loguru import logger

from core.nim_client import nim_embed
from knowledge_graph.graph_writer import _concept_id, _domain_id, _method_id
from models.types import ExtractionResult, RawPaper
from vector_store.client import upsert_vectors


def qdrant_point_id(node_id: str) -> int:
    """Stable unsigned integer ID for Qdrant points."""
    digest = hashlib.blake2b(node_id.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") & ((1 << 63) - 1)


async def index_paper_extraction(
    paper: RawPaper,
    extraction: ExtractionResult,
) -> dict[str, int]:
    """
    Embed and upsert one ingested paper plus extracted entities.

    Embedding failures are intentionally handled by callers so graph ingestion
    can still succeed if the vector backend or embedding provider is unavailable.
    """
    return await index_batch_extractions([(paper, extraction)])


async def index_batch_extractions(
    items: list[tuple[RawPaper, ExtractionResult]],
) -> dict[str, int]:
    """
    Embed and upsert papers and extracted entities in collection-level batches.
    """
    batches: dict[str, list[dict]] = {
        "papers": [],
        "concepts": [],
        "domains": [],
    }

    seen_points: set[tuple[str, str]] = set()
    for paper, extraction in items:
        if paper.title:
            paper_text = f"Paper: {paper.title}\nAbstract: {(paper.abstract or '')[:1200]}"
            batches["papers"].append(
                {
                    "node_id": extraction.paper_id,
                    "text": paper_text,
                    "payload": {
                        "node_id": extraction.paper_id,
                        "title": paper.title,
                        "type": "Paper",
                        "year": paper.year,
                        "source": paper.source,
                    },
                }
            )

        for concept in extraction.concepts:
            name = concept.canonical_name or concept.name
            if not name:
                continue
            node_id = _concept_id(name)
            key = ("concepts", node_id)
            if key in seen_points:
                continue
            seen_points.add(key)
            batches["concepts"].append(
                {
                    "node_id": node_id,
                    "text": f"Scientific concept: {name}",
                    "payload": {
                        "node_id": node_id,
                        "name": name,
                        "domain": concept.domain,
                        "type": "Concept",
                        "source_paper_id": extraction.paper_id,
                    },
                }
            )

        for method in extraction.methods:
            name = method.canonical_name or method.name
            if not name:
                continue
            node_id = _method_id(name)
            key = ("concepts", node_id)
            if key in seen_points:
                continue
            seen_points.add(key)
            batches["concepts"].append(
                {
                    "node_id": node_id,
                    "text": f"Scientific method: {name}",
                    "payload": {
                        "node_id": node_id,
                        "name": name,
                        "category": method.category,
                        "type": "Method",
                        "source_paper_id": extraction.paper_id,
                    },
                }
            )

        for domain in extraction.domains:
            if not domain:
                continue
            node_id = _domain_id(domain)
            key = ("domains", node_id)
            if key in seen_points:
                continue
            seen_points.add(key)
            batches["domains"].append(
                {
                    "node_id": node_id,
                    "text": f"Research domain: {domain}",
                    "payload": {
                        "node_id": node_id,
                        "name": domain,
                        "type": "Domain",
                        "source_paper_id": extraction.paper_id,
                    },
                }
            )

    counts: dict[str, int] = {}
    for collection, items in batches.items():
        if not items:
            counts[collection] = 0
            continue

        vectors = await nim_embed([item["text"] for item in items])
        points = [
            {
                "id": qdrant_point_id(item["node_id"]),
                "vector": vector,
                "payload": item["payload"],
            }
            for item, vector in zip(items, vectors)
        ]
        await upsert_vectors(collection, points)
        counts[collection] = len(points)

    logger.debug(f"Indexed vectors for {len(items)} papers: {counts}")
    return counts
