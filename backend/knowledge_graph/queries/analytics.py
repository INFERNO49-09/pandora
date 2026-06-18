"""
Graph analytics queries.
Higher-level query functions built on top of the raw Neo4j client.
"""
from knowledge_graph.client import run_query


async def get_domain_info(domain_id: str) -> dict:
    result = await run_query(
        """
        MATCH (d:Domain {id: $id})
        OPTIONAL MATCH (p:Paper)-[:IN_DOMAIN]->(d)
        RETURN d.id AS id,
               d.name AS name,
               count(p) AS paper_count,
               avg(p.citation_count) AS avg_citations,
               max(p.year) AS latest_year,
               count(CASE WHEN p.year >= 2022 THEN 1 END) AS recent_papers
        """,
        params={"id": domain_id},
    )
    return result[0] if result else {}


async def get_top_papers_in_domain(domain_id: str, limit: int = 10) -> list[dict]:
    return await run_query(
        """
        MATCH (p:Paper)-[:IN_DOMAIN]->(d:Domain {id: $id})
        RETURN p.id AS id, p.title AS title,
               p.year AS year, p.citation_count AS citations,
               p.abstract AS abstract
        ORDER BY p.citation_count DESC
        LIMIT $limit
        """,
        params={"id": domain_id, "limit": limit},
    )


async def get_bridge_papers(
    domain_a_id: str,
    domain_b_id: str,
    limit: int = 10,
) -> list[dict]:
    """Papers that appear in both domains — the existing bridges."""
    return await run_query(
        """
        MATCH (p:Paper)-[:IN_DOMAIN]->(da:Domain {id: $da})
        WHERE (p)-[:IN_DOMAIN]->(db:Domain {id: $db})
        RETURN p.id AS id, p.title AS title,
               p.year AS year, p.citation_count AS citations
        ORDER BY p.citation_count DESC
        LIMIT $limit
        """,
        params={"da": domain_a_id, "db": domain_b_id, "limit": limit},
    )


async def get_shared_concepts(
    domain_a_id: str,
    domain_b_id: str,
    limit: int = 20,
) -> list[dict]:
    """Concepts used in papers from both domains."""
    return await run_query(
        """
        MATCH (da:Domain {id: $da})<-[:IN_DOMAIN]-(pa:Paper)
              -[:USES]->(c:Concept)<-[:USES]-(pb:Paper)
              -[:IN_DOMAIN]->(db:Domain {id: $db})
        RETURN c.id AS id, c.canonical_name AS name,
               count(DISTINCT pa) AS count_a,
               count(DISTINCT pb) AS count_b
        ORDER BY (count_a + count_b) DESC
        LIMIT $limit
        """,
        params={"da": domain_a_id, "db": domain_b_id, "limit": limit},
    )


async def get_concept_neighborhood(
    concept_id: str,
    depth: int = 2,
    limit: int = 50,
) -> dict:
    """Get the local neighborhood of a concept in the graph."""
    nodes_result = await run_query(
        """
        MATCH path = (c:Concept {id: $id})-[*1..{depth}]-(neighbor)
        WHERE (neighbor:Concept OR neighbor:Method OR neighbor:Domain)
        WITH DISTINCT neighbor
        RETURN neighbor.id AS id,
               coalesce(neighbor.canonical_name, neighbor.name) AS name,
               labels(neighbor)[0] AS type
        LIMIT $limit
        """.replace("{depth}", str(depth)),
        params={"id": concept_id, "limit": limit},
    )

    edges_result = await run_query(
        """
        MATCH (c:Concept {id: $id})-[r]-(neighbor)
        WHERE (neighbor:Concept OR neighbor:Method OR neighbor:Domain)
        RETURN c.id AS source, neighbor.id AS target, type(r) AS rel_type
        LIMIT $limit
        """,
        params={"id": concept_id, "limit": limit},
    )

    return {
        "center_id": concept_id,
        "neighbors": nodes_result,
        "edges": edges_result,
    }


async def get_graph_stats() -> dict:
    """Overall graph statistics."""
    counts = await run_query(
        """
        MATCH (p:Paper) WITH count(p) AS papers
        OPTIONAL MATCH (c:Concept) WITH papers, count(c) AS concepts
        OPTIONAL MATCH (d:Domain) WITH papers, concepts, count(d) AS domains
        OPTIONAL MATCH (m:Method) WITH papers, concepts, domains, count(m) AS methods
        OPTIONAL MATCH (a:Author) WITH papers, concepts, domains, methods, count(a) AS authors
        OPTIONAL MATCH (o:ResearchOpportunity) WITH papers, concepts, domains, methods, authors, count(o) AS opportunities
        RETURN papers, concepts, domains, methods, authors, opportunities
        """
    )

    rels = await run_query("MATCH ()-[r]->() RETURN count(r) AS total")

    stats = counts[0] if counts else {}
    stats["total_relationships"] = rels[0]["total"] if rels else 0
    return stats


async def get_trending_concepts(years_back: int = 3, limit: int = 20) -> list[dict]:
    """Concepts with the fastest growing paper count in recent years."""
    return await run_query(
        """
        MATCH (c:Concept)<-[:USES]-(p:Paper)
        WHERE p.year >= date().year - $years_back
        WITH c, count(p) AS recent_count
        WHERE recent_count >= 3
        MATCH (c)<-[:USES]-(all_p:Paper)
        WITH c, recent_count, count(all_p) AS total_count
        WHERE total_count > 0
        RETURN c.id AS id,
               c.canonical_name AS name,
               c.domain AS domain,
               recent_count,
               total_count,
               toFloat(recent_count) / total_count AS recency_ratio
        ORDER BY recency_ratio DESC, recent_count DESC
        LIMIT $limit
        """,
        params={"years_back": years_back, "limit": limit},
    )
