"""
Link prediction API.
For MVP: uses embedding similarity as a lightweight link predictor.
Full GraphSAGE/TransE models are added in Phase 2.
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from knowledge_graph.client import run_query
from vector_store.client import search_similar
from core.nim_client import nim_embed_single
from models.types import LinkPrediction
from datetime import datetime

router = APIRouter(prefix="/predict", tags=["link-prediction"])


class LinkPredictionRequest(BaseModel):
    node_id: str
    node_type: str = "Concept"          # Concept, Domain, Method
    relation_type: str = "RELATED_TO"   # predicted relation type
    top_k: int = 10
    min_confidence: float = 0.5


@router.post("/links")
async def predict_links(req: LinkPredictionRequest):
    """
    Predict missing links from a given node.

    MVP implementation: embedding similarity in Qdrant.
    Finds nodes that are semantically close but not yet connected in the graph.
    Nodes that SHOULD be connected but aren't = predicted missing links.
    """
    if req.top_k > 50:
        raise HTTPException(status_code=400, detail="top_k cannot exceed 50")

    # Get source node
    node_result = await run_query(
        "MATCH (n {id: $node_id}) RETURN n, labels(n) AS labels",
        params={"node_id": req.node_id},
    )

    if not node_result:
        raise HTTPException(status_code=404, detail=f"Node {req.node_id} not found")

    node = dict(node_result[0]["n"])
    node_name = node.get("canonical_name") or node.get("name") or node.get("title", "")

    # Get existing connections (to exclude from predictions)
    existing = await run_query(
        """
        MATCH (n {id: $node_id})-[r]-(neighbor)
        RETURN neighbor.id AS neighbor_id
        """,
        params={"node_id": req.node_id},
    )
    existing_ids = {r["neighbor_id"] for r in existing} | {req.node_id}

    # Embed the source node
    collection_map = {
        "Concept": "concepts",
        "Domain": "domains",
        "Method": "concepts",  # methods go in concepts collection for MVP
        "Paper": "papers",
    }
    collection = collection_map.get(req.node_type, "concepts")

    try:
        query_vector = await nim_embed_single(
            f"{req.node_type}: {node_name}"
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Embedding service error: {e}")

    # Search for similar nodes
    similar = await search_similar(
        collection=collection,
        query_vector=query_vector,
        top_k=req.top_k + len(existing_ids) + 10,  # overfetch, then filter
        score_threshold=req.min_confidence,
    )

    # Filter out already-connected nodes
    predictions = []
    for hit in similar:
        target_id = hit["payload"].get("node_id")
        if target_id in existing_ids:
            continue

        predictions.append(
            LinkPrediction(
                source_node_id=req.node_id,
                source_node_type=req.node_type,
                source_name=node_name,
                target_node_id=target_id or hit["id"],
                target_node_type=req.node_type,
                target_name=hit["payload"].get("name", ""),
                predicted_relation=req.relation_type,
                confidence=round(hit["score"], 4),
                model_name="embedding_similarity_v1",
                generated_at=datetime.utcnow(),
            ).model_dump()
        )

        if len(predictions) >= req.top_k:
            break

    return {
        "source_node": {"id": req.node_id, "name": node_name, "type": req.node_type},
        "predicted_relation": req.relation_type,
        "predictions": predictions,
        "model": "embedding_similarity_v1",
        "note": "Phase 2 will use GraphSAGE + TransE ensemble",
    }


@router.get("/missing-connections")
async def find_missing_connections(
    domain: str = Query(..., description="Domain name to analyze"),
    limit: int = Query(20, le=100),
):
    """
    Find concept pairs within a domain that are semantically similar
    but have no graph connection — likely missing links.
    """
    # Get concepts in this domain
    concepts = await run_query(
        """
        MATCH (d:Domain)
        WHERE toLower(d.name) CONTAINS toLower($domain)
        MATCH (p:Paper)-[:IN_DOMAIN]->(d)
        MATCH (p)-[:USES]->(c:Concept)
        RETURN DISTINCT c.id AS id, c.canonical_name AS name
        LIMIT 100
        """,
        params={"domain": domain},
    )

    if not concepts:
        raise HTTPException(
            status_code=404,
            detail=f"No concepts found for domain: {domain}"
        )

    # For each concept, find similar concepts not yet connected
    missing_links = []
    seen_pairs = set()

    for concept in concepts[:20]:  # process top 20 for MVP
        concept_id = concept["id"]
        concept_name = concept["name"]

        if not concept_name:
            continue

        try:
            query_vec = await nim_embed_single(f"Scientific concept: {concept_name}")
        except Exception:
            continue

        similar = await search_similar(
            collection="concepts",
            query_vector=query_vec,
            top_k=10,
            score_threshold=0.70,
        )

        # Check which are not connected in graph
        for hit in similar:
            target_id = hit["payload"].get("node_id")
            if not target_id or target_id == concept_id:
                continue

            pair_key = tuple(sorted([concept_id, target_id]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # Check for existing edge
            edge_check = await run_query(
                """
                MATCH (a {id: $id_a})-[r]-(b {id: $id_b})
                RETURN count(r) AS edge_count
                """,
                params={"id_a": concept_id, "id_b": target_id},
            )

            if edge_check and edge_check[0]["edge_count"] == 0:
                missing_links.append({
                    "source_id": concept_id,
                    "source_name": concept_name,
                    "target_id": target_id,
                    "target_name": hit["payload"].get("name", ""),
                    "similarity": round(hit["score"], 4),
                    "predicted_relation": "RELATED_TO",
                })

        if len(missing_links) >= limit:
            break

    missing_links.sort(key=lambda x: x["similarity"], reverse=True)

    return {
        "domain": domain,
        "missing_connections": missing_links[:limit],
        "analyzed_concepts": min(len(concepts), 20),
    }
