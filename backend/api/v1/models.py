"""
Model Registry API.

GET  /models            — list all models with metrics
GET  /models/active     — currently active models per relation type
GET  /models/{id}       — single model detail
POST /models/train      — trigger training run (admin)
POST /models/embed      — trigger embedding refresh (admin)
GET  /models/metrics    — MRR / Hits@K time series for dashboard
"""
from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from loguru import logger

from auth.middleware import User, get_current_user, require_admin, optional_user
from core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/models", tags=["models"])


# ── DB HELPER ─────────────────────────────────────────────────────────────────

async def _get_conn():
    dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    return await asyncpg.connect(dsn)


# ── SCHEMAS ───────────────────────────────────────────────────────────────────

class TrainRequest(BaseModel):
    model_type: str               # graphsage | transe | rotate
    edge_type: str                # e.g. Concept__RELATED_TO__Concept
    hidden_dim: int = 256
    num_layers: int = 3
    embedding_dim: int = 200
    epochs: int = 50


class EmbedRequest(BaseModel):
    node_type: str | None = None  # None = all types


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_models(
    model_type: str | None = Query(None),
    relation_type: str | None = Query(None),
    active_only: bool = Query(False),
    limit: int = Query(50, le=200),
    _user: User | None = Depends(optional_user),
):
    """List all trained models with performance metrics."""
    conn = await _get_conn()
    try:
        conditions = []
        args: list = []

        if model_type:
            args.append(model_type)
            conditions.append(f"model_type = ${len(args)}")
        if relation_type:
            args.append(relation_type)
            conditions.append(f"relation_type = ${len(args)}")
        if active_only:
            conditions.append("is_active = TRUE")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        args.append(limit)

        rows = await conn.fetch(
            f"""
            SELECT id, model_name, model_type, relation_type,
                   train_mrr, val_mrr, test_mrr,
                   hits_at_1, hits_at_10,
                   is_active, trained_at, created_at,
                   hyperparameters
            FROM ml_models
            {where}
            ORDER BY trained_at DESC NULLS LAST
            LIMIT ${len(args)}
            """,
            *args,
        )
        return {
            "models": [dict(r) for r in rows],
            "total": len(rows),
        }
    finally:
        await conn.close()


@router.get("/active")
async def get_active_models(_user: User | None = Depends(optional_user)):
    """Return the currently active model for each relation type."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (relation_type)
                   id, model_name, model_type, relation_type,
                   test_mrr, hits_at_1, hits_at_10,
                   trained_at
            FROM ml_models
            WHERE is_active = TRUE
            ORDER BY relation_type, trained_at DESC NULLS LAST
            """
        )
        return {"active_models": [dict(r) for r in rows]}
    finally:
        await conn.close()


@router.get("/metrics")
async def get_model_metrics(
    model_type: str | None = Query(None),
    limit: int = Query(20),
    _user: User | None = Depends(optional_user),
):
    """
    Return MRR time series for the model dashboard.
    Each entry = one training run with its metrics + timestamp.
    """
    conn = await _get_conn()
    try:
        condition = "WHERE model_type = $1" if model_type else ""
        args = [model_type] if model_type else []
        args.append(limit)

        rows = await conn.fetch(
            f"""
            SELECT model_type, relation_type,
                   test_mrr, hits_at_1, hits_at_10,
                   is_active, trained_at
            FROM ml_models
            {condition}
            ORDER BY trained_at DESC NULLS LAST
            LIMIT ${len(args)}
            """,
            *args,
        )

        # Group by model_type + relation_type for time series
        series: dict[str, list] = {}
        for r in rows:
            key = f"{r['model_type']}/{r['relation_type']}"
            if key not in series:
                series[key] = []
            series[key].append({
                "trained_at": str(r["trained_at"]) if r["trained_at"] else None,
                "test_mrr":   round(float(r["test_mrr"] or 0), 4),
                "hits_at_1":  round(float(r["hits_at_1"] or 0), 4),
                "hits_at_10": round(float(r["hits_at_10"] or 0), 4),
                "is_active":  r["is_active"],
            })

        return {"series": series}
    finally:
        await conn.close()


@router.get("/{model_id}")
async def get_model(
    model_id: str,
    _user: User | None = Depends(optional_user),
):
    """Get full detail for a single model."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM ml_models WHERE id = $1", model_id
        )
        if not row:
            raise HTTPException(status_code=404, detail="Model not found")
        return dict(row)
    finally:
        await conn.close()


@router.post("/train")
async def trigger_training(
    req: TrainRequest,
    admin: Annotated[User, Depends(require_admin)],
):
    """
    Trigger a model training run (admin only).
    Returns Celery task ID for polling.
    """
    from graph_ml.tasks.ml_tasks import train_graphsage_task, train_transe_task

    if req.model_type == "graphsage":
        task = train_graphsage_task.apply_async(
            kwargs={
                "edge_type":   req.edge_type,
                "hidden_dim":  req.hidden_dim,
                "num_layers":  req.num_layers,
                "epochs":      req.epochs,
            },
            queue="discovery",
        )
    elif req.model_type in ("transe", "rotate"):
        task = train_transe_task.apply_async(
            kwargs={
                "edge_type":     req.edge_type,
                "embedding_dim": req.embedding_dim,
                "epochs":        req.epochs,
            },
            queue="discovery",
        )
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model_type: {req.model_type}. Use: graphsage, transe, rotate",
        )

    return {
        "task_id":    task.id,
        "status":     "queued",
        "model_type": req.model_type,
        "edge_type":  req.edge_type,
        "status_url": f"/api/v1/ingest/jobs/{task.id}",
    }


@router.post("/embed")
async def trigger_embedding_refresh(
    req: EmbedRequest,
    admin: Annotated[User, Depends(require_admin)],
):
    """Trigger embedding refresh for all nodes or a specific type (admin only)."""
    from graph_ml.tasks.ml_tasks import refresh_embeddings

    task = refresh_embeddings.apply_async(
        kwargs={"node_type": req.node_type},
        queue="discovery",
    )
    return {
        "task_id":   task.id,
        "node_type": req.node_type or "all",
        "status":    "queued",
    }


@router.post("/{model_id}/activate")
async def activate_model(
    model_id: str,
    admin: Annotated[User, Depends(require_admin)],
):
    """Manually promote a specific model to active status (admin only)."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT model_type, relation_type FROM ml_models WHERE id = $1",
            model_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Model not found")

        # Deactivate siblings
        await conn.execute(
            """
            UPDATE ml_models SET is_active = FALSE
            WHERE model_type = $1 AND relation_type = $2
            """,
            row["model_type"], row["relation_type"],
        )
        # Activate target
        await conn.execute(
            "UPDATE ml_models SET is_active = TRUE WHERE id = $1",
            model_id,
        )
        return {"activated": model_id}
    finally:
        await conn.close()
