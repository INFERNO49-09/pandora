"""
Unit tests for CARGS gap scoring.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from discovery.cargs import CARGSScorer, WEIGHTS


@pytest.fixture
def scorer():
    return CARGSScorer()


@pytest.mark.asyncio
async def test_score_returns_valid_range(scorer):
    """All score components should be in [0, 1]."""
    with patch("discovery.cargs.run_query", new_callable=AsyncMock) as mock_q, \
         patch("discovery.cargs.nim_embed_single", new_callable=AsyncMock) as mock_emb:

        # Mock novelty query: 2 bridge papers, sizes 100 and 200
        mock_q.side_effect = [
            # novelty call
            [{"size_a": 100, "size_b": 200, "bridge_count": 2}],
            # impact call
            [{"domain_id": "d1", "avg_citations": 50.0}, {"domain_id": "d2", "avg_citations": 80.0}],
            # feasibility call
            [{"shared_count": 10}],
            # velocity call
            [{"domain_id": "d1", "recent_count": 150}, {"domain_id": "d2", "recent_count": 200}],
        ]
        # semantic: return unit vectors → cosine = 1.0
        mock_emb.side_effect = [[1.0, 0.0], [1.0, 0.0]]

        score = await scorer.score_domain_pair("d1", "d2", "Machine Learning", "Drug Discovery")

    assert 0.0 <= score.opportunity_score <= 1.0
    assert 0.0 <= score.novelty_score <= 1.0
    assert 0.0 <= score.impact_score <= 1.0
    assert 0.0 <= score.feasibility_score <= 1.0
    assert 0.0 <= score.velocity_score <= 1.0
    assert 0.0 <= score.embedding_proximity <= 1.0


@pytest.mark.asyncio
async def test_novelty_high_when_few_bridges(scorer):
    """A domain pair with very few bridge papers should get high novelty."""
    with patch("discovery.cargs.run_query", new_callable=AsyncMock) as mock_q, \
         patch("discovery.cargs.nim_embed_single", new_callable=AsyncMock) as mock_emb:

        mock_q.side_effect = [
            [{"size_a": 1000, "size_b": 500, "bridge_count": 0}],  # novelty: 0 bridges
            [{"domain_id": "d1", "avg_citations": 30.0}, {"domain_id": "d2", "avg_citations": 40.0}],
            [{"shared_count": 5}],
            [{"domain_id": "d1", "recent_count": 50}, {"domain_id": "d2", "recent_count": 60}],
        ]
        mock_emb.side_effect = [[1.0, 0.0], [0.9, 0.1]]

        score = await scorer.score_domain_pair("d1", "d2", "Quantum Computing", "Oncology")

    assert score.novelty_score > 0.8, f"Expected high novelty, got {score.novelty_score}"


@pytest.mark.asyncio
async def test_novelty_low_when_many_bridges(scorer):
    """A domain pair with many bridge papers should get low novelty."""
    with patch("discovery.cargs.run_query", new_callable=AsyncMock) as mock_q, \
         patch("discovery.cargs.nim_embed_single", new_callable=AsyncMock) as mock_emb:

        mock_q.side_effect = [
            [{"size_a": 100, "size_b": 100, "bridge_count": 500}],  # tons of bridges
            [{"domain_id": "d1", "avg_citations": 30.0}, {"domain_id": "d2", "avg_citations": 40.0}],
            [{"shared_count": 5}],
            [{"domain_id": "d1", "recent_count": 50}, {"domain_id": "d2", "recent_count": 60}],
        ]
        mock_emb.side_effect = [[1.0, 0.0], [0.9, 0.1]]

        score = await scorer.score_domain_pair("d1", "d2", "ML", "Deep Learning")

    assert score.novelty_score < 0.2, f"Expected low novelty, got {score.novelty_score}"


def test_weights_sum_to_one():
    """Weight components must sum to 1.0 for the composite score to be valid."""
    total = sum(WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9, f"Weights sum to {total}, expected 1.0"


def test_cosine_similarity_unit_vectors(scorer):
    """Identical vectors should have similarity 1.0."""
    v = [0.5, 0.5, 0.5, 0.5]
    assert abs(scorer._cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal(scorer):
    """Orthogonal vectors should have similarity 0.0."""
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    assert abs(scorer._cosine_similarity(v1, v2)) < 1e-6
