"""
Trends API — research velocity and growth prediction.
"""
from fastapi import APIRouter, Query
from knowledge_graph.queries.analytics import get_trending_concepts
from knowledge_graph.client import run_query

router = APIRouter(prefix="/trends", tags=["trends"])


@router.get("/concepts")
async def get_trending_concepts_endpoint(
    years_back: int = Query(3, ge=1, le=10),
    domain: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Get fastest-growing scientific concepts by recent paper count."""
    concepts = await get_trending_concepts(years_back=years_back, limit=limit * 2)

    if domain:
        concepts = [
            c for c in concepts
            if c.get("domain") and domain.lower() in c["domain"].lower()
        ]

    return {"trends": concepts[:limit], "years_analyzed": years_back}


@router.get("/domains")
async def get_domain_growth(
    limit: int = Query(20, ge=1, le=100),
):
    """Get domains ranked by recent publication velocity."""
    results = await run_query(
        """
        MATCH (d:Domain)<-[:IN_DOMAIN]-(p:Paper)
        WITH d, p
        WITH d,
             count(CASE WHEN p.year >= date().year - 2 THEN 1 END) AS recent,
             count(p) AS total
        WHERE total >= 10
        RETURN d.id AS id, d.name AS name,
               recent AS recent_papers,
               total AS total_papers,
               toFloat(recent) / total AS growth_ratio
        ORDER BY growth_ratio DESC, recent DESC
        LIMIT $limit
        """,
        params={"limit": limit},
    )
    return {"domains": results}


@router.get("/publication-timeline")
async def get_publication_timeline(
    domain: str = Query(...),
    years: int = Query(10, ge=3, le=20),
):
    """Year-by-year publication count for a domain."""
    results = await run_query(
        """
        MATCH (d:Domain)
        WHERE toLower(d.name) CONTAINS toLower($domain)
        MATCH (p:Paper)-[:IN_DOMAIN]->(d)
        WHERE p.year >= date().year - $years AND p.year IS NOT NULL
        RETURN p.year AS year, count(p) AS papers
        ORDER BY year ASC
        """,
        params={"domain": domain, "years": years},
    )
    return {"domain": domain, "timeline": results}


@router.get("/emerging-intersections")
async def get_emerging_intersections(limit: int = Query(10, ge=1, le=50)):
    """
    Domain pairs with rapidly growing bridge paper counts.
    These are intersections that are being actively formed right now.
    """
    results = await run_query(
        """
        MATCH (da:Domain)<-[:IN_DOMAIN]-(p:Paper)-[:IN_DOMAIN]->(db:Domain)
        WHERE id(da) < id(db)
          AND p.year >= date().year - 3
          AND da.paper_count >= 20
          AND db.paper_count >= 20
        WITH da, db, count(p) AS recent_bridges
        WHERE recent_bridges >= 3
        MATCH (da)<-[:IN_DOMAIN]-(all_p:Paper)-[:IN_DOMAIN]->(db)
        WITH da, db, recent_bridges, count(all_p) AS total_bridges
        WHERE total_bridges > 0
        RETURN da.name AS domain_a,
               db.name AS domain_b,
               recent_bridges,
               total_bridges,
               toFloat(recent_bridges) / total_bridges AS emergence_ratio
        ORDER BY emergence_ratio DESC, recent_bridges DESC
        LIMIT $limit
        """,
        params={"limit": limit},
    )
    return {"emerging_intersections": results}
