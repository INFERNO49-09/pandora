"""
OpenAlex source client with cursor pagination and rich metadata parsing.
"""
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from models.types import RawPaper


OPENALEX_BASE = "https://api.openalex.org"
POLITE_EMAIL = "pandora@example.com"
MAX_REFERENCES_PER_PAPER = 200


@dataclass(frozen=True)
class OpenAlexFetchResult:
    papers: list[RawPaper]
    next_cursor: str | None
    fetched_at: datetime


class OpenAlexClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=OPENALEX_BASE,
            headers={"User-Agent": f"Pandora/1.0 (mailto:{POLITE_EMAIL})"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def fetch_papers_by_topic(
        self,
        topic: str,
        max_results: int = 1000,
        from_date: str | None = None,
        cursor: str | None = None,
    ) -> list[RawPaper]:
        result = await self.fetch_papers_pagewise(
            search=topic,
            max_results=max_results,
            from_date=from_date,
            cursor=cursor,
        )
        logger.info(f"OpenAlex: fetched {len(result.papers)} papers for topic '{topic}'")
        return result.papers

    async def fetch_recent_papers(
        self,
        days_back: int = 7,
        domains: list[str] | None = None,
        max_results: int = 5000,
        cursor: str | None = None,
    ) -> OpenAlexFetchResult:
        from_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        topic = " OR ".join(domains) if domains else "machine learning"
        return await self.fetch_papers_pagewise(
            search=topic,
            max_results=max_results,
            from_date=from_date,
            cursor=cursor,
        )

    async def fetch_incremental_papers(
        self,
        *,
        last_sync_timestamp: datetime | None,
        cursor: str | None,
        domains: list[str] | None = None,
        max_results: int = 5000,
    ) -> OpenAlexFetchResult:
        from_updated_date = None
        if last_sync_timestamp:
            from_updated_date = last_sync_timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d")

        topic = " OR ".join(domains) if domains else "machine learning"
        return await self.fetch_papers_pagewise(
            search=topic,
            max_results=max_results,
            from_updated_date=from_updated_date,
            cursor=cursor,
        )

    async def fetch_papers_pagewise(
        self,
        *,
        search: str | None,
        max_results: int,
        from_date: str | None = None,
        from_updated_date: str | None = None,
        cursor: str | None = None,
    ) -> OpenAlexFetchResult:
        papers: list[RawPaper] = []
        next_cursor = cursor or "*"
        fetched_at = datetime.now(timezone.utc)

        while len(papers) < max_results and next_cursor:
            per_page = min(200, max_results - len(papers))
            params: dict[str, Any] = {
                "per-page": per_page,
                "cursor": next_cursor,
                "select": ",".join(
                    [
                        "id",
                        "doi",
                        "title",
                        "display_name",
                        "abstract_inverted_index",
                        "publication_year",
                        "publication_date",
                        "updated_date",
                        "primary_location",
                        "authorships",
                        "cited_by_count",
                        "referenced_works",
                        "related_works",
                        "concepts",
                        "topics",
                        "primary_topic",
                        "keywords",
                        "open_access",
                        "counts_by_year",
                        "ids",
                    ]
                ),
                "sort": "updated_date:asc",
            }
            if search:
                params["search"] = search

            filters = []
            if from_date:
                filters.append(f"from_publication_date:{from_date}")
            if from_updated_date:
                filters.append(f"from_updated_date:{from_updated_date}")
            if filters:
                params["filter"] = ",".join(filters)

            data = await self._get_json("/works", params=params)
            results = data.get("results", [])
            if not results:
                break

            for work in results:
                paper = self._parse_work(work)
                if paper:
                    papers.append(paper)

            next_cursor = (data.get("meta") or {}).get("next_cursor")
            await asyncio.sleep(0.11)

        return OpenAlexFetchResult(
            papers=papers[:max_results],
            next_cursor=next_cursor,
            fetched_at=fetched_at,
        )

    @retry(
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        wait=wait_exponential_jitter(initial=1, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    async def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def _parse_work(self, work: dict[str, Any]) -> RawPaper | None:
        title = (work.get("title") or work.get("display_name") or "").strip()
        if not title:
            return None

        abstract = self._reconstruct_abstract(work.get("abstract_inverted_index") or {})
        openalex_url = work.get("id") or ""
        openalex_id = openalex_url.rstrip("/").split("/")[-1]
        doi = self._normalize_doi(work.get("doi") or (work.get("ids") or {}).get("doi"))

        authors, authorships, institutions = self._parse_authorships(work.get("authorships") or [])
        venue = self._parse_venue(work.get("primary_location") or {})
        references = [
            ref.rstrip("/").split("/")[-1]
            for ref in (work.get("referenced_works") or [])[:MAX_REFERENCES_PER_PAPER]
            if ref
        ]
        concepts = self._parse_named_scores(work.get("concepts") or [])
        topics = self._parse_named_scores(work.get("topics") or [])
        primary_topic = self._parse_topic(work.get("primary_topic"))
        keywords = [
            item.get("display_name", "")
            for item in (work.get("keywords") or [])
            if item.get("display_name")
        ]
        content_hash = hashlib.sha256(
            "\n".join([title.lower(), abstract.lower(), str(work.get("publication_year") or "")]).encode("utf-8")
        ).hexdigest()

        return RawPaper(
            source="openalex",
            source_id=openalex_id,
            openalex_id=openalex_id,
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            authorships=authorships,
            institutions=institutions,
            year=work.get("publication_year"),
            venue=venue,
            citation_count=work.get("cited_by_count") or 0,
            references=references,
            referenced_works=references,
            concepts=concepts,
            topics=topics,
            primary_topic=primary_topic,
            keywords=keywords,
            content_hash=content_hash,
            url=openalex_url,
            raw_metadata={
                "openalex_id": openalex_id,
                "publication_date": work.get("publication_date"),
                "updated_date": work.get("updated_date"),
                "counts_by_year": work.get("counts_by_year") or [],
                "open_access": work.get("open_access") or {},
                "related_works": work.get("related_works") or [],
            },
        )

    def _parse_authorships(
        self,
        openalex_authorships: list[dict[str, Any]],
    ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
        author_names: list[str] = []
        authorships: list[dict[str, Any]] = []
        institutions_by_id: dict[str, dict[str, Any]] = {}

        for position, authorship in enumerate(openalex_authorships):
            author = authorship.get("author") or {}
            name = author.get("display_name") or ""
            openalex_id = (author.get("id") or "").rstrip("/").split("/")[-1] or None
            if name:
                author_names.append(name)

            institution_ids: list[str] = []
            for institution in authorship.get("institutions") or []:
                institution_id = (institution.get("id") or "").rstrip("/").split("/")[-1]
                if not institution_id:
                    continue
                institution_ids.append(institution_id)
                institutions_by_id[institution_id] = {
                    "id": institution_id,
                    "openalex_id": institution_id,
                    "name": institution.get("display_name") or "",
                    "country": institution.get("country_code"),
                    "ror": institution.get("ror"),
                    "type": institution.get("type"),
                }

            if name:
                authorships.append(
                    {
                        "id": openalex_id or self._stable_id("author", name),
                        "openalex_id": openalex_id,
                        "name": name,
                        "position": position,
                        "institutions": institution_ids,
                        "is_corresponding": bool(authorship.get("is_corresponding")),
                        "raw_author_position": authorship.get("author_position"),
                    }
                )

        return author_names, authorships, list(institutions_by_id.values())

    def _parse_named_scores(self, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parsed = []
        for value in values:
            name = value.get("display_name") or value.get("name")
            if not name:
                continue
            parsed.append(
                {
                    "id": (value.get("id") or "").rstrip("/").split("/")[-1] or self._stable_id("concept", name),
                    "name": name,
                    "score": value.get("score"),
                    "level": value.get("level"),
                    "wikidata": value.get("wikidata"),
                }
            )
        return parsed

    def _parse_topic(self, topic: dict[str, Any] | None) -> dict[str, Any] | None:
        if not topic:
            return None
        name = topic.get("display_name") or topic.get("name")
        if not name:
            return None
        return {
            "id": (topic.get("id") or "").rstrip("/").split("/")[-1] or self._stable_id("topic", name),
            "name": name,
            "score": topic.get("score"),
            "subfield": topic.get("subfield"),
            "field": topic.get("field"),
            "domain": topic.get("domain"),
        }

    def _parse_venue(self, primary_location: dict[str, Any]) -> str | None:
        source = primary_location.get("source") or {}
        return source.get("display_name")

    def _normalize_doi(self, doi: str | None) -> str | None:
        if not doi:
            return None
        return doi.replace("https://doi.org/", "").replace("http://dx.doi.org/", "").lower()

    def _stable_id(self, prefix: str, value: str) -> str:
        return f"{prefix}:{hashlib.sha256(value.lower().strip().encode('utf-8')).hexdigest()[:16]}"

    def _reconstruct_abstract(self, inverted_index: dict[str, list[int]]) -> str:
        if not inverted_index:
            return ""

        position_word: dict[int, str] = {}
        for word, positions in inverted_index.items():
            for position in positions:
                position_word[position] = word

        if not position_word:
            return ""

        return " ".join(position_word.get(i, "") for i in range(max(position_word) + 1)).strip()

    async def close(self) -> None:
        await self.client.aclose()
