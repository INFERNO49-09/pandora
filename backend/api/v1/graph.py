"""
Graph exploration API.
Returns subgraphs, node details, and search results for the frontend explorer.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from knowledge_graph.client import run_query

router = APIRouter(prefix="/graph", tags=["graph"])


class SubgraphRequest(BaseModel):
    seed_ids: list[str]
    depth: int = 2
    max_nodes: int = 500
    node_types: list[str] = ["Concept", "Domain", "Method", "Paper"]
    include_opportunities: bool = True


@router.post("/subgraph")
async def get_subgraph(req: SubgraphRequest):
    """
    Get a subgraph centered on seed nodes for visualization.
    Returns nodes and edges in a format ready for Cytoscape.js / React Flow.
    """
    if req.depth > 4:
        raise HTTPException(status_code=400, detail="depth cannot exceed 4")

    depth = req.depth
    node_type_filter = "|".join(req.node_types)

    results = await run_query(
        f"""
        MATCH path = (seed)-[*0..{depth}]-(neighbor)
        WHERE seed.id IN $seed_ids
          AND (
            {' OR '.join(f'neighbor:{nt}' for nt in req.node_types)}
          )
        WITH path, nodes(path) AS path_nodes, relationships(path) AS rels
        UNWIND path_nodes AS n
        WITH COLLECT(DISTINCT n) AS all_nodes, COLLECT(DISTINCT rels) AS all_rel_lists
        UNWIND all_rel_lists AS rel_list
        UNWIND rel_list AS r
        RETURN all_nodes, COLLECT(DISTINCT r) AS all_rels
        LIMIT 1
        """,
        params={"seed_ids": req.seed_ids},
    )

    if not results:
        return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0}

    row = results[0]
    raw_nodes = row.get("all_nodes", [])
    raw_rels = row.get("all_rels", [])

    # Format for frontend
    nodes = []
    for node in raw_nodes[:req.max_nodes]:
        node_dict = dict(node)
        labels = list(node.labels) if hasattr(node, "labels") else []
        node_type = labels[0] if labels else "Unknown"
        nodes.append({
            "id": node_dict.get("id", str(node.id)),
            "label": node_dict.get("canonical_name") or node_dict.get("name") or node_dict.get("title", "")[:60],
            "type": node_type,
            "data": node_dict,
        })

    edges = []
    seen_edges = set()
    for rel in raw_rels:
        edge_key = f"{rel.start_node.id}-{rel.type}-{rel.end_node.id}"
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        edges.append({
            "id": edge_key,
            "source": str(rel.start_node.get("id", rel.start_node.id)),
            "target": str(rel.end_node.get("id", rel.end_node.id)),
            "type": rel.type,
            "data": dict(rel),
        })

    # Optionally include opportunity nodes bridging these domains
    if req.include_opportunities:
        opp_result = await run_query(
            """
            MATCH (o:ResearchOpportunity)-[:BRIDGES]->(d:Domain)
            WHERE d.id IN $domain_ids
            RETURN o
            LIMIT 10
            """,
            params={
                "domain_ids": [
                    n["id"] for n in nodes if n["type"] == "Domain"
                ]
            },
        )
        for row in opp_result:
            opp = dict(row["o"])
            nodes.append({
                "id": opp["id"],
                "label": opp.get("title", "Research Opportunity")[:60],
                "type": "ResearchOpportunity",
                "data": opp,
            })

    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
    }


@router.get("/search")
async def search_graph(
    q: str = Query(..., min_length=2),
    node_types: str = Query("Concept,Domain,Method,Paper"),
    limit: int = Query(20, le=100),
):
    """Full-text search across the knowledge graph."""
    types = [t.strip() for t in node_types.split(",")]

    results = []
    for node_type in types:
        index_name = f"{node_type.lower()}_fulltext"
        try:
            type_results = await run_query(
                f"""
                CALL db.index.fulltext.queryNodes('{index_name}', $query)
                YIELD node, score
                RETURN node, score, '{node_type}' AS type
                ORDER BY score DESC
                LIMIT $limit
                """,
                params={"query": q, "limit": limit // len(types)},
            )
            for row in type_results:
                node_dict = dict(row["node"])
                results.append({
                    "id": node_dict.get("id"),
                    "label": node_dict.get("canonical_name") or node_dict.get("name") or node_dict.get("title", "")[:80],
                    "type": row["type"],
                    "score": row["score"],
                    "data": node_dict,
                })
        except Exception:
            # Index might not exist yet
            pass

    results.sort(key=lambda x: x["score"], reverse=True)
    return {"results": results[:limit], "query": q}


@router.get("/node/{node_id}")
async def get_node_detail(node_id: str):
    """Get full detail for a single graph node."""
    result = await run_query(
        """
        MATCH (n {id: $node_id})
        OPTIONAL MATCH (n)-[r]-(neighbor)
        RETURN n,
               labels(n) AS node_labels,
               collect({
                 type: type(r),
                 direction: CASE WHEN startNode(r) = n THEN 'out' ELSE 'in' END,
                 neighbor_id: neighbor.id,
                 neighbor_label: coalesce(neighbor.canonical_name, neighbor.name, neighbor.title)
               }) AS relationships
        """,
        params={"node_id": node_id},
    )

    if not result:
        raise HTTPException(status_code=404, detail="Node not found")

    row = result[0]
    return {
        "node": dict(row["n"]),
        "labels": row["node_labels"],
        "relationships": row["relationships"],
    }


@router.get("/domains")
async def list_domains(
    min_papers: int = Query(5),
    limit: int = Query(100),
):
    """List all research domains in the graph."""
    results = await run_query(
        """
        MATCH (d:Domain)
        WHERE d.paper_count >= $min_papers
        OPTIONAL MATCH (d)<-[:BRIDGES]-(o:ResearchOpportunity)
        RETURN d.id AS id, d.name AS name,
               d.paper_count AS paper_count,
               count(o) AS opportunity_count
        ORDER BY d.paper_count DESC
        LIMIT $limit
        """,
        params={"min_papers": min_papers, "limit": limit},
    )
    return {"domains": results}
