"""
Pre-extraction paper deduplication.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from loguru import logger

from ingestion.state import get_pool
from models.types import RawPaper


@dataclass(frozen=True)
class DedupResult:
    paper: RawPaper
    is_duplicate: bool
    matched_on: str | None = None


def normalize_identifier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned.startswith("https://doi.org/"):
        cleaned = cleaned.removeprefix("https://doi.org/")
    if cleaned.startswith("http://dx.doi.org/"):
        cleaned = cleaned.removeprefix("http://dx.doi.org/")
    return cleaned or None


def compute_content_hash(paper: RawPaper) -> str:
    if paper.content_hash:
        return paper.content_hash
    content = "\n".join(
        [
            (paper.title or "").strip().lower(),
            (paper.abstract or "").strip().lower(),
            str(paper.year or ""),
        ]
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def ensure_dedup_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_paper_fingerprints (
                paper_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT,
                openalex_id TEXT,
                arxiv_id TEXT,
                doi TEXT,
                content_hash TEXT NOT NULL,
                title TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        for column in ("openalex_id", "arxiv_id", "doi", "content_hash"):
            await conn.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_fingerprint_{column}
                ON ingestion_paper_fingerprints ({column})
                WHERE {column} IS NOT NULL
                """
            )


def paper_identity(paper: RawPaper) -> str:
    openalex_id = normalize_identifier(paper.openalex_id or (paper.source_id if paper.source == "openalex" else None))
    if openalex_id:
        return f"openalex:{openalex_id}"
    doi = normalize_identifier(paper.doi)
    if doi:
        return f"doi:{doi}"
    arxiv_id = normalize_identifier(paper.arxiv_id)
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    return f"hash:{compute_content_hash(paper)[:16]}"


async def filter_new_papers(papers: list[RawPaper]) -> tuple[list[RawPaper], list[DedupResult]]:
    await ensure_dedup_schema()
    if not papers:
        return [], []

    pool = await get_pool()
    records = []
    for paper in papers:
        content_hash = compute_content_hash(paper)
        enriched = paper.model_copy(update={"content_hash": content_hash})
        records.append(
            {
                "paper": enriched,
                "paper_id": paper_identity(enriched),
                "source": enriched.source,
                "source_id": normalize_identifier(enriched.source_id),
                "openalex_id": normalize_identifier(enriched.openalex_id),
                "arxiv_id": normalize_identifier(enriched.arxiv_id),
                "doi": normalize_identifier(enriched.doi),
                "content_hash": content_hash,
                "title": enriched.title,
            }
        )

    new_papers: list[RawPaper] = []
    duplicates: list[DedupResult] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for record in records:
                existing = await conn.fetchrow(
                    """
                    SELECT paper_id,
                           CASE
                               WHEN $1::text IS NOT NULL AND openalex_id = $1 THEN 'openalex_id'
                               WHEN $2::text IS NOT NULL AND arxiv_id = $2 THEN 'arxiv_id'
                               WHEN $3::text IS NOT NULL AND doi = $3 THEN 'doi'
                               WHEN content_hash = $4 THEN 'content_hash'
                               ELSE 'paper_id'
                           END AS matched_on
                    FROM ingestion_paper_fingerprints
                    WHERE ($1::text IS NOT NULL AND openalex_id = $1)
                       OR ($2::text IS NOT NULL AND arxiv_id = $2)
                       OR ($3::text IS NOT NULL AND doi = $3)
                       OR content_hash = $4
                    LIMIT 1
                    """,
                    record["openalex_id"],
                    record["arxiv_id"],
                    record["doi"],
                    record["content_hash"],
                )
                if existing:
                    duplicates.append(
                        DedupResult(
                            paper=record["paper"],
                            is_duplicate=True,
                            matched_on=existing["matched_on"],
                        )
                    )
                    continue

                insert_status = await conn.execute(
                    """
                    INSERT INTO ingestion_paper_fingerprints (
                        paper_id, source, source_id, openalex_id,
                        arxiv_id, doi, content_hash, title
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT DO NOTHING
                    """,
                    record["paper_id"],
                    record["source"],
                    record["source_id"],
                    record["openalex_id"],
                    record["arxiv_id"],
                    record["doi"],
                    record["content_hash"],
                    record["title"],
                )
                if insert_status.endswith("1"):
                    new_papers.append(record["paper"])
                else:
                    duplicates.append(
                        DedupResult(
                            paper=record["paper"],
                            is_duplicate=True,
                            matched_on="race_conflict",
                        )
                    )

    if duplicates:
        logger.info(f"Skipped {len(duplicates)} duplicate papers before extraction")
    return new_papers, duplicates
