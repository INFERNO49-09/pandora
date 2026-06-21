"""
Link prediction API backed by the Phase 2 ensemble predictor.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from graph_ml.inference.predictor import EnsemblePredictor
from knowledge_graph.client import run_query
from models.types import LinkPrediction


router = APIRouter(prefix="/predict", tags=["link-prediction"])


class LinkPredictionRequest(BaseModel):
    node_id: str
    node_type: str = "Concept"
    relation_type: str = "RELATED_TO"
    top_k: int = Field(default=10, ge=1, le=50)
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)


@router.post("/links")
async def predict_links(req: LinkPredictionRequest):
    """
    Predict missing graph links using embedding similarity plus trained models
    when GraphSAGE or TransE artifacts are available.
    """
    node_result = await run_query(
        """
        MATCH (n {id: $node_id})
        RETURN n.id AS id,
               coalesce(n.canonical_name, n.name, n.title) AS name,
               labels(n)[0] AS type
        """,
        params={"node_id": req.node_id},
    )
    if not node_result:
        raise HTTPException(status_code=404, detail=f"Node {req.node_id} not found")

    source = node_result[0]
    predictor = EnsemblePredictor()
    predictions = await predictor.predict(
        node_id=req.node_id,
        node_type=req.node_type,
        relation_type=req.relation_type,
        top_k=req.top_k,
        min_confidence=req.min_confidence,
    )

    return {
        "source_node": {
            "id": source["id"],
            "name": source["name"],
            "type": source["type"],
        },
        "predicted_relation": req.relation_type,
        "predictions": [
            LinkPrediction(
                source_node_id=req.node_id,
                source_node_type=req.node_type,
                source_name=source["name"] or req.node_id,
                target_node_id=prediction.target_node_id,
                target_node_type=prediction.target_type,
                target_name=prediction.target_name,
                predicted_relation=prediction.predicted_relation,
                confidence=prediction.confidence,
                model_name=prediction.model_name,
                generated_at=datetime.utcnow(),
            ).model_dump()
            | {"model_scores": prediction.model_scores}
            for prediction in predictions
        ],
        "model": "phase2_ensemble",
    }


@router.get("/missing-connections")
async def find_missing_connections(
    domain: str = Query(..., description="Domain name to analyze"),
    limit: int = Query(20, le=100),
):
    """
    Find likely missing concept links inside a domain using the same ensemble path.
    """
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
        raise HTTPException(status_code=404, detail=f"No concepts found for domain: {domain}")

    predictor = EnsemblePredictor()
    missing_links: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    for concept in concepts[:25]:
        predicted = await predictor.predict(
            node_id=concept["id"],
            node_type="Concept",
            relation_type="RELATED_TO",
            top_k=10,
            min_confidence=0.55,
        )
        for item in predicted:
            if item.target_type != "Concept":
                continue
            pair_key = tuple(sorted([concept["id"], item.target_node_id]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            missing_links.append(
                {
                    "source_id": concept["id"],
                    "source_name": concept["name"],
                    "target_id": item.target_node_id,
                    "target_name": item.target_name,
                    "confidence": item.confidence,
                    "predicted_relation": item.predicted_relation,
                    "model_scores": item.model_scores,
                }
            )
            if len(missing_links) >= limit:
                break
        if len(missing_links) >= limit:
            break

    missing_links.sort(key=lambda row: row["confidence"], reverse=True)
    return {
        "domain": domain,
        "missing_connections": missing_links[:limit],
        "analyzed_concepts": min(len(concepts), 25),
        "model": "phase2_ensemble",
    }
