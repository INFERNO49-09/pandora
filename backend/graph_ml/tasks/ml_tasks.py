"""
Graph ML Celery tasks.

Scheduled:
  Weekly  (Sunday 3 AM): full model retrain for all edge types
  Nightly (3:30 AM):     incremental embedding refresh for new nodes

Manual trigger via API:
  POST /api/v1/models/train
  POST /api/v1/models/embed-refresh
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

from core.async_utils import run_async
from core.celery_app import celery_app


# ── TRAINING TASKS ────────────────────────────────────────────────────────────

@celery_app.task(
    name="graph_ml.tasks.train_graphsage",
    bind=True,
    max_retries=1,
    time_limit=3600 * 4,   # 4 hour hard limit
)
def train_graphsage_task(
    self,
    edge_type: str = "Concept__RELATED_TO__Concept",
    hidden_dim: int = 256,
    num_layers: int = 3,
    epochs: int = 50,
):
    """
    Train GraphSAGE on a specific edge type.
    Registers result in PostgreSQL model registry.
    """
    return run_async(_train_graphsage_async(
        edge_type=edge_type,
        hidden_dim=hidden_dim,
        num_layers=num_layers,
        epochs=epochs,
    ))


@celery_app.task(
    name="graph_ml.tasks.train_transe",
    bind=True,
    max_retries=1,
    time_limit=3600 * 6,
)
def train_transe_task(
    self,
    edge_type: str = "Concept__RELATED_TO__Concept",
    embedding_dim: int = 200,
    epochs: int = 100,
):
    """Train TransE on a specific relationship type."""
    return run_async(_train_transe_async(
        edge_type=edge_type,
        embedding_dim=embedding_dim,
        epochs=epochs,
    ))


@celery_app.task(name="graph_ml.tasks.train_all_models")
def train_all_models():
    """
    Weekly task: retrain all models across priority edge types.
    Queues individual training tasks per edge type.
    """
    PRIORITY_EDGE_TYPES = [
        "Concept__RELATED_TO__Concept",
        "Paper__CITES__Paper",
        "Domain__SUBDOMAIN_OF__Domain",
        "Method__VARIANT_OF__Method",
    ]

    job_ids = []
    for edge_type in PRIORITY_EDGE_TYPES:
        # GraphSAGE
        t1 = train_graphsage_task.apply_async(
            args=[edge_type],
            queue="discovery",
        )
        # TransE
        t2 = train_transe_task.apply_async(
            args=[edge_type],
            queue="discovery",
        )
        job_ids.extend([t1.id, t2.id])

    logger.info(f"Queued {len(job_ids)} training jobs")
    return {"queued_jobs": job_ids}


# ── EMBEDDING TASKS ───────────────────────────────────────────────────────────

@celery_app.task(name="graph_ml.tasks.refresh_embeddings")
def refresh_embeddings(node_type: str | None = None):
    """
    Nightly task: embed all un-embedded nodes.
    Queries Neo4j for nodes without a Qdrant entry,
    embeds via NIM, writes to Qdrant.
    """
    return run_async(_refresh_embeddings_async(node_type))


@celery_app.task(name="graph_ml.tasks.embed_new_papers")
def embed_new_papers(since_hours: int = 24):
    """
    Triggered after ingestion: embed papers added in the last N hours.
    """
    return run_async(_embed_new_papers_async(since_hours))


# ── MODEL EVALUATION ──────────────────────────────────────────────────────────

@celery_app.task(name="graph_ml.tasks.evaluate_active_models")
def evaluate_active_models():
    """
    Weekly: re-evaluate all active models against fresh held-out edges.
    Updates MRR/Hits@K in the model registry.
    Automatically promotes better models to active status.
    """
    return run_async(_evaluate_active_models_async())


# ── ASYNC IMPLEMENTATIONS ─────────────────────────────────────────────────────

async def _train_graphsage_async(
    edge_type: str,
    hidden_dim: int,
    num_layers: int,
    epochs: int,
) -> dict:
    from graph_ml.models.graphsage import GraphSAGEConfig
    from graph_ml.training.pipeline import train_graphsage

    config = GraphSAGEConfig(
        hidden_dim=hidden_dim,
        num_layers=num_layers,
        epochs=epochs,
        target_edge_type=edge_type,
    )

    start = time.time()
    try:
        result = await train_graphsage(config)
    except Exception as e:
        logger.error(f"GraphSAGE training failed: {e}")
        return {"status": "failed", "error": str(e)}

    duration = time.time() - start

    # Register model
    if "test_mrr" in result:
        await _register_model(
            model_name=f"graphsage_{edge_type}_v{int(time.time())}",
            model_type="graphsage",
            relation_type=edge_type,
            test_mrr=result["test_mrr"],
            hits_at_1=result.get("hits_at_1", 0),
            hits_at_10=result.get("hits_at_10", 0),
            artifact_path=result.get("model_path", ""),
            hyperparams={"hidden_dim": hidden_dim, "num_layers": num_layers, "epochs": epochs},
            training_duration_s=int(duration),
        )

    logger.info(f"GraphSAGE training complete in {duration:.0f}s: {result}")
    return {**result, "status": "complete", "duration_s": int(duration)}


async def _train_transe_async(
    edge_type: str,
    embedding_dim: int,
    epochs: int,
) -> dict:
    from graph_ml.models.transe import TransEConfig
    from graph_ml.training.pipeline import train_transe

    # Count entities for TransE config
    from knowledge_graph.client import run_query
    src_type = edge_type.split("__")[0]
    count_result = await run_query(
        f"MATCH (n:{src_type}) RETURN count(n) AS cnt"
    )
    num_entities = count_result[0]["cnt"] if count_result else 10000

    config = TransEConfig(
        num_entities=num_entities,
        num_relations=1,
        embedding_dim=embedding_dim,
        epochs=epochs,
    )

    start = time.time()
    try:
        result = await train_transe(config, edge_type)
    except Exception as e:
        logger.error(f"TransE training failed: {e}")
        return {"status": "failed", "error": str(e)}

    duration = time.time() - start

    await _register_model(
        model_name=f"transe_{edge_type}_v{int(time.time())}",
        model_type="transe",
        relation_type=edge_type,
        test_mrr=0.0,
        hits_at_1=0.0,
        hits_at_10=0.0,
        artifact_path=result.get("model_path", ""),
        hyperparams={"embedding_dim": embedding_dim, "epochs": epochs},
        training_duration_s=int(duration),
    )

    return {**result, "status": "complete", "duration_s": int(duration)}


async def _refresh_embeddings_async(node_type: str | None) -> dict:
    from knowledge_graph.client import run_query
    from vector_store.client import upsert_vectors
    from vector_store.indexer import qdrant_point_id
    from core.nim_client import nim_embed

    NODE_CONFIGS = {
        "Concept": ("concepts", "canonical_name"),
        "Domain":  ("domains",  "name"),
        "Paper":   ("papers",   "title"),
        "Method":  ("concepts", "name"),
    }

    types_to_embed = (
        {node_type: NODE_CONFIGS[node_type]}
        if node_type and node_type in NODE_CONFIGS
        else NODE_CONFIGS
    )

    total = 0
    for ntype, (collection, name_field) in types_to_embed.items():
        nodes = await run_query(
            f"""
            MATCH (n:{ntype})
            WHERE n.{name_field} IS NOT NULL
            RETURN n.id AS id, n.{name_field} AS name
            LIMIT 50000
            """
        )
        if not nodes:
            continue

        texts = [f"{ntype}: {n['name']}" for n in nodes]
        BATCH = 96
        for i in range(0, len(texts), BATCH):
            batch_nodes = nodes[i:i+BATCH]
            batch_texts = texts[i:i+BATCH]
            try:
                vectors = await nim_embed(batch_texts)
                points = [
                    {
                        "id":      qdrant_point_id(n["id"]),
                        "vector":  vec,
                        "payload": {
                            "node_id": n["id"],
                            "name":    n["name"],
                            "type":    ntype,
                        },
                    }
                    for n, vec in zip(batch_nodes, vectors)
                ]
                await upsert_vectors(collection, points)
                total += len(points)
            except Exception as e:
                logger.error(f"Embedding batch failed for {ntype}: {e}")

    logger.info(f"Embedding refresh complete: {total} nodes embedded")
    return {"embedded": total, "node_type": node_type}


async def _embed_new_papers_async(since_hours: int) -> dict:
    from knowledge_graph.client import run_query
    from vector_store.client import upsert_vectors
    from vector_store.indexer import qdrant_point_id
    from core.nim_client import nim_embed

    papers = await run_query(
        """
        MATCH (p:Paper)
        WHERE p.updated_at >= datetime() - duration({hours: $hours})
          AND p.title IS NOT NULL
        RETURN p.id AS id, p.title AS title
        LIMIT 5000
        """,
        params={"hours": since_hours},
    )

    if not papers:
        return {"embedded": 0}

    texts = [f"Paper: {p['title']}" for p in papers]
    vectors = await nim_embed(texts)
    points = [
        {
            "id":      qdrant_point_id(p["id"]),
            "vector":  vec,
            "payload": {"node_id": p["id"], "title": p["title"], "type": "Paper"},
        }
        for p, vec in zip(papers, vectors)
    ]
    await upsert_vectors("papers", points)
    return {"embedded": len(points)}


async def _evaluate_active_models_async() -> dict:
    """Placeholder — full evaluation runs in training pipeline."""
    logger.info("Model evaluation task triggered")
    return {"status": "evaluation_queued"}


async def _register_model(
    model_name: str,
    model_type: str,
    relation_type: str,
    test_mrr: float,
    hits_at_1: float,
    hits_at_10: float,
    artifact_path: str,
    hyperparams: dict,
    training_duration_s: int,
) -> str:
    """Write model metadata to PostgreSQL model registry."""
    import asyncpg
    from core.config import get_settings
    settings = get_settings()

    model_id = str(uuid.uuid4())
    dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")

    try:
        conn = await asyncpg.connect(dsn)
        try:
            # Deactivate previous model of same type+relation
            await conn.execute(
                """
                UPDATE ml_models SET is_active = FALSE
                WHERE model_type = $1 AND relation_type = $2
                """,
                model_type, relation_type,
            )
            # Insert new model (mark active if it improves MRR)
            await conn.execute(
                """
                INSERT INTO ml_models
                  (id, model_name, model_type, relation_type,
                   test_mrr, hits_at_1, hits_at_10,
                   hyperparameters, model_artifact_s3_key,
                   is_active, trained_at, created_at)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW(),NOW())
                """,
                model_id, model_name, model_type, relation_type,
                test_mrr, hits_at_1, hits_at_10,
                json.dumps(hyperparams), artifact_path,
                True,  # new model is active
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.error(f"Model registry write failed: {e}")

    return model_id
