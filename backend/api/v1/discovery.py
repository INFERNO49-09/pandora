"""
Discovery API — the primary value surface of Pandora.
Exposes research opportunities, gap scores, and on-demand analysis.
"""
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel
from knowledge_graph.client import run_query
from discovery.cargs import CARGSScorer
from discovery.hypothesis_generator import HypothesisGenerator
from models.types import ResearchOpportunity, GapScore

router = APIRouter(prefix="/discover", tags=["discovery"])


# ── GET OPPORTUNITIES ──────────────────────────────────────────────────────────

@router.get("/opportunities")
async def get_opportunities(
    domain: str | None = Query(None, description="Filter by domain name (partial match)"),
    min_score: float = Query(0.50, ge=0.0, le=1.0),
    sort_by: str = Query("opportunity_score", enum=["opportunity_score", "novelty_score", "impact_score"]),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get ranked research opportunities discovered by Pandora."""

    domain_filter = ""
    params: dict = {
        "min_score": min_score,
        "limit": limit,
        "offset": offset,
    }

    if domain:
        domain_filter = "AND (toLower(o.domain_a) CONTAINS toLower($domain) OR toLower(o.domain_b) CONTAINS toLower($domain))"
        params["domain"] = domain

    results = await run_query(
        f"""
        MATCH (o:ResearchOpportunity)
        WHERE o.opportunity_score >= $min_score
          AND o.status = 'active'
          {domain_filter}
        RETURN o
        ORDER BY o.{sort_by} DESC
        SKIP $offset
        LIMIT $limit
        """,
        params=params,
    )

    # Count for pagination
    count_result = await run_query(
        f"""
        MATCH (o:ResearchOpportunity)
        WHERE o.opportunity_score >= $min_score AND o.status = 'active'
        {domain_filter}
        RETURN count(o) AS total
        """,
        params={k: v for k, v in params.items() if k not in ["limit", "offset"]},
    )

    total = count_result[0]["total"] if count_result else 0

    return {
        "opportunities": [dict(r["o"]) for r in results],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


@router.get("/opportunities/{opportunity_id}")
async def get_opportunity_detail(opportunity_id: str):
    """Get full detail for a research opportunity including supporting papers."""

    result = await run_query(
        """
        MATCH (o:ResearchOpportunity {id: $id})
        OPTIONAL MATCH (o)-[:BRIDGES]->(d:Domain)
        OPTIONAL MATCH (o)-[:SUPPORTED_BY]->(p:Paper)
        RETURN o,
               collect(DISTINCT d.name) AS domains,
               collect(DISTINCT {id: p.id, title: p.title, year: p.year, citations: p.citation_count}) AS papers
        """,
        params={"id": opportunity_id},
    )

    if not result:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    row = result[0]
    opp = dict(row["o"])
    opp["linked_domains"] = row["domains"]
    opp["supporting_papers"] = [p for p in row["papers"] if p.get("id")]

    return opp


# ── DOMAIN MAP ────────────────────────────────────────────────────────────────

@router.get("/domain-map")
async def get_domain_map(
    min_papers: int = Query(5, ge=1),
    highlight_gaps: bool = Query(True),
):
    """
    Get all domains with their connection strengths for visualization.
    Returns nodes (domains) and edges (connections / gaps).
    """
    # Domain nodes
    domains = await run_query(
        """
        MATCH (d:Domain)
        WHERE d.paper_count >= $min_papers
        RETURN d.id AS id, d.name AS name,
               d.paper_count AS paper_count,
               d.growth_rate AS growth_rate
        ORDER BY d.paper_count DESC
        LIMIT 100
        """,
        params={"min_papers": min_papers},
    )

    # Domain connections (papers spanning two domains)
    connections = await run_query(
        """
        MATCH (da:Domain)<-[:IN_DOMAIN]-(p:Paper)-[:IN_DOMAIN]->(db:Domain)
        WHERE da.paper_count >= $min_papers
          AND db.paper_count >= $min_papers
          AND id(da) < id(db)
        RETURN da.id AS source, db.id AS target,
               count(p) AS bridge_papers,
               da.name AS source_name,
               db.name AS target_name
        ORDER BY bridge_papers DESC
        LIMIT 500
        """,
        params={"min_papers": min_papers},
    )

    # Top opportunities (for gap overlay)
    gap_overlay = []
    if highlight_gaps:
        gaps = await run_query(
            """
            MATCH (o:ResearchOpportunity)
            WHERE o.opportunity_score >= 0.6
            RETURN o.domain_a AS domain_a, o.domain_b AS domain_b,
                   o.opportunity_score AS score, o.id AS id
            ORDER BY o.opportunity_score DESC
            LIMIT 50
            """,
        )
        gap_overlay = gaps

    return {
        "nodes": domains,
        "edges": connections,
        "gap_overlays": gap_overlay,
    }


# ── ON-DEMAND SCORING ─────────────────────────────────────────────────────────

class ScoreRequest(BaseModel):
    domain_a_name: str
    domain_b_name: str


@router.post("/score")
async def score_domain_pair(req: ScoreRequest, background_tasks: BackgroundTasks):
    """
    On-demand CARGS scoring for a specific domain pair.
    Also triggers hypothesis generation in the background.
    """
    # Resolve domain names to IDs
    result = await run_query(
        """
        MATCH (d:Domain)
        WHERE toLower(d.name) CONTAINS toLower($name_a)
           OR toLower(d.name) CONTAINS toLower($name_b)
        RETURN d.id AS id, d.name AS name
        LIMIT 10
        """,
        params={"name_a": req.domain_a_name, "name_b": req.domain_b_name},
    )

    if len(result) < 2:
        raise HTTPException(
            status_code=404,
            detail=f"Could not find both domains in graph. Found: {[r['name'] for r in result]}"
        )

    # Best match for each
    da = next((r for r in result if req.domain_a_name.lower() in r["name"].lower()), result[0])
    db = next((r for r in result if req.domain_b_name.lower() in r["name"].lower()), result[-1])

    if da["id"] == db["id"]:
        raise HTTPException(status_code=400, detail="Domain A and Domain B resolved to the same domain")

    scorer = CARGSScorer()
    score = await scorer.score_domain_pair(
        da["id"], db["id"], da["name"], db["name"]
    )

    # Queue hypothesis generation if score is good enough
    if score.opportunity_score >= 0.50:
        from discovery.tasks import generate_opportunity
        background_tasks.add_task(
            lambda: generate_opportunity.apply_async(
                args=[da["id"], db["id"], da["name"], db["name"], score.model_dump()],
                queue="discovery",
            )
        )

    return {
        "domain_a": da["name"],
        "domain_b": db["name"],
        "score": score.model_dump(),
        "hypothesis_generation": "queued" if score.opportunity_score >= 0.50 else "skipped (score too low)",
    }


# ── DISCOVERY STATS ───────────────────────────────────────────────────────────

@router.get("/stats")
async def get_discovery_stats():
    """Overall graph and discovery statistics."""
    result = await run_query(
        """
        MATCH (p:Paper) WITH count(p) AS papers
        MATCH (c:Concept) WITH papers, count(c) AS concepts
        MATCH (d:Domain) WITH papers, concepts, count(d) AS domains
        MATCH (o:ResearchOpportunity) WITH papers, concepts, domains, count(o) AS opportunities
        RETURN papers, concepts, domains, opportunities
        """
    )

    rel_result = await run_query(
        "MATCH ()-[r]->() RETURN count(r) AS total_relationships"
    )

    stats = result[0] if result else {}
    stats["total_relationships"] = rel_result[0]["total_relationships"] if rel_result else 0

    return stats
