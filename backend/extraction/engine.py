"""
Knowledge extraction engine.
Uses NVIDIA NIM (Llama 3.1 70B) to extract structured knowledge
from paper abstracts and titles.
"""
import json
import hashlib
from loguru import logger
from core.nim_client import nim_chat
from models.types import (
    RawPaper,
    ExtractionResult,
    ExtractedConcept,
    ExtractedMethod,
    ExtractedRelation,
    ExtractedProblem,
)


EXTRACTION_SYSTEM_PROMPT = """You are a scientific knowledge extraction system.
Your job is to extract structured information from scientific paper abstracts.
Always respond with valid JSON only. No prose, no markdown, no explanation.
Be conservative: only extract entities that are clearly mentioned in the text.
Do not infer or hallucinate entities that are not explicitly stated."""


EXTRACTION_PROMPT = """Extract scientific knowledge from this paper.

Title: {title}
Abstract: {abstract}

Return a JSON object with exactly these fields:
{{
  "concepts": [
    {{"name": "...", "domain": "...", "confidence": 0.9}}
  ],
  "methods": [
    {{"name": "...", "category": "architecture|algorithm|training|evaluation|framework", "confidence": 0.9}}
  ],
  "relations": [
    {{"head": "...", "head_type": "concept|method|dataset", "relation": "USES|IMPROVES|EXTENDS|INTRODUCES|EVALUATED_ON", "tail": "...", "tail_type": "concept|method|dataset", "confidence": 0.8}}
  ],
  "open_problems": [
    {{"description": "...", "problem_type": "limitation|open_problem|future_work", "severity": "major|minor"}}
  ],
  "domains": ["...", "..."]
}}

Rules:
- concepts: scientific ideas, phenomena, technical areas (not author names, not venue names)
- methods: algorithms, architectures, frameworks, training techniques
- relations: only between entities you extracted above
- open_problems: limitations or future directions explicitly stated in the abstract
- domains: broad research areas (e.g. "Computer Vision", "Natural Language Processing", "Drug Discovery")
- Keep names concise and canonical (e.g. "Graph Neural Networks" not "graph-based neural network models")
- Maximum 10 concepts, 5 methods, 8 relations, 3 open_problems, 3 domains"""


class KnowledgeExtractor:
    async def extract(self, paper: RawPaper) -> ExtractionResult:
        """
        Extract structured knowledge from a single paper.
        Returns ExtractionResult — empty lists on failure, never raises.
        """
        paper_id = self._compute_paper_id(paper)

        # Skip papers with no abstract
        if not paper.abstract or len(paper.abstract) < 50:
            return ExtractionResult(
                paper_id=paper_id,
                error="Abstract too short for extraction",
            )

        try:
            raw = await nim_chat(
                messages=[{
                    "role": "user",
                    "content": EXTRACTION_PROMPT.format(
                        title=paper.title,
                        abstract=paper.abstract[:3000],  # cap for token budget
                    ),
                }],
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.05,
                max_tokens=1500,
            )

            data = self._parse_json(raw)
            if not data:
                return ExtractionResult(
                    paper_id=paper_id,
                    error="JSON parse failed",
                )

            return ExtractionResult(
                paper_id=paper_id,
                concepts=[
                    ExtractedConcept(
                        name=c.get("name", ""),
                        domain=c.get("domain"),
                        confidence=float(c.get("confidence", 0.8)),
                    )
                    for c in data.get("concepts", [])
                    if c.get("name")
                ],
                methods=[
                    ExtractedMethod(
                        name=m.get("name", ""),
                        category=m.get("category"),
                        confidence=float(m.get("confidence", 0.8)),
                    )
                    for m in data.get("methods", [])
                    if m.get("name")
                ],
                relations=[
                    ExtractedRelation(
                        head=r.get("head", ""),
                        head_type=r.get("head_type", "concept"),
                        relation=r.get("relation", "RELATED_TO"),
                        tail=r.get("tail", ""),
                        tail_type=r.get("tail_type", "concept"),
                        confidence=float(r.get("confidence", 0.7)),
                    )
                    for r in data.get("relations", [])
                    if r.get("head") and r.get("tail")
                ],
                open_problems=[
                    ExtractedProblem(
                        description=p.get("description", ""),
                        problem_type=p.get("problem_type", "open_problem"),
                        severity=p.get("severity", "minor"),
                    )
                    for p in data.get("open_problems", [])
                    if p.get("description")
                ],
                domains=data.get("domains", []),
            )

        except Exception as e:
            logger.error(f"Extraction failed for paper '{paper.title[:60]}': {e}")
            return ExtractionResult(paper_id=paper_id, error=str(e))

    def _compute_paper_id(self, paper: RawPaper) -> str:
        """
        Stable paper ID. Precedence: DOI > arXiv ID > hash of title+year.
        """
        if paper.doi:
            return f"doi:{paper.doi.lower()}"
        if paper.arxiv_id:
            return f"arxiv:{paper.arxiv_id}"
        content = f"{paper.title.lower().strip()}:{paper.year}"
        return f"hash:{hashlib.sha256(content.encode()).hexdigest()[:16]}"

    def _parse_json(self, raw: str) -> dict | None:
        """
        Parse JSON from LLM output. Handles common issues:
        - Trailing commas
        - Markdown code fences
        - Extra text before/after JSON
        """
        if not raw:
            return None

        # Strip markdown fences
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        # Find JSON object boundaries
        start = text.find("{")
        end = text.rfind("}") + 1
        if start == -1 or end == 0:
            return None

        json_str = text[start:end]

        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            # Last resort: try to fix common issues
            try:
                import re
                # Remove trailing commas before ] or }
                fixed = re.sub(r",\s*([}\]])", r"\1", json_str)
                return json.loads(fixed)
            except Exception:
                logger.warning(f"Failed to parse JSON: {json_str[:200]}")
                return None


async def extract_batch(
    papers: list[RawPaper],
    concurrency: int = 5,
) -> list[ExtractionResult]:
    """
    Extract knowledge from a batch of papers with controlled concurrency.
    NIM handles rate limits, but we still cap parallel calls.
    """
    import asyncio
    semaphore = asyncio.Semaphore(concurrency)
    extractor = KnowledgeExtractor()

    async def extract_one(paper: RawPaper) -> ExtractionResult:
        async with semaphore:
            return await extractor.extract(paper)

    results = await asyncio.gather(*[extract_one(p) for p in papers])
    
    success = sum(1 for r in results if not r.error)
    logger.info(f"Extraction batch: {success}/{len(papers)} succeeded")
    return list(results)
