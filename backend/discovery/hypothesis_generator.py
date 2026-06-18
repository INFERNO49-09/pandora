"""
Hypothesis generator.
Takes a discovered research gap (domain pair + CARGS score)
and generates a structured scientific hypothesis using NIM.
"""
from loguru import logger
from core.nim_client import nim_chat
from knowledge_graph.client import run_query
from models.types import GapScore, ResearchOpportunity
import uuid


HYPOTHESIS_SYSTEM = """You are a scientific research strategist with deep expertise
across multiple disciplines. You generate specific, grounded, testable research hypotheses.
Every claim must be supported by the evidence provided. Do not speculate beyond the data."""


HYPOTHESIS_PROMPT = """A knowledge graph analysis has identified a potentially underexplored 
research opportunity between two scientific domains.

DOMAIN A: {domain_a}
  - Papers in graph: {papers_a}
  - Recent activity (2022+): {recent_a} papers
  
DOMAIN B: {domain_b}  
  - Papers in graph: {papers_b}
  - Recent activity (2022+): {recent_b} papers

GAP ANALYSIS:
  - Bridge papers (spanning both domains): {bridge_papers}
  - Shared methods/concepts: {shared_methods}
  - Opportunity score: {opportunity_score:.2f} / 1.0
  - Novelty score: {novelty_score:.2f} (higher = less explored)
  - Feasibility score: {feasibility_score:.2f} (higher = more methodologically plausible)

SAMPLE PAPERS FROM DOMAIN A:
{sample_papers_a}

SAMPLE PAPERS FROM DOMAIN B:
{sample_papers_b}

Based on this analysis, generate a research opportunity report with this exact structure:

TITLE: [concise 8-10 word title for the opportunity]

HYPOTHESIS: [one specific, falsifiable hypothesis connecting these domains, 2-3 sentences]

RATIONALE: [why this connection is scientifically plausible, grounded in the evidence above, 3-4 sentences]

EXPERIMENTAL_APPROACH: [concrete steps to test this hypothesis, 3-5 bullet points]

EXPECTED_IMPACT: [what breakthrough this would enable if the hypothesis is confirmed, 2-3 sentences]

CHALLENGES: [main technical or practical obstacles, 2-3 bullet points]

Be specific. Use technical language appropriate for domain experts."""


class HypothesisGenerator:

    async def generate(
        self,
        domain_a_id: str,
        domain_b_id: str,
        domain_a_name: str,
        domain_b_name: str,
        gap_score: GapScore,
    ) -> ResearchOpportunity:
        """
        Generate a full research opportunity with hypothesis for a domain pair.
        """
        # Gather supporting evidence from Neo4j
        evidence = await self._gather_evidence(
            domain_a_id, domain_b_id, domain_a_name, domain_b_name
        )

        # Generate hypothesis
        prompt = HYPOTHESIS_PROMPT.format(
            domain_a=domain_a_name,
            domain_b=domain_b_name,
            papers_a=evidence["papers_a"],
            papers_b=evidence["papers_b"],
            recent_a=evidence["recent_a"],
            recent_b=evidence["recent_b"],
            bridge_papers=evidence["bridge_count"],
            shared_methods=evidence["shared_count"],
            opportunity_score=gap_score.opportunity_score,
            novelty_score=gap_score.novelty_score,
            feasibility_score=gap_score.feasibility_score,
            sample_papers_a=self._format_papers(evidence["sample_a"]),
            sample_papers_b=self._format_papers(evidence["sample_b"]),
        )

        try:
            raw = await nim_chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=HYPOTHESIS_SYSTEM,
                temperature=0.65,  # slightly creative for hypothesis generation
                max_tokens=1200,
            )
            parsed = self._parse_hypothesis(raw)
        except Exception as e:
            logger.error(f"Hypothesis generation failed: {e}")
            parsed = {
                "title": f"{domain_a_name} x {domain_b_name}",
                "hypothesis": f"Connecting {domain_a_name} with {domain_b_name} may yield novel insights.",
                "rationale": "Identified via graph gap analysis.",
                "experimental_approach": "Further investigation required.",
                "expected_impact": "Unknown.",
                "challenges": "Further analysis needed.",
            }

        return ResearchOpportunity(
            id=str(uuid.uuid4()),
            title=parsed.get("title", f"{domain_a_name} × {domain_b_name}"),
            description=parsed.get("hypothesis", ""),
            domain_a=domain_a_name,
            domain_b=domain_b_name,
            bridge_concepts=evidence.get("bridge_concepts", []),
            opportunity_score=gap_score.opportunity_score,
            novelty_score=gap_score.novelty_score,
            impact_score=gap_score.impact_score,
            feasibility_score=gap_score.feasibility_score,
            velocity_score=gap_score.velocity_score,
            hypothesis=parsed.get("hypothesis"),
            hypothesis_rationale=parsed.get("rationale"),
            experimental_approach=parsed.get("experimental_approach"),
            supporting_paper_ids=evidence.get("supporting_paper_ids", []),
            score_evidence=gap_score.evidence,
        )

    async def _gather_evidence(
        self,
        domain_a_id: str,
        domain_b_id: str,
        domain_a_name: str,
        domain_b_name: str,
    ) -> dict:
        """Fetch supporting evidence from Neo4j."""
        # Domain sizes
        size_result = await run_query(
            """
            MATCH (d:Domain)
            WHERE d.id IN [$da, $db]
            MATCH (p:Paper)-[:IN_DOMAIN]->(d)
            RETURN d.id AS did, count(p) AS total,
                   count(CASE WHEN p.year >= 2022 THEN 1 END) AS recent
            """,
            params={"da": domain_a_id, "db": domain_b_id},
        )

        papers_a = next((r["total"] for r in size_result if r["did"] == domain_a_id), 0)
        papers_b = next((r["total"] for r in size_result if r["did"] == domain_b_id), 0)
        recent_a = next((r["recent"] for r in size_result if r["did"] == domain_a_id), 0)
        recent_b = next((r["recent"] for r in size_result if r["did"] == domain_b_id), 0)

        # Sample papers from each domain
        sample_a = await run_query(
            """
            MATCH (p:Paper)-[:IN_DOMAIN]->(d:Domain {id: $domain_id})
            RETURN p.title AS title, p.year AS year, p.citation_count AS citations
            ORDER BY p.citation_count DESC
            LIMIT 5
            """,
            params={"domain_id": domain_a_id},
        )

        sample_b = await run_query(
            """
            MATCH (p:Paper)-[:IN_DOMAIN]->(d:Domain {id: $domain_id})
            RETURN p.title AS title, p.year AS year, p.citation_count AS citations
            ORDER BY p.citation_count DESC
            LIMIT 5
            """,
            params={"domain_id": domain_b_id},
        )

        # Bridge papers
        bridge_result = await run_query(
            """
            MATCH (bridge:Paper)-[:IN_DOMAIN]->(da:Domain {id: $da})
            WHERE (bridge)-[:IN_DOMAIN]->(db:Domain {id: $db})
            RETURN bridge.id AS id, bridge.title AS title
            LIMIT 10
            """,
            params={"da": domain_a_id, "db": domain_b_id},
        )

        # Shared concepts/methods
        shared_result = await run_query(
            """
            MATCH (da:Domain {id: $da})<-[:IN_DOMAIN]-(pa:Paper)
                  -[:USES]->(shared)<-[:USES]-(pb:Paper)
                  -[:IN_DOMAIN]->(db:Domain {id: $db})
            WHERE (shared:Concept OR shared:Method)
            RETURN shared.canonical_name AS name LIMIT 10
            """,
            params={"da": domain_a_id, "db": domain_b_id},
        )

        return {
            "papers_a": papers_a,
            "papers_b": papers_b,
            "recent_a": recent_a,
            "recent_b": recent_b,
            "sample_a": sample_a,
            "sample_b": sample_b,
            "bridge_count": len(bridge_result),
            "shared_count": len(shared_result),
            "bridge_concepts": [r["name"] for r in shared_result if r.get("name")],
            "supporting_paper_ids": [r["id"] for r in bridge_result],
        }

    def _format_papers(self, papers: list[dict]) -> str:
        if not papers:
            return "No sample papers available"
        lines = []
        for p in papers:
            year = p.get("year", "?")
            title = p.get("title", "Unknown")
            cites = p.get("citations", 0)
            lines.append(f"  - [{year}] {title} ({cites} citations)")
        return "\n".join(lines)

    def _parse_hypothesis(self, raw: str) -> dict:
        """Parse structured hypothesis output."""
        fields = {
            "title": "TITLE",
            "hypothesis": "HYPOTHESIS",
            "rationale": "RATIONALE",
            "experimental_approach": "EXPERIMENTAL_APPROACH",
            "expected_impact": "EXPECTED_IMPACT",
            "challenges": "CHALLENGES",
        }

        result = {}
        lines = raw.split("\n")

        current_field = None
        current_content = []

        for line in lines:
            stripped = line.strip()
            matched = False
            for key, prefix in fields.items():
                if stripped.startswith(f"{prefix}:"):
                    if current_field:
                        result[current_field] = " ".join(current_content).strip()
                    current_field = key
                    content_after_colon = stripped[len(prefix) + 1:].strip()
                    current_content = [content_after_colon] if content_after_colon else []
                    matched = True
                    break
            if not matched and current_field and stripped:
                current_content.append(stripped)

        if current_field:
            result[current_field] = " ".join(current_content).strip()

        return result
