"""
Ingestion API — paper upload and topic seeding.
"""
import hashlib
import io
import re
from fastapi import APIRouter, HTTPException, BackgroundTasks, UploadFile, File, Form
from pydantic import BaseModel
from knowledge_graph.client import run_query
from ingestion.tasks import seed_topic, ingest_paper

router = APIRouter(prefix="/ingest", tags=["ingestion"])

MAX_PDF_BYTES = 50 * 1024 * 1024   # 50 MB


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


# ── PDF PARSING HELPERS ───────────────────────────────────────────────────────

def _extract_pdf_text(pdf_bytes: bytes) -> tuple[str, dict]:
    """
    Extract raw text and metadata from a PDF.
    Returns (full_text, metadata_dict).
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    raw_meta = reader.metadata or {}

    # Many PDF generators (LaTeX, ReportLab, Word) write placeholder junk
    # like "untitled", "anonymous", "unspecified" instead of leaving fields
    # empty. Treat these as absent so they don't override real content.
    _JUNK_VALUES = {
        "untitled", "anonymous", "unspecified", "unknown", "n/a", "none",
        "default", "user", "microsoft word", "(anonymous)",
    }

    def _clean(value: str) -> str:
        v = (value or "").strip()
        return "" if v.lower() in _JUNK_VALUES else v

    # Collect text page by page (first 20 pages is enough for abstract + intro)
    pages_text = []
    for page in reader.pages[:20]:
        try:
            pages_text.append(page.extract_text() or "")
        except Exception:
            pages_text.append("")

    full_text = "\n".join(pages_text)
    return full_text, {
        "title":   _clean(raw_meta.get("/Title", "")),
        "author":  _clean(raw_meta.get("/Author", "")),
        "subject": _clean(raw_meta.get("/Subject", "")),
        "creator": _clean(raw_meta.get("/Creator", "")),
    }


def _parse_paper_fields(text: str, pdf_meta: dict) -> dict:
    """
    Heuristically extract title, abstract, authors, year from raw PDF text.
    Falls back to PDF metadata where possible.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]

    # ── title ──────────────────────────────────────────────────────────────
    title = pdf_meta.get("title", "").strip()
    if not title and lines:
        # First non-trivial line is usually the title (longer than 10 chars,
        # not purely numeric, not a common header word)
        for line in lines[:15]:
            if (len(line) > 15
                    and not re.match(r"^[\d\s\.\-]+$", line)
                    and line.lower() not in {"abstract", "introduction", "references"}):
                title = line
                break
    title = title[:300]  # hard cap

    # ── authors ────────────────────────────────────────────────────────────
    authors: list[str] = []
    raw_author = pdf_meta.get("author", "").strip()
    if raw_author:
        # PDF metadata may use comma or semicolon separation
        authors = [a.strip() for a in re.split(r"[,;]", raw_author) if a.strip()]
    else:
        # Scan lines near the title for an author-ish pattern:
        # "Firstname Lastname, Firstname2 Lastname2" with commas
        for line in lines[1:10]:
            # Author lines tend to have 2–6 "words" and no lowercase-only words
            # that would suggest it's a sentence
            parts = line.split(",")
            if 2 <= len(parts) <= 8 and all(
                re.match(r"^[A-Z][a-zA-Z\.\-\s]+$", p.strip()) for p in parts if p.strip()
            ):
                authors = [p.strip() for p in parts if p.strip()]
                break

    # ── year ───────────────────────────────────────────────────────────────
    year: int | None = None
    year_matches = re.findall(r"\b(19\d{2}|20[012]\d)\b", text[:3000])
    if year_matches:
        # Pick the most-frequently occurring plausible year near the start
        from collections import Counter
        counts = Counter(int(y) for y in year_matches)
        year = counts.most_common(1)[0][0]

    # ── abstract ───────────────────────────────────────────────────────────
    abstract = ""
    abstract_match = re.search(
        r"(?:^|\n)\s*[Aa]bstract[\.\—\-\s]*\n+([\s\S]{100,3000?})(?=\n\s*(?:[1I]\s*[\.\-]?\s*[Ii]ntroduction|[Kk]eywords|1\s+Introduction)|\Z)",
        text,
    )
    if abstract_match:
        abstract = " ".join(abstract_match.group(1).split())
    else:
        # Fallback: grab a ~500-char chunk after detecting "abstract" keyword
        lower = text.lower()
        idx = lower.find("abstract")
        if idx != -1:
            chunk = text[idx + 8: idx + 2500]
            # Stop at next section heading
            stop = re.search(r"\n\s*(?:\d+[\.\s]|introduction|keywords)", chunk, re.I)
            abstract = " ".join(chunk[:stop.start() if stop else 1500].split())

    # ── DOI ────────────────────────────────────────────────────────────────
    doi: str | None = None
    doi_match = re.search(r"\b(10\.\d{4,}/[^\s\"\'<>]+)", text[:3000])
    if doi_match:
        doi = doi_match.group(1).rstrip(".,;)")

    return {
        "title":    title,
        "abstract": abstract[:5000],
        "authors":  authors,
        "year":     year,
        "doi":      doi,
    }


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

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
    Ingest a single paper manually via JSON.
    """
    from models.types import RawPaper

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


@router.post("/pdf/parse")
async def parse_pdf(file: UploadFile = File(...)):
    """
    Parse a PDF and return extracted fields WITHOUT ingesting.
    Use this to preview what will be ingested before confirming.
    Returns: title, abstract, authors, year, doi, page_count.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF (.pdf)")

    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"PDF too large (max {MAX_PDF_BYTES // 1024 // 1024} MB)")
    if len(content) < 100:
        raise HTTPException(status_code=400, detail="PDF appears to be empty")

    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

    text, meta = _extract_pdf_text(content)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted from this PDF. It may be a scanned image — try copy-pasting the abstract manually via /ingest/paper.",
        )

    fields = _parse_paper_fields(text, meta)

    return {
        "filename":   file.filename,
        "page_count": page_count,
        "parsed":     fields,
        "text_preview": text[:500].strip(),   # first 500 chars for user review
    }


@router.post("/pdf")
async def ingest_pdf(
    file: UploadFile = File(...),
    # Optional overrides — the user can fix anything the parser got wrong
    title_override:    str | None = Form(None),
    abstract_override: str | None = Form(None),
    authors_override:  str | None = Form(None),   # comma-separated
    year_override:     int | None = Form(None),
    venue:             str | None = Form(None),
):
    """
    Upload a PDF and ingest it directly into the knowledge graph.
    Extracts text, parses metadata, then queues the standard ingestion pipeline.

    Accepts optional form fields to override parsed values.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF (.pdf)")

    content = await file.read()
    if len(content) > MAX_PDF_BYTES:
        raise HTTPException(status_code=413, detail=f"PDF too large (max {MAX_PDF_BYTES // 1024 // 1024} MB)")

    # Extract text
    try:
        text, meta = _extract_pdf_text(content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Could not read PDF: {e}")

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="No text could be extracted. The PDF may be a scanned image — use /ingest/paper and paste the abstract manually.",
        )

    # Parse fields
    fields = _parse_paper_fields(text, meta)

    # Apply user overrides
    title    = (title_override    or fields["title"]   or "").strip()
    abstract = (abstract_override or fields["abstract"] or "").strip()
    authors  = (
        [a.strip() for a in authors_override.split(",") if a.strip()]
        if authors_override
        else fields["authors"]
    )
    year = year_override or fields["year"]
    doi  = fields["doi"]

    if not title:
        raise HTTPException(status_code=422, detail="Could not detect a title. Pass title_override.")
    if not abstract or len(abstract) < 50:
        raise HTTPException(
            status_code=422,
            detail="Could not extract a usable abstract (need ≥ 50 chars). Pass abstract_override.",
        )

    from models.types import RawPaper

    paper = RawPaper(
        source="pdf_upload",
        source_id=hashlib.sha256((title + (doi or "")).encode()).hexdigest()[:16],
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        doi=doi,
        venue=venue,
        citation_count=0,
    )

    task = ingest_paper.apply_async(
        args=[paper.model_dump()],
        queue="ingestion",
    )

    return {
        "job_id":     task.id,
        "status":     "queued",
        "status_url": f"/api/v1/ingest/jobs/{task.id}",
        "parsed": {
            "title":    title,
            "abstract": abstract[:300] + ("…" if len(abstract) > 300 else ""),
            "authors":  authors,
            "year":     year,
            "doi":      doi,
        },
        "message": f"'{title[:60]}' queued for knowledge extraction and graph ingestion.",
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
