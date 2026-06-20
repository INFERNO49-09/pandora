"""
Query History API — log and retrieve past copilot / search queries.

GET  /history         — list user's recent queries
GET  /history/stats   — per-type counts for the user profile page
POST /history         — internal: log a query (called by other routers)
"""
from __future__ import annotations

import uuid
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Query

from auth.middleware import User, get_current_user, optional_user
from core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/history", tags=["history"])

VALID_TYPES = {"copilot", "predict", "gap", "search"}


# ── DB HELPER ─────────────────────────────────────────────────────────────────

async def _get_conn() -> asyncpg.Connection:
    dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    return await asyncpg.connect(dsn)


# ── SHARED HELPER (imported by other routers) ─────────────────────────────────

async def log_query(
    user_id: str | None,
    query_text: str,
    query_type: str,
    response_ms: int | None = None,
    agents_used: list[str] | None = None,
) -> str | None:
    """
    Persist a query to history. Returns the new history row ID.
    Swallows all exceptions — logging must never break the main flow.
    """
    if query_type not in VALID_TYPES:
        return None
    try:
        conn = await _get_conn()
        row_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO query_history
                (id, user_id, query_text, query_type, response_ms, agents_used)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            row_id,
            user_id,
            query_text[:2000],   # hard cap
            query_type,
            response_ms,
            agents_used or [],
        )
        await conn.close()
        return row_id
    except Exception:
        return None


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_history(
    current_user: Annotated[User, Depends(get_current_user)],
    query_type: str | None = Query(None, description="Filter: copilot | predict | gap | search"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Return the authenticated user's recent queries, newest first."""
    conn = await _get_conn()
    try:
        args: list = [current_user.id]
        where = "WHERE user_id = $1"

        if query_type and query_type in VALID_TYPES:
            args.append(query_type)
            where += f" AND query_type = ${len(args)}"

        args.extend([limit, offset])

        rows = await conn.fetch(
            f"""
            SELECT id, query_text, query_type, response_ms, agents_used, created_at
            FROM query_history
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(args) - 1}
            OFFSET ${len(args)}
            """,
            *args,
        )

        return {
            "queries": [
                {
                    **dict(r),
                    "id": str(r["id"]),
                    "created_at": r["created_at"].isoformat(),
                    "agents_used": list(r["agents_used"] or []),
                }
                for r in rows
            ],
            "limit": limit,
            "offset": offset,
        }
    finally:
        await conn.close()


@router.get("/stats")
async def get_history_stats(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Return per-type query counts and last activity for the user profile."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT query_type,
                   COUNT(*)            AS total,
                   MAX(created_at)     AS last_at,
                   AVG(response_ms)    AS avg_ms
            FROM query_history
            WHERE user_id = $1
            GROUP BY query_type
            """,
            current_user.id,
        )
        stats = {
            r["query_type"]: {
                "total": r["total"],
                "last_at": r["last_at"].isoformat() if r["last_at"] else None,
                "avg_response_ms": round(r["avg_ms"]) if r["avg_ms"] else None,
            }
            for r in rows
        }
        grand_total = sum(v["total"] for v in stats.values())
        return {"by_type": stats, "total_queries": grand_total}
    finally:
        await conn.close()
