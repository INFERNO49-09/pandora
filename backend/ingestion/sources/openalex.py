"""
OpenAlex source client.
OpenAlex is the best starting point: 250M+ works, fully open API,
rich metadata, no auth required for basic access.
Docs: https://docs.openalex.org
"""
import asyncio
import hashlib
from datetime import datetime, timedelta
import httpx
from loguru import logger
from models.types import RawPaper


OPENALEX_BASE = "https://api.openalex.org"
# Polite pool: add your email for higher rate limits
POLITE_EMAIL = "pandora@example.com"


class OpenAlexClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=OPENALEX_BASE,
            headers={"User-Agent": f"Pandora/1.0 (mailto:{POLITE_EMAIL})"},
            timeout=30.0,
        )

    async def fetch_papers_by_topic(
        self,
        topic: str,
        max_results: int = 1000,
        from_date: str | None = None,
    ) -> list[RawPaper]:
        """
        Fetch papers matching a topic keyword from OpenAlex.
        Uses cursor-based pagination.
        """
        papers = []
        cursor = "*"
        per_page = min(200, max_results)

        while len(papers) < max_results:
            params = {
                "search": topic,
                "per-page": per_page,
                "cursor": cursor,
                "select": (
                    "id,title,abstract_inverted_index,authorships,"
                    "publication_year,doi,primary_location,cited_by_count,"
                    "referenced_works,keywords,open_access"
                ),
            }
            if from_date:
                params["filter"] = f"from_publication_date:{from_date}"

            try:
                response = await self.client.get("/works", params=params)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.error(f"OpenAlex fetch error: {e}")
                break

            results = data.get("results", [])
            if not results:
                break

            for work in results:
                paper = self._parse_work(work)
                if paper:
                    papers.append(paper)

            # Pagination
            meta = data.get("meta", {})
            cursor = meta.get("next_cursor")
            if not cursor:
                break

            # Rate limit: 10 req/s in polite pool
            await asyncio.sleep(0.1)

        logger.info(f"OpenAlex: fetched {len(papers)} papers for topic '{topic}'")
        return papers[:max_results]

    async def fetch_recent_papers(
        self,
        days_back: int = 7,
        domains: list[str] | None = None,
        max_results: int = 5000,
    ) -> list[RawPaper]:
        """Fetch recently published papers for continuous ingestion."""
        from_date = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
        topic = " OR ".join(domains) if domains else "machine learning"
        return await self.fetch_papers_by_topic(
            topic=topic,
            max_results=max_results,
            from_date=from_date,
        )

    def _parse_work(self, work: dict) -> RawPaper | None:
        """Parse OpenAlex work object into RawPaper."""
        title = work.get("title", "").strip()
        if not title:
            return None

        # Reconstruct abstract from inverted index
        abstract = self._reconstruct_abstract(
            work.get("abstract_inverted_index") or {}
        )

        # Parse authors
        authors = []
        for authorship in work.get("authorships", []):
            author = authorship.get("author", {})
            display_name = author.get("display_name", "")
            if display_name:
                authors.append(display_name)

        # Extract venue
        venue = None
        primary = work.get("primary_location") or {}
        source = primary.get("source") or {}
        venue = source.get("display_name")

        # Extract keywords
        keywords = [k.get("display_name", "") for k in work.get("keywords", [])]

        # Extract references (OpenAlex IDs)
        references = [
            ref.split("/")[-1]  # strip URL prefix
            for ref in work.get("referenced_works", [])
            if ref
        ]

        doi = work.get("doi", "")
        if doi:
            doi = doi.replace("https://doi.org/", "")

        openalex_id = work.get("id", "").split("/")[-1]

        return RawPaper(
            source="openalex",
            source_id=openalex_id,
            doi=doi or None,
            title=title,
            abstract=abstract,
            authors=authors,
            year=work.get("publication_year"),
            venue=venue,
            citation_count=work.get("cited_by_count", 0),
            references=references[:100],  # cap to avoid massive payloads
            keywords=keywords,
        )

    def _reconstruct_abstract(self, inverted_index: dict) -> str:
        """
        OpenAlex stores abstracts as inverted indexes: {word: [positions]}.
        Reconstruct the original text.
        """
        if not inverted_index:
            return ""

        # Build position -> word mapping
        position_word = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                position_word[pos] = word

        if not position_word:
            return ""

        max_pos = max(position_word.keys())
        words = [position_word.get(i, "") for i in range(max_pos + 1)]
        return " ".join(w for w in words if w)

    async def close(self):
        await self.client.aclose()
