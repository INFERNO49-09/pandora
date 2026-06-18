"""
Discovery Celery tasks.
Run nightly to scan for research opportunities.
"""
import asyncio
from loguru import logger
from core.celery_app import celery_app
from discovery.cargs import scan_all_domain_pairs
from discovery.hypothesis_generator import HypothesisGenerator
from knowledge_graph.client import run_query


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="discovery.tasks.run_full_discovery_scan")
def run_full_discovery_scan():
    """
    Nightly task: scan all domain pairs, generate opportunities.
    """
    return run_async(_run_discovery_scan_async())


@celery_app.task(name="discovery.tasks.generate_opportunity")
def generate_opportunity(
    domain_a_id: str,
    domain_b_id: str,
    domain_a_name: str,
    domain_b_name: str,
    gap_score_dict: dict,
):
    return run_async(
        _generate_opportunity_async(
            domain_a_id, domain_b_id,
            domain_a_name, domain_b_name,
            gap_score_dict,
        )
    )


async def _run_discovery_scan_async() -> dict:
    logger.info("Starting full discovery scan...")

    # Run CARGS scan across all domain pairs
    top_opportunities = await scan_all_domain_pairs(
        min_score=0.45,
        limit=200,  # scan top-200 most-connected domains
    )

    logger.info(f"Found {len(top_opportunities)} candidate opportunities")

    # Generate hypotheses for top-50 (rate-limit NIM calls)
    generator = HypothesisGenerator()
    generated = []

    for da_id, db_id, da_name, db_name, gap_score in top_opportunities[:50]:
        try:
            opportunity = await generator.generate(
                domain_a_id=da_id,
                domain_b_id=db_id,
                domain_a_name=da_name,
                domain_b_name=db_name,
                gap_score=gap_score,
            )

            # Write opportunity to graph
            await _write_opportunity_to_graph(opportunity)
            generated.append(opportunity.id)

        except Exception as e:
            logger.error(f"Failed to generate opportunity for {da_name} x {db_name}: {e}")

    logger.info(f"Discovery scan complete. Generated {len(generated)} opportunities.")
    return {
        "candidates_found": len(top_opportunities),
        "opportunities_generated": len(generated),
        "opportunity_ids": generated,
    }


async def _generate_opportunity_async(
    domain_a_id: str,
    domain_b_id: str,
    domain_a_name: str,
    domain_b_name: str,
    gap_score_dict: dict,
) -> dict:
    from models.types import GapScore
    gap_score = GapScore(**gap_score_dict)
    generator = HypothesisGenerator()

    opportunity = await generator.generate(
        domain_a_id=domain_a_id,
        domain_b_id=domain_b_id,
        domain_a_name=domain_a_name,
        domain_b_name=domain_b_name,
        gap_score=gap_score,
    )

    await _write_opportunity_to_graph(opportunity)
    return {"opportunity_id": opportunity.id, "title": opportunity.title}


async def _write_opportunity_to_graph(opportunity):
    """Write a ResearchOpportunity node to Neo4j."""
    await run_query(
        """
        MERGE (o:ResearchOpportunity {id: $id})
        SET o.title = $title,
            o.description = $description,
            o.domain_a = $domain_a,
            o.domain_b = $domain_b,
            o.opportunity_score = $opportunity_score,
            o.novelty_score = $novelty_score,
            o.impact_score = $impact_score,
            o.feasibility_score = $feasibility_score,
            o.velocity_score = $velocity_score,
            o.hypothesis = $hypothesis,
            o.rationale = $rationale,
            o.experimental_approach = $experimental_approach,
            o.status = $status,
            o.generated_at = datetime()
        """,
        params={
            "id": opportunity.id,
            "title": opportunity.title,
            "description": opportunity.description,
            "domain_a": opportunity.domain_a,
            "domain_b": opportunity.domain_b,
            "opportunity_score": opportunity.opportunity_score,
            "novelty_score": opportunity.novelty_score,
            "impact_score": opportunity.impact_score,
            "feasibility_score": opportunity.feasibility_score,
            "velocity_score": opportunity.velocity_score,
            "hypothesis": opportunity.hypothesis,
            "rationale": opportunity.hypothesis_rationale,
            "experimental_approach": opportunity.experimental_approach,
            "status": opportunity.status.value,
        },
        write=True,
    )

    # Link to domains
    for domain_name in [opportunity.domain_a, opportunity.domain_b]:
        await run_query(
            """
            MATCH (o:ResearchOpportunity {id: $opp_id})
            MATCH (d:Domain {name: $domain_name})
            MERGE (o)-[:BRIDGES]->(d)
            """,
            params={"opp_id": opportunity.id, "domain_name": domain_name},
            write=True,
        )


@celery_app.task(name="discovery.tasks.run_contradiction_scan")
def run_contradiction_scan(domain: str | None = None) -> dict:
    """Nightly contradiction detection scan."""
    return run_async(_run_contradiction_scan_async(domain))


async def _run_contradiction_scan_async(domain: str | None) -> dict:
    from discovery.contradiction_detector import ContradictionDetector
    detector = ContradictionDetector()
    contradictions = await detector.scan_domain(domain=domain, min_confidence=0.70, limit=100)
    logger.info(f"Contradiction scan complete: {len(contradictions)} found")
    return {"contradictions_found": len(contradictions), "domain": domain}
