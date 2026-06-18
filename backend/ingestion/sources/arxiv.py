"""
arXiv source client using the arXiv API.
Best for CS/ML/Physics papers with full abstracts.
Rate limit: 3 requests/second.
"""
import asyncio
import xml.etree.ElementTree as ET
import httpx
from loguru import logger
from models.types import RawPaper


ARXIV_BASE = "http://export.arxiv.org/api"
ARXIV_NS = "http://www.w3.org/2005/Atom"

# arXiv category groups for filtering
CS_CATEGORIES = [
    "cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.IR",
    "cs.NE", "cs.RO", "cs.HC", "stat.ML",
]


class ArXivClient:
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=ARXIV_BASE,
            timeout=30.0,
        )

    async def fetch_papers(
        self,
        query: str,
        categories: list[str] | None = None,
        max_results: int = 1000,
        start: int = 0,
    ) -> list[RawPaper]:
        """Fetch papers from arXiv matching query and optional category filter."""
        papers = []
        batch_size = 100
        offset = start

        # Build search query
        search_query = f"all:{query}"
        if categories:
            cat_filter = " OR ".join(f"cat:{c}" for c in categories)
            search_query = f"({search_query}) AND ({cat_filter})"

        while len(papers) < max_results:
            params = {
                "search_query": search_query,
                "start": offset,
                "max_results": min(batch_size, max_results - len(papers)),
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            }

            try:
                response = await self.client.get("/query", params=params)
                response.raise_for_status()
                batch = self._parse_atom(response.text)
            except Exception as e:
                logger.error(f"arXiv fetch error: {e}")
                break

            if not batch:
                break

            papers.extend(batch)
            offset += len(batch)

            # Respect rate limit
            await asyncio.sleep(0.4)

        return papers[:max_results]

    def _parse_atom(self, xml_text: str) -> list[RawPaper]:
        """Parse Atom XML response from arXiv API."""
        papers = []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.error(f"XML parse error: {e}")
            return []

        ns = {"atom": ARXIV_NS}
        entries = root.findall("atom:entry", ns)

        for entry in entries:
            try:
                paper = self._parse_entry(entry, ns)
                if paper:
                    papers.append(paper)
            except Exception as e:
                logger.warning(f"Failed to parse arXiv entry: {e}")

        return papers

    def _parse_entry(self, entry, ns: dict) -> RawPaper | None:
        title_el = entry.find("atom:title", ns)
        abstract_el = entry.find("atom:summary", ns)
        id_el = entry.find("atom:id", ns)

        if title_el is None or id_el is None:
            return None

        # Extract arXiv ID from URL
        arxiv_url = id_el.text or ""
        arxiv_id = arxiv_url.split("/abs/")[-1].strip()

        title = (title_el.text or "").strip().replace("\n", " ")
        abstract = (abstract_el.text or "").strip().replace("\n", " ") if abstract_el else ""

        # Authors
        authors = []
        for author_el in entry.findall("atom:author", ns):
            name_el = author_el.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        # Year from published date
        published_el = entry.find("atom:published", ns)
        year = None
        if published_el is not None and published_el.text:
            try:
                year = int(published_el.text[:4])
            except (ValueError, IndexError):
                pass

        # DOI link if available
        doi = None
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "doi":
                doi = link.get("href", "").replace("http://dx.doi.org/", "")

        return RawPaper(
            source="arxiv",
            source_id=arxiv_id,
            arxiv_id=arxiv_id,
            doi=doi,
            title=title,
            abstract=abstract,
            authors=authors,
            year=year,
            url=arxiv_url,
            pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        )

    async def close(self):
        await self.client.aclose()
