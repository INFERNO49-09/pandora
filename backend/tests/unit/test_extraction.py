"""
Unit tests for the knowledge extraction engine.
Uses mocked NIM responses — no API calls made during tests.
"""
import pytest
from unittest.mock import AsyncMock, patch
from extraction.engine import KnowledgeExtractor
from models.types import RawPaper


MOCK_EXTRACTION_RESPONSE = """{
  "concepts": [
    {"name": "Graph Neural Networks", "domain": "Machine Learning", "confidence": 0.95},
    {"name": "Drug Discovery", "domain": "Cheminformatics", "confidence": 0.90}
  ],
  "methods": [
    {"name": "Message Passing", "category": "algorithm", "confidence": 0.88},
    {"name": "Graph Attention", "category": "architecture", "confidence": 0.85}
  ],
  "relations": [
    {"head": "Graph Neural Networks", "head_type": "concept", "relation": "USES",
     "tail": "Message Passing", "tail_type": "method", "confidence": 0.90},
    {"head": "Graph Neural Networks", "head_type": "concept", "relation": "IMPROVES",
     "tail": "Drug Discovery", "tail_type": "concept", "confidence": 0.85}
  ],
  "open_problems": [
    {"description": "Scalability to billion-node graphs remains unsolved",
     "problem_type": "limitation", "severity": "major"}
  ],
  "domains": ["Machine Learning", "Cheminformatics"]
}"""

SAMPLE_PAPER = RawPaper(
    source="arxiv",
    source_id="2301.12345",
    arxiv_id="2301.12345",
    title="Graph Neural Networks for Drug Discovery: A Survey",
    abstract=(
        "We survey recent advances in applying graph neural networks (GNNs) to drug discovery. "
        "GNNs leverage message passing algorithms to learn molecular representations. "
        "We demonstrate improvements over traditional methods on standard benchmarks. "
        "Scalability to billion-node graphs remains an open challenge."
    ),
    authors=["Alice Smith", "Bob Jones"],
    year=2023,
)


@pytest.mark.asyncio
async def test_extraction_returns_correct_structure():
    """Extraction should return well-typed ExtractionResult."""
    extractor = KnowledgeExtractor()

    with patch("extraction.engine.nim_chat", new_callable=AsyncMock) as mock_nim:
        mock_nim.return_value = MOCK_EXTRACTION_RESPONSE
        result = await extractor.extract(SAMPLE_PAPER)

    assert result.error is None
    assert len(result.concepts) == 2
    assert len(result.methods) == 2
    assert len(result.relations) == 2
    assert len(result.open_problems) == 1
    assert len(result.domains) == 2


@pytest.mark.asyncio
async def test_extraction_concept_names():
    extractor = KnowledgeExtractor()

    with patch("extraction.engine.nim_chat", new_callable=AsyncMock) as mock_nim:
        mock_nim.return_value = MOCK_EXTRACTION_RESPONSE
        result = await extractor.extract(SAMPLE_PAPER)

    concept_names = [c.name for c in result.concepts]
    assert "Graph Neural Networks" in concept_names
    assert "Drug Discovery" in concept_names


@pytest.mark.asyncio
async def test_extraction_skips_short_abstract():
    """Papers with abstracts < 50 chars should return early with error."""
    extractor = KnowledgeExtractor()
    paper = RawPaper(
        source="test",
        source_id="test-001",
        title="A Paper",
        abstract="Too short.",
    )

    result = await extractor.extract(paper)
    assert result.error is not None
    assert "short" in result.error.lower()


@pytest.mark.asyncio
async def test_extraction_handles_malformed_json():
    """Malformed LLM output should not crash — returns empty result."""
    extractor = KnowledgeExtractor()

    with patch("extraction.engine.nim_chat", new_callable=AsyncMock) as mock_nim:
        mock_nim.return_value = "Sorry, I cannot help with that."
        result = await extractor.extract(SAMPLE_PAPER)

    # Should not raise, should return error
    assert result.error is not None


@pytest.mark.asyncio
async def test_extraction_strips_markdown_fences():
    """LLM sometimes wraps JSON in markdown fences — should handle gracefully."""
    extractor = KnowledgeExtractor()
    fenced_response = f"```json\n{MOCK_EXTRACTION_RESPONSE}\n```"

    with patch("extraction.engine.nim_chat", new_callable=AsyncMock) as mock_nim:
        mock_nim.return_value = fenced_response
        result = await extractor.extract(SAMPLE_PAPER)

    assert result.error is None
    assert len(result.concepts) == 2


def test_paper_id_doi_priority():
    """Paper ID should prefer DOI over arXiv over hash."""
    extractor = KnowledgeExtractor()

    paper_with_doi = RawPaper(
        source="test", source_id="x",
        title="Test", abstract="test",
        doi="10.1234/test",
        arxiv_id="2301.99999",
    )
    assert extractor._compute_paper_id(paper_with_doi).startswith("doi:")

    paper_arxiv_only = RawPaper(
        source="test", source_id="x",
        title="Test", abstract="test",
        arxiv_id="2301.99999",
    )
    assert extractor._compute_paper_id(paper_arxiv_only).startswith("arxiv:")

    paper_no_ids = RawPaper(
        source="test", source_id="x",
        title="Test", abstract="test",
        year=2023,
    )
    assert extractor._compute_paper_id(paper_no_ids).startswith("hash:")


def test_json_parse_trailing_comma():
    """_parse_json should handle trailing commas."""
    extractor = KnowledgeExtractor()
    json_with_trailing = '{"concepts": [{"name": "GNN",}], "methods": [],}'
    result = extractor._parse_json(json_with_trailing)
    assert result is not None
    assert "concepts" in result
