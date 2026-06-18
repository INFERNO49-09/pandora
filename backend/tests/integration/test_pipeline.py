"""
Integration tests.

These tests require real services running (Neo4j, Qdrant, Postgres, Redis).
Run with: pytest tests/integration -v --timeout=60

They test the complete data flow:
  Paper → Extraction → Graph Write → CARGS → Opportunity
"""
import asyncio
import os
import pytest

# Skip all integration tests if services not available
pytestmark = pytest.mark.skipif(
    os.getenv("INTEGRATION_TESTS", "0") != "1",
    reason="Set INTEGRATION_TESTS=1 to run integration tests",
)


# ── FIXTURES ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def neo4j_ready():
    """Verify Neo4j is reachable."""
    from knowledge_graph.client import run_query
    result = await run_query("RETURN 1 AS ok")
    assert result and result[0]["ok"] == 1
    return True


@pytest.fixture(scope="session")
async def qdrant_ready():
    """Verify Qdrant is reachable."""
    from vector_store.client import get_qdrant
    client = get_qdrant()
    collections = await client.get_collections()
    return collections is not None


@pytest.fixture(scope="session")
async def schema_ready(neo4j_ready):
    """Ensure Neo4j schema is initialized."""
    from knowledge_graph.client import setup_schema
    await setup_schema()
    return True


@pytest.fixture(scope="session")
async def collections_ready(qdrant_ready):
    """Ensure Qdrant collections exist."""
    from vector_store.client import setup_collections
    await setup_collections()
    return True


SAMPLE_PAPER_DICT = {
    "source": "test",
    "source_id": "test-integration-001",
    "title": "Graph Neural Networks for Scientific Discovery: A Survey",
    "abstract": (
        "We survey recent advances in applying graph neural networks (GNNs) "
        "to scientific discovery tasks. GNNs leverage message passing algorithms "
        "to learn representations from molecular, citation, and knowledge graphs. "
        "Applications span drug discovery, material science, and protein folding. "
        "We identify key limitations: scalability to billion-node graphs remains "
        "an open challenge. Future work should explore federated training of GNNs "
        "on distributed scientific datasets."
    ),
    "authors": ["Test Author A", "Test Author B"],
    "year": 2024,
    "doi": None,
    "arxiv_id": "2401.99999",
    "venue": "Test Conference",
    "citation_count": 42,
    "keywords": ["graph neural networks", "scientific discovery"],
    "references": [],
    "url": None,
    "pdf_url": None,
}


# ── INGESTION PIPELINE ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extraction_pipeline(schema_ready):
    """Test that extraction produces valid structured output."""
    from models.types import RawPaper
    from extraction.engine import KnowledgeExtractor

    paper = RawPaper(**SAMPLE_PAPER_DICT)
    extractor = KnowledgeExtractor()
    result = await extractor.extract(paper)

    assert result.paper_id is not None
    # Should extract at least some concepts
    assert len(result.concepts) >= 1, f"Expected concepts, got: {result.concepts}"
    # Should identify at least one domain
    assert len(result.domains) >= 1, f"Expected domains, got: {result.domains}"


@pytest.mark.asyncio
async def test_graph_write_pipeline(schema_ready):
    """Test full paper → graph write round-trip."""
    from models.types import RawPaper, ExtractionResult, ExtractedConcept
    from knowledge_graph.graph_writer import GraphWriter
    from knowledge_graph.client import run_query

    paper = RawPaper(**SAMPLE_PAPER_DICT)
    extraction = ExtractionResult(
        paper_id="arxiv:2401.99999",
        concepts=[
            ExtractedConcept(name="Graph Neural Networks", domain="Machine Learning"),
            ExtractedConcept(name="Scientific Discovery", domain="AI"),
        ],
        domains=["Machine Learning", "Scientific Discovery"],
    )

    writer = GraphWriter()
    paper_id = await writer.write_paper_with_extraction(paper, extraction)

    assert paper_id == "arxiv:2401.99999"

    # Verify paper exists in graph
    result = await run_query(
        "MATCH (p:Paper {id: $id}) RETURN p.title AS title",
        params={"id": paper_id},
    )
    assert result, "Paper not found in Neo4j after write"
    assert "Graph Neural Networks" in result[0]["title"]

    # Verify concepts were linked
    concepts = await run_query(
        """
        MATCH (p:Paper {id: $id})-[:USES]->(c:Concept)
        RETURN c.canonical_name AS name
        """,
        params={"id": paper_id},
    )
    concept_names = [c["name"] for c in concepts]
    assert "Graph Neural Networks" in concept_names


@pytest.mark.asyncio
async def test_domain_write_and_query(schema_ready):
    """Domains should be created and linked to papers."""
    from knowledge_graph.client import run_query

    result = await run_query(
        """
        MATCH (p:Paper {id: 'arxiv:2401.99999'})-[:IN_DOMAIN]->(d:Domain)
        RETURN d.name AS domain
        """
    )
    assert len(result) >= 1, "No domains linked to test paper"


# ── VECTOR STORE ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embedding_roundtrip(collections_ready):
    """Embed text → store → retrieve → verify similarity."""
    from core.nim_client import nim_embed_single
    from vector_store.client import upsert_vectors, search_similar

    text = "Graph neural networks for drug discovery"
    vec = await nim_embed_single(f"Concept: {text}")

    assert len(vec) > 0, "Embedding returned empty vector"
    assert abs(sum(x*x for x in vec) ** 0.5 - 1.0) < 0.1, "Embedding should be roughly normalized"

    # Upsert
    await upsert_vectors("concepts", [{
        "id":      999999999,
        "vector":  vec,
        "payload": {"node_id": "test-gnn-drug", "name": text, "type": "Concept"},
    }])

    # Retrieve by similarity
    hits = await search_similar("concepts", vec, top_k=3, score_threshold=0.5)
    assert len(hits) >= 1
    top_hit = hits[0]
    assert top_hit["score"] > 0.95, f"Expected high self-similarity, got {top_hit['score']}"


# ── DISCOVERY ENGINE ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cargs_scoring(schema_ready):
    """CARGS should return valid scores for domain pairs in the graph."""
    from knowledge_graph.client import run_query
    from discovery.cargs import CARGSScorer

    # Get two domains that exist
    domains = await run_query(
        "MATCH (d:Domain) WHERE d.paper_count >= 1 RETURN d.id AS id, d.name AS name LIMIT 2"
    )
    if len(domains) < 2:
        pytest.skip("Need at least 2 domains in graph for CARGS test")

    scorer = CARGSScorer()
    score = await scorer.score_domain_pair(
        domain_a_id=domains[0]["id"],
        domain_b_id=domains[1]["id"],
        domain_a_name=domains[0]["name"],
        domain_b_name=domains[1]["name"],
    )

    assert 0.0 <= score.opportunity_score <= 1.0
    assert 0.0 <= score.novelty_score <= 1.0
    assert 0.0 <= score.feasibility_score <= 1.0


@pytest.mark.asyncio
async def test_graph_search(schema_ready):
    """Full-text search should return results for known terms."""
    from knowledge_graph.client import run_query

    # This depends on the full-text index existing
    try:
        results = await run_query(
            """
            CALL db.index.fulltext.queryNodes('paper_fulltext', 'graph neural')
            YIELD node, score
            RETURN node.title AS title, score
            LIMIT 5
            """
        )
        # May return empty if no papers ingested — that's OK
        assert isinstance(results, list)
    except Exception as e:
        if "index" in str(e).lower():
            pytest.skip("Full-text index not yet created — run setup_schema first")
        raise


# ── CLEANUP ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cleanup(schema_ready):
    """Remove test data created during integration tests."""
    from knowledge_graph.client import run_query

    await run_query(
        "MATCH (p:Paper {id: 'arxiv:2401.99999'}) DETACH DELETE p",
        write=True,
    )
    # Verify gone
    result = await run_query(
        "MATCH (p:Paper {id: 'arxiv:2401.99999'}) RETURN count(p) AS cnt"
    )
    assert result[0]["cnt"] == 0
