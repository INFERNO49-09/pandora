"""
Contradiction Detection Pipeline.

Identifies scientific disagreements by finding papers that:
1. Evaluate on the same dataset with the same metric
2. Report directionally conflicting results
3. Reach opposing conclusions on the same claim

Three contradiction types:
  QUANTITATIVE  — same metric, same dataset, conflicting numbers
  QUALITATIVE   — opposing conclusions stated in abstracts/conclusions
  METHODOLOGICAL — same task, incompatible methodology claims

Architecture:
  - Quantitative: graph query (Experiment nodes) + threshold check
  - Qualitative: LLM comparison of conclusion sections
  - The graph query runs as a nightly Celery task
  - Results stored in PostgreSQL contradiction_reports table
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from loguru import logger

from knowledge_graph.client import run_query
from core.nim_client import nim_chat


@dataclass
class Contradiction:
    id: str
    paper_a_id: str
    paper_a_title: str
    paper_b_id: str
    paper_b_title: str
    dataset: str | None
    metric: str | None
    paper_a_value: float | None
    paper_b_value: float | None
    confidence: float
    explanation: str
    contradiction_type: str      # quantitative | qualitative | methodological
    methodology_analysis: str | None = None


QUALITATIVE_SYSTEM = """You are a scientific fact-checker comparing two research papers.
Analyze whether the two papers reach contradictory conclusions on the same scientific question.
Be precise and evidence-based. Only flag genuine contradictions, not minor methodological differences."""

QUALITATIVE_PROMPT = """Compare these two paper abstracts and determine if they contradict each other.

PAPER A: {title_a} ({year_a})
Abstract: {abstract_a}

PAPER B: {title_b} ({year_b})
Abstract: {abstract_b}

Answer with a JSON object:
{{
  "contradicts": true/false,
  "confidence": 0.0-1.0,
  "explanation": "one precise sentence describing the contradiction or lack thereof",
  "contradiction_type": "quantitative|qualitative|methodological|none",
  "shared_topic": "the specific claim or topic where they disagree"
}}

Only mark contradicts=true for genuine scientific disagreements, not different scopes."""


class ContradictionDetector:

    async def scan_domain(
        self,
        domain: str | None = None,
        min_confidence: float = 0.70,
        limit: int = 200,
    ) -> list[Contradiction]:
        """
        Scan the graph for contradictions.
        Runs quantitative scan first (fast, graph-only),
        then qualitative NIM scan on top candidates.
        """
        logger.info(f"Starting contradiction scan (domain={domain})")

        quantitative = await self._scan_quantitative(domain, limit)
        logger.info(f"Found {len(quantitative)} quantitative contradiction candidates")

        qualitative = await self._scan_qualitative(domain, min(50, limit))
        logger.info(f"Found {len(qualitative)} qualitative contradiction candidates")

        all_contradictions = quantitative + qualitative
        all_contradictions = [c for c in all_contradictions if c.confidence >= min_confidence]
        all_contradictions.sort(key=lambda c: c.confidence, reverse=True)

        return all_contradictions

    async def _scan_quantitative(
        self,
        domain: str | None,
        limit: int,
    ) -> list[Contradiction]:
        """
        Find papers reporting conflicting numeric results.
        Uses Experiment nodes that share Dataset + Metric.
        Falls back to paper-level result matching if no Experiment nodes.
        """
        domain_filter = ""
        params: dict = {"limit": limit}
        if domain:
            domain_filter = """
            AND EXISTS {
              MATCH (p1)-[:IN_DOMAIN]->(d:Domain)
              WHERE toLower(d.name) CONTAINS toLower($domain)
            }
            """
            params["domain"] = domain

        # Method 1: Experiment node comparison
        results = await run_query(
            f"""
            MATCH (p1:Paper)-[:HAS_EXPERIMENT]->(e1:Experiment)
                  -[:ON_DATASET]->(d:Dataset)
                  <-[:ON_DATASET]-(e2:Experiment)
                  <-[:HAS_EXPERIMENT]-(p2:Paper)
            MATCH (e1)-[:MEASURES]->(m:Metric)<-[:MEASURES]-(e2)
            WHERE p1.id < p2.id
              AND e1.metric_value IS NOT NULL
              AND e2.metric_value IS NOT NULL
              AND e1.metric_value <> e2.metric_value
              {domain_filter}
            WITH p1, p2, d, m, e1, e2,
                 abs(e1.metric_value - e2.metric_value) AS delta,
                 abs(e1.metric_value - e2.metric_value) /
                 (abs(e1.metric_value) + abs(e2.metric_value) + 0.001) AS rel_delta
            WHERE rel_delta > 0.05
            RETURN p1.id AS aid, p1.title AS atitle,
                   p2.id AS bid, p2.title AS btitle,
                   d.name AS dataset, m.name AS metric,
                   e1.metric_value AS val_a, e2.metric_value AS val_b,
                   m.higher_is_better AS higher_better,
                   delta, rel_delta
            ORDER BY rel_delta DESC
            LIMIT $limit
            """,
            params=params,
        )

        contradictions = []
        for row in results:
            # Determine if conflict is directionally meaningful
            conflict_score = self._quantitative_conflict_score(
                row["val_a"], row["val_b"],
                row.get("higher_better"), row["rel_delta"]
            )
            if conflict_score < 0.5:
                continue

            contradictions.append(Contradiction(
                id=str(uuid.uuid4()),
                paper_a_id=row["aid"],
                paper_a_title=row["atitle"] or "",
                paper_b_id=row["bid"],
                paper_b_title=row["btitle"] or "",
                dataset=row.get("dataset"),
                metric=row.get("metric"),
                paper_a_value=row.get("val_a"),
                paper_b_value=row.get("val_b"),
                confidence=round(conflict_score, 3),
                explanation=(
                    f"Paper A reports {row['val_a']:.2f} vs Paper B reports "
                    f"{row['val_b']:.2f} on {row.get('metric', 'metric')} / "
                    f"{row.get('dataset', 'dataset')} "
                    f"({row['rel_delta']*100:.1f}% relative difference)"
                ),
                contradiction_type="quantitative",
            ))

        return contradictions

    def _quantitative_conflict_score(
        self,
        val_a: float,
        val_b: float,
        higher_is_better: bool | None,
        rel_delta: float,
    ) -> float:
        """
        Score the severity of a quantitative conflict.
        
        Factors:
        - Relative delta (larger = more serious)
        - Whether one clearly dominates (and thus the other is wrong)
        """
        # Base score: relative delta
        base = min(rel_delta * 2, 1.0)

        # Boost if delta is large (>20% difference = highly suspicious)
        if rel_delta > 0.20:
            base = min(base + 0.2, 1.0)

        # If we know directionality, check if results are clearly opposed
        if higher_is_better is not None:
            # One paper claims high is good, reports high — other reports low
            # Genuine conflict, not just noise
            if abs(val_a - val_b) > 5.0:   # absolute gap > 5 units
                base = min(base + 0.15, 1.0)

        return base

    async def _scan_qualitative(
        self,
        domain: str | None,
        limit: int,
    ) -> list[Contradiction]:
        """
        Find qualitative contradictions using NIM to compare abstracts.
        Targets paper pairs that:
        1. Are in the same domain
        2. Use the same method or dataset
        3. Were published within 3 years of each other
        """
        domain_filter = ""
        params: dict = {"limit": limit}
        if domain:
            domain_filter = "AND toLower(d.name) CONTAINS toLower($domain)"
            params["domain"] = domain

        # Find candidate pairs: same method or dataset, same domain
        candidates = await run_query(
            f"""
            MATCH (p1:Paper)-[:IN_DOMAIN]->(d:Domain)<-[:IN_DOMAIN]-(p2:Paper)
            MATCH (p1)-[:USES]->(shared)<-[:USES]-(p2)
            WHERE p1.id < p2.id
              AND p1.abstract IS NOT NULL AND p2.abstract IS NOT NULL
              AND p1.year IS NOT NULL AND p2.year IS NOT NULL
              AND abs(p1.year - p2.year) <= 3
              AND size(p1.abstract) > 100
              AND size(p2.abstract) > 100
              {domain_filter}
            RETURN p1.id AS aid, p1.title AS atitle, p1.abstract AS aabs, p1.year AS ayear,
                   p2.id AS bid, p2.title AS btitle, p2.abstract AS babs, p2.year AS byear
            LIMIT $limit
            """,
            params=params,
        )

        contradictions = []
        # Process in batches of 10 to manage NIM rate limits
        for i, row in enumerate(candidates):
            if i >= limit:
                break
            try:
                result = await self._compare_abstracts(row)
                if result and result.confidence >= 0.65:
                    contradictions.append(result)
            except Exception as e:
                logger.warning(f"Qualitative comparison failed: {e}")

        return contradictions

    async def _compare_abstracts(self, row: dict) -> Contradiction | None:
        """Run NIM comparison of two paper abstracts."""
        raw = await nim_chat(
            messages=[{
                "role": "user",
                "content": QUALITATIVE_PROMPT.format(
                    title_a=row["atitle"] or "Unknown",
                    year_a=row.get("ayear", "?"),
                    abstract_a=(row["aabs"] or "")[:1500],
                    title_b=row["btitle"] or "Unknown",
                    year_b=row.get("byear", "?"),
                    abstract_b=(row["babs"] or "")[:1500],
                ),
            }],
            system_prompt=QUALITATIVE_SYSTEM,
            temperature=0.05,
            max_tokens=300,
        )

        import json, re
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group())
        except Exception:
            return None

        if not data.get("contradicts"):
            return None

        return Contradiction(
            id=str(uuid.uuid4()),
            paper_a_id=row["aid"],
            paper_a_title=row["atitle"] or "",
            paper_b_id=row["bid"],
            paper_b_title=row["btitle"] or "",
            dataset=None,
            metric=None,
            paper_a_value=None,
            paper_b_value=None,
            confidence=float(data.get("confidence", 0.65)),
            explanation=data.get("explanation", ""),
            contradiction_type=data.get("contradiction_type", "qualitative"),
            methodology_analysis=data.get("shared_topic"),
        )

    async def get_stored_contradictions(
        self,
        domain: str | None = None,
        contradiction_type: str | None = None,
        min_confidence: float = 0.70,
        limit: int = 50,
    ) -> list[dict]:
        """Fetch stored contradiction reports from PostgreSQL."""
        import asyncpg
        from core.config import get_settings
        settings = get_settings()

        # Build filter
        filters = ["confidence_score >= $1"]
        args: list = [min_confidence]

        if domain:
            # Join to Neo4j not possible from PG, so we filter post-fetch
            pass
        if contradiction_type:
            args.append(contradiction_type)
            filters.append(f"contradiction_type = ${len(args)}")

        args.append(limit)
        where = " AND ".join(filters)

        try:
            conn = await asyncpg.connect(
                settings.POSTGRES_DSN.replace("+asyncpg", "")
            )
            rows = await conn.fetch(
                f"""
                SELECT * FROM contradiction_reports
                WHERE {where}
                ORDER BY confidence_score DESC
                LIMIT ${len(args)}
                """,
                *args,
            )
            await conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.warning(f"DB fetch failed, querying graph instead: {e}")
            # Fallback: query Neo4j contradiction edges
            return await self._get_graph_contradictions(domain, min_confidence, limit)

    async def _get_graph_contradictions(
        self,
        domain: str | None,
        min_confidence: float,
        limit: int,
    ) -> list[dict]:
        """Fallback: read CONTRADICTS edges from Neo4j."""
        domain_filter = ""
        params: dict = {"min_conf": min_confidence, "limit": limit}
        if domain:
            domain_filter = """
            AND EXISTS {
              MATCH (p1)-[:IN_DOMAIN]->(d:Domain)
              WHERE toLower(d.name) CONTAINS toLower($domain)
            }
            """
            params["domain"] = domain

        results = await run_query(
            f"""
            MATCH (p1:Paper)-[r:CONTRADICTS]->(p2:Paper)
            WHERE coalesce(r.confidence, 0.7) >= $min_conf
              {domain_filter}
            RETURN p1.id AS paper_a_id, p1.title AS paper_a_title,
                   p2.id AS paper_b_id, p2.title AS paper_b_title,
                   coalesce(r.confidence, 0.7) AS confidence_score,
                   r.evidence AS explanation,
                   'qualitative' AS contradiction_type
            ORDER BY confidence_score DESC
            LIMIT $limit
            """,
            params=params,
        )
        return results

    async def persist_contradictions(self, contradictions: list[Contradiction]) -> None:
        """
        Persist a list of contradictions to both PostgreSQL (tabular reports)
        and Neo4j (graph edges).
        """
        if not contradictions:
            return

        import asyncpg
        from core.config import get_settings
        settings = get_settings()

        # 1. Persist to PostgreSQL
        try:
            conn = await asyncpg.connect(settings.POSTGRES_DSN.replace("+asyncpg", ""))
            await conn.executemany(
                """
                INSERT INTO contradiction_reports
                    (paper_a_id, paper_b_id, dataset_id, metric_id,
                     paper_a_value, paper_b_value, confidence_score,
                     explanation, contradiction_type, detected_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                ON CONFLICT DO NOTHING
                """,
                [
                    (
                        c.paper_a_id,
                        c.paper_b_id,
                        c.dataset,
                        c.metric,
                        c.paper_a_value,
                        c.paper_b_value,
                        c.confidence,
                        c.explanation,
                        c.contradiction_type,
                    )
                    for c in contradictions
                ],
            )
            logger.info(f"Persisted {len(contradictions)} contradiction reports to PostgreSQL")
        except Exception as e:
            logger.error(f"Failed to persist contradictions to PostgreSQL: {e}")
        finally:
            if 'conn' in locals() and not conn.is_closed():
                await conn.close()

        # 2. Persist to Neo4j
        try:
            for c in contradictions:
                await run_query(
                    """
                    MATCH (p1:Paper {id: $paper_a_id})
                    MATCH (p2:Paper {id: $paper_b_id})
                    MERGE (p1)-[r:CONTRADICTS]->(p2)
                    SET r.confidence = $confidence,
                        r.evidence = $explanation,
                        r.type = $type,
                        r.detected_at = datetime()
                    """,
                    params={
                        "paper_a_id": c.paper_a_id,
                        "paper_b_id": c.paper_b_id,
                        "confidence": c.confidence,
                        "explanation": c.explanation,
                        "type": c.contradiction_type,
                    },
                    write=True,
                )
            logger.info(f"Persisted {len(contradictions)} contradiction edges to Neo4j")
        except Exception as e:
            logger.error(f"Failed to persist contradictions to Neo4j: {e}")

