"""
Graph ML Inference Engine.

Runs link prediction at query time using an ensemble of:
  1. Embedding similarity (always available — no training needed)
  2. GraphSAGE (if trained model exists)
  3. TransE (if trained model exists)

Ensemble: weighted average by each model's validation MRR.
Weights are loaded from PostgreSQL model registry.

All predictions are cached in Redis (TTL: 1 hour).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from vector_store.client import search_similar
from knowledge_graph.client import run_query
from core.nim_client import nim_embed_single


@dataclass
class PredictionResult:
    target_node_id: str
    target_name: str
    target_type: str
    predicted_relation: str
    confidence: float          # ensemble score 0-1
    model_scores: dict[str, float]   # per-model breakdown
    model_name: str = "ensemble"


class EnsemblePredictor:
    """
    Ensemble link predictor.

    For the MVP, embedding_similarity is the default.
    GraphSAGE and TransE models are loaded automatically
    when their artifact files are present.
    """

    CACHE_TTL = 3600  # 1 hour

    def __init__(self):
        self._graphsage = None   # loaded lazily
        self._transe    = None   # loaded lazily
        self._redis     = None

    async def _get_redis(self):
        if self._redis is None:
            import redis.asyncio as aioredis
            from core.config import get_settings
            settings = get_settings()
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    # ── PUBLIC API ─────────────────────────────────────────────────────────

    async def predict(
        self,
        node_id: str,
        node_type: str,
        relation_type: str = "RELATED_TO",
        top_k: int = 15,
        min_confidence: float = 0.40,
    ) -> list[PredictionResult]:
        """
        Main prediction entry point.
        Checks cache first, then runs ensemble.
        """
        cache_key = f"pred:{node_id}:{node_type}:{relation_type}:{top_k}:{min_confidence}"
        r = await self._get_redis()

        # Cache hit
        cached = await r.get(cache_key)
        if cached:
            data = json.loads(cached)
            return [PredictionResult(**d) for d in data]

        # Get existing edges to exclude
        existing = await self._get_existing_edges(node_id)

        # Run all available models
        model_results: dict[str, list[tuple[str, float]]] = {}

        emb_results = await self._embedding_similarity(
            node_id, node_type, top_k * 3, existing
        )
        if emb_results:
            model_results["embedding_similarity"] = emb_results

        sage_results = await self._graphsage_predict(
            node_id, node_type, top_k * 3, existing
        )
        if sage_results:
            model_results["graphsage"] = sage_results

        transe_results = await self._transe_predict(
            node_id, relation_type, top_k * 3, existing
        )
        if transe_results:
            model_results["transe"] = transe_results

        # Ensemble
        predictions = self._ensemble(
            model_results, relation_type, top_k, min_confidence
        )
        predictions = await self.enrich_predictions(predictions)

        # Cache result
        await r.set(cache_key, json.dumps([p.__dict__ for p in predictions]), ex=self.CACHE_TTL)

        return predictions

    # ── MODEL RUNNERS ──────────────────────────────────────────────────────

    async def _embedding_similarity(
        self,
        node_id: str,
        node_type: str,
        top_k: int,
        existing_ids: set[str],
    ) -> list[tuple[str, float]]:
        """
        Embedding similarity baseline.
        Finds nodes with similar embeddings not yet connected.
        """
        collection_map = {
            "Concept": "concepts",
            "Domain":  "domains",
            "Method":  "concepts",
            "Paper":   "papers",
        }
        collection = collection_map.get(node_type, "concepts")

        # Get node name for embedding
        result = await run_query(
            "MATCH (n {id: $id}) RETURN coalesce(n.canonical_name, n.name, n.title) AS name",
            params={"id": node_id},
        )
        if not result or not result[0].get("name"):
            return []

        name = result[0]["name"]
        try:
            vec = await nim_embed_single(f"{node_type}: {name}")
        except Exception as e:
            logger.warning(f"Embedding failed for {node_id}: {e}")
            return []

        hits = await search_similar(
            collection=collection,
            query_vector=vec,
            top_k=top_k + len(existing_ids) + 10,
            score_threshold=0.50,
        )

        results = []
        for h in hits:
            tid = h["payload"].get("node_id")
            if tid and tid not in existing_ids and tid != node_id:
                results.append((tid, float(h["score"])))
            if len(results) >= top_k:
                break

        return results

    async def _graphsage_predict(
        self,
        node_id: str,
        node_type: str,
        top_k: int,
        existing_ids: set[str],
    ) -> list[tuple[str, float]]:
        """
        GraphSAGE inference. Skips gracefully if model not loaded.
        """
        model_path = self._find_graphsage_artifact(node_type)
        if not model_path.exists():
            logger.debug(f"No GraphSAGE model at {model_path}, skipping")
            return []

        try:
            import torch
            checkpoint = torch.load(model_path, map_location="cpu")
            node_id_map = checkpoint.get("node_id_map", {}).get(node_type, {})
            node_embeddings = checkpoint.get("node_embeddings", {}).get(node_type)
            if node_id not in node_id_map or node_embeddings is None:
                return []

            reverse_map = {idx: nid for nid, idx in node_id_map.items()}
            source_idx = node_id_map[node_id]
            source_emb = node_embeddings[source_idx]
            scores = torch.matmul(node_embeddings, source_emb)
            ranked = torch.argsort(scores, descending=True).tolist()

            results: list[tuple[str, float]] = []
            max_score = float(scores[ranked[0]].item()) if ranked else 1.0
            for idx in ranked:
                target_id = reverse_map.get(idx)
                if not target_id or target_id == node_id or target_id in existing_ids:
                    continue
                raw_score = float(scores[idx].item())
                normalized = raw_score / max_score if max_score > 0 else raw_score
                results.append((target_id, max(0.0, min(1.0, normalized))))
                if len(results) >= top_k:
                    break
            logger.debug(f"GraphSAGE model loaded from {model_path}")
            return results
        except Exception as e:
            logger.warning(f"GraphSAGE inference failed: {e}")
            return []

    def _find_graphsage_artifact(self, node_type: str) -> Path:
        candidates = [
            Path(f"/models/pandora_graphsage_{node_type}__RELATED_TO__{node_type}.pt"),
            Path(f"/tmp/pandora_graphsage_{node_type}__RELATED_TO__{node_type}.pt"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate

        for root in (Path("/models"), Path("/tmp")):
            matches = sorted(root.glob(f"pandora_graphsage_*__*__{node_type}.pt"))
            if matches:
                return matches[-1]
        return candidates[0]

    async def _transe_predict(
        self,
        node_id: str,
        relation_type: str,
        top_k: int,
        existing_ids: set[str],
    ) -> list[tuple[str, float]]:
        """
        TransE tail prediction. Skips if model not loaded.
        """
        model_path = self._find_transe_artifact(relation_type)
        if not model_path.exists():
            return []

        try:
            import torch
            checkpoint = torch.load(model_path, map_location="cpu")
            entity_emb = checkpoint.get("entity_emb")
            relation_emb = checkpoint.get("relation_emb")
            node_id_map = checkpoint.get("node_id_map", {})
            if entity_emb is None or relation_emb is None or node_id not in node_id_map:
                return []
            reverse_map = {idx: nid for nid, idx in node_id_map.items()}
            head_idx = node_id_map[node_id]
            head = entity_emb[head_idx]
            relation = relation_emb[0]
            scores = -torch.linalg.vector_norm(head + relation - entity_emb, dim=1)
            ranked = torch.argsort(scores, descending=True).tolist()

            best = float(scores[ranked[0]].item()) if ranked else 0.0
            worst = float(scores[ranked[min(len(ranked) - 1, top_k * 3)]].item()) if ranked else -1.0
            denom = max(best - worst, 1e-6)
            results: list[tuple[str, float]] = []
            for idx in ranked:
                target_id = reverse_map.get(idx)
                if not target_id or target_id == node_id or target_id in existing_ids:
                    continue
                normalized = (float(scores[idx].item()) - worst) / denom
                results.append((target_id, max(0.0, min(1.0, normalized))))
                if len(results) >= top_k:
                    break
            logger.debug(f"TransE model loaded for relation {relation_type}")
            return results
        except Exception as e:
            logger.warning(f"TransE inference failed: {e}")
            return []

    def _find_transe_artifact(self, relation_type: str) -> Path:
        candidates = [
            Path(f"/models/pandora_transe_Concept__{relation_type}__Concept.pt"),
            Path(f"/tmp/pandora_transe_Concept__{relation_type}__Concept.pt"),
            Path(f"/models/pandora_transe_Paper__{relation_type}__Paper.pt"),
            Path(f"/tmp/pandora_transe_Paper__{relation_type}__Paper.pt"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        for root in (Path("/models"), Path("/tmp")):
            matches = sorted(root.glob(f"pandora_transe_*__{relation_type}__*.pt"))
            if matches:
                return matches[-1]
        return candidates[0]

    # ── ENSEMBLE LOGIC ─────────────────────────────────────────────────────

    def _ensemble(
        self,
        model_results: dict[str, list[tuple[str, float]]],
        relation_type: str,
        top_k: int,
        min_confidence: float,
    ) -> list[PredictionResult]:
        """
        Weighted ensemble: combine scores from all models.

        Weights reflect expected accuracy (from model registry).
        embedding_similarity is always weight=1.0 (baseline).
        Trained models get weight proportional to their val MRR.
        """
        MODEL_WEIGHTS = {
            "embedding_similarity": 1.0,
            "graphsage":            1.5,   # higher when trained
            "transe":               1.3,
        }

        # Aggregate scores per target node
        score_map: dict[str, dict[str, float]] = {}
        weight_map: dict[str, dict[str, float]] = {}

        for model_name, results in model_results.items():
            weight = MODEL_WEIGHTS.get(model_name, 1.0)
            max_score = max((s for _, s in results), default=1.0)

            for target_id, raw_score in results:
                normalized = raw_score / max_score if max_score > 0 else raw_score
                weighted   = normalized * weight

                if target_id not in score_map:
                    score_map[target_id] = {}
                    weight_map[target_id] = {}
                score_map[target_id][model_name] = weighted
                weight_map[target_id][model_name] = weight

        # Compute final ensemble score from available model outputs only.
        predictions = []
        for target_id, per_model in score_map.items():
            available_weight = sum(weight_map[target_id].values()) or 1.0
            ensemble_score = sum(per_model.values()) / available_weight
            if ensemble_score < min_confidence:
                continue

            predictions.append(
                PredictionResult(
                    target_node_id=target_id,
                    target_name="",          # populated below
                    target_type="",
                    predicted_relation=relation_type,
                    confidence=round(ensemble_score, 4),
                    model_scores=per_model,
                    model_name="ensemble" if len(per_model) > 1 else list(per_model.keys())[0],
                )
            )

        # Sort by confidence
        predictions.sort(key=lambda p: p.confidence, reverse=True)
        predictions = predictions[:top_k]

        return predictions

    async def enrich_predictions(
        self,
        predictions: list[PredictionResult],
    ) -> list[PredictionResult]:
        """Populate target_name and target_type from Neo4j."""
        if not predictions:
            return predictions

        ids = [p.target_node_id for p in predictions]
        results = await run_query(
            """
            MATCH (n)
            WHERE n.id IN $ids
            RETURN n.id AS id,
                   coalesce(n.canonical_name, n.name, n.title) AS name,
                   labels(n)[0] AS type
            """,
            params={"ids": ids},
        )

        lookup = {r["id"]: r for r in results}
        for p in predictions:
            row = lookup.get(p.target_node_id, {})
            p.target_name = row.get("name", p.target_node_id)
            p.target_type = row.get("type", "Unknown")

        return predictions

    async def _get_existing_edges(self, node_id: str) -> set[str]:
        """Get IDs of all nodes already connected to this node."""
        results = await run_query(
            "MATCH (n {id: $id})-[r]-(neighbor) RETURN neighbor.id AS nid",
            params={"id": node_id},
        )
        return {r["nid"] for r in results if r["nid"]}
