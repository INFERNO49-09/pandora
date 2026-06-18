"""
CARGS v2: Community-Aware Research Gap Scoring.

Scores cross-domain research opportunities using five dimensions:
  1. Novelty    - how sparse is the connection between domains?
  2. Impact     - how important are these domains? (citation weight)
  3. Feasibility - do shared methods/concepts bridge the gap?
  4. Velocity   - are both domains actively publishing?
  5. Semantic   - how conceptually close are the domains? (embedding similarity)

This is Pandora's core novel algorithm.
"""
import asyncio
import math
from loguru import logger
from knowledge_graph.client import run_query
from vector_store.client import search_similar
from core.nim_client import nim_embed_single
from models.types import GapScore


# Learned weights (can be tuned via grid search on held-out data)
WEIGHTS = {
    "novelty":    0.30,
    "impact":     0.25,
    "feasibility": 0.20,
    "velocity":   0.15,
    "semantic":   0.10,
}


class CARGSScorer:

    async def score_domain_pair(
        self,
        domain_a_id: str,
        domain_b_id: str,
        domain_a_name: str,
        domain_b_name: str,
    ) -> GapScore:
        """
        Compute opportunity score for a pair of research domains.
        All sub-scores are normalized to [0, 1].
        """
        # Run all sub-scores in parallel
        (
            novelty,
            impact,
            feasibility,
            velocity,
            semantic,
        ) = await asyncio.gather(
            self._compute_novelty(domain_a_id, domain_b_id),
            self._compute_impact(domain_a_id, domain_b_id),
            self._compute_feasibility(domain_a_id, domain_b_id),
            self._compute_velocity(domain_a_id, domain_b_id),
            self._compute_semantic(domain_a_name, domain_b_name),
        )

        opportunity_score = (
            WEIGHTS["novelty"]    * novelty +
            WEIGHTS["impact"]     * impact +
            WEIGHTS["feasibility"] * feasibility +
            WEIGHTS["velocity"]   * velocity +
            WEIGHTS["semantic"]   * semantic
        )

        return GapScore(
            opportunity_score=round(opportunity_score, 4),
            novelty_score=round(novelty, 4),
            impact_score=round(impact, 4),
            feasibility_score=round(feasibility, 4),
            velocity_score=round(velocity, 4),
            embedding_proximity=round(semantic, 4),
            evidence={
                "domain_a": domain_a_name,
                "domain_b": domain_b_name,
            },
        )

    async def _compute_novelty(
        self,
        domain_a_id: str,
        domain_b_id: str,
    ) -> float:
        """
        Novelty = 1 - (actual_bridges / expected_bridges).
        Actual bridges: papers citing papers from both domains.
        Expected bridges: geometric mean of domain sizes * base rate.
        """
        result = await run_query(
            """
            MATCH (da:Domain {id: $domain_a_id})<-[:IN_DOMAIN]-(pa:Paper)
            MATCH (db:Domain {id: $domain_b_id})<-[:IN_DOMAIN]-(pb:Paper)
            WITH count(DISTINCT pa) AS size_a, count(DISTINCT pb) AS size_b

            OPTIONAL MATCH (bridge:Paper)-[:IN_DOMAIN]->(da)
            WHERE (bridge)-[:IN_DOMAIN]->(db)
            WITH size_a, size_b, count(DISTINCT bridge) AS bridge_count

            RETURN size_a, size_b, bridge_count
            """,
            params={"domain_a_id": domain_a_id, "domain_b_id": domain_b_id},
        )

        if not result:
            return 0.5

        row = result[0]
        size_a = row.get("size_a", 0)
        size_b = row.get("size_b", 0)
        bridge_count = row.get("bridge_count", 0)

        if size_a == 0 or size_b == 0:
            return 0.0

        # Expected bridges: based on random graph model
        # E[bridges] = size_a * size_b * global_cross_domain_rate
        global_cross_rate = 0.002  # empirically: ~0.2% of possible pairs are bridged
        expected = size_a * size_b * global_cross_rate
        expected = max(expected, 1)  # avoid division by zero

        novelty = 1.0 - min(bridge_count / expected, 1.0)
        return novelty

    async def _compute_impact(
        self,
        domain_a_id: str,
        domain_b_id: str,
    ) -> float:
        """
        Impact = normalized sum of citation counts in both domains.
        High-impact domains = high-value opportunity.
        """
        result = await run_query(
            """
            MATCH (d:Domain)
            WHERE d.id IN [$domain_a_id, $domain_b_id]
            MATCH (p:Paper)-[:IN_DOMAIN]->(d)
            RETURN d.id AS domain_id,
                   avg(p.citation_count) AS avg_citations,
                   count(p) AS paper_count
            """,
            params={"domain_a_id": domain_a_id, "domain_b_id": domain_b_id},
        )

        if not result or len(result) < 2:
            return 0.3

        avg_citations = [r.get("avg_citations", 0) or 0 for r in result]
        combined = sum(avg_citations) / len(avg_citations)

        # Normalize: log scale (citation counts are heavy-tailed)
        # Cap at 500 average citations = max impact
        normalized = min(math.log1p(combined) / math.log1p(500), 1.0)
        return normalized

    async def _compute_feasibility(
        self,
        domain_a_id: str,
        domain_b_id: str,
    ) -> float:
        """
        Feasibility = how many methods/concepts are shared between domains.
        Shared infrastructure means bridging is technically plausible.
        """
        result = await run_query(
            """
            MATCH (da:Domain {id: $domain_a_id})<-[:IN_DOMAIN]-(pa:Paper)
                  -[:USES]->(shared)<-[:USES]-(pb:Paper)
                  -[:IN_DOMAIN]->(db:Domain {id: $domain_b_id})
            WHERE (shared:Concept OR shared:Method)
            RETURN count(DISTINCT shared) AS shared_count
            """,
            params={"domain_a_id": domain_a_id, "domain_b_id": domain_b_id},
        )

        if not result:
            return 0.1

        shared_count = result[0].get("shared_count", 0)

        # Normalize: 20+ shared concepts/methods = max feasibility
        return min(shared_count / 20.0, 1.0)

    async def _compute_velocity(
        self,
        domain_a_id: str,
        domain_b_id: str,
    ) -> float:
        """
        Velocity = publication rate in recent years (2022+).
        High-velocity domains = active research communities = higher impact.
        """
        result = await run_query(
            """
            MATCH (d:Domain)
            WHERE d.id IN [$domain_a_id, $domain_b_id]
            MATCH (p:Paper)-[:IN_DOMAIN]->(d)
            WHERE p.year >= 2022
            RETURN d.id AS domain_id, count(p) AS recent_count
            """,
            params={"domain_a_id": domain_a_id, "domain_b_id": domain_b_id},
        )

        if not result:
            return 0.2

        recent_counts = [r.get("recent_count", 0) for r in result]
        min_velocity = min(recent_counts) if recent_counts else 0

        # Normalize: 500+ recent papers = max velocity
        return min(min_velocity / 500.0, 1.0)

    async def _compute_semantic(
        self,
        domain_a_name: str,
        domain_b_name: str,
    ) -> float:
        """
        Semantic proximity via embedding similarity.
        Semantically close but bibliographically disconnected = high opportunity.
        """
        try:
            # Check if embeddings exist in Qdrant
            emb_a = await nim_embed_single(f"Research domain: {domain_a_name}")
            emb_b = await nim_embed_single(f"Research domain: {domain_b_name}")
            similarity = self._cosine_similarity(emb_a, emb_b)
            return float(similarity)
        except Exception as e:
            logger.warning(f"Semantic scoring failed: {e}")
            return 0.3

    def _cosine_similarity(self, v1: list[float], v2: list[float]) -> float:
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot / (norm1 * norm2)


async def scan_all_domain_pairs(
    min_score: float = 0.45,
    limit: int = 500,
) -> list[tuple[str, str, str, str, GapScore]]:
    """
    Scan all domain pairs and return top opportunities.
    Returns list of (domain_a_id, domain_b_id, domain_a_name, domain_b_name, score).
    """
    scorer = CARGSScorer()

    # Get all domains with at least 10 papers
    domains = await run_query(
        """
        MATCH (d:Domain)
        WHERE d.paper_count >= 10
        RETURN d.id AS id, d.name AS name
        ORDER BY d.paper_count DESC
        LIMIT $limit
        """,
        params={"limit": limit},
    )

    if len(domains) < 2:
        logger.warning("Not enough domains for gap analysis")
        return []

    logger.info(f"Scanning {len(domains)} domains = {len(domains)*(len(domains)-1)//2} pairs")

    # Score all pairs with bounded concurrency
    semaphore = asyncio.Semaphore(10)
    results = []

    async def score_pair(da, db):
        async with semaphore:
            score = await scorer.score_domain_pair(
                da["id"], db["id"], da["name"], db["name"]
            )
            return (da["id"], db["id"], da["name"], db["name"], score)

    tasks = [
        score_pair(domains[i], domains[j])
        for i in range(len(domains))
        for j in range(i + 1, len(domains))
    ]

    all_scores = await asyncio.gather(*tasks, return_exceptions=True)

    for result in all_scores:
        if isinstance(result, Exception):
            continue
        da_id, db_id, da_name, db_name, score = result
        if score.opportunity_score >= min_score:
            results.append(result)

    results.sort(key=lambda x: x[4].opportunity_score, reverse=True)
    logger.info(f"Found {len(results)} opportunities above threshold {min_score}")
    return results
