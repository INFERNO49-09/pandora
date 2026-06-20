"""
Bookmarks API — save and manage research items.

GET    /bookmarks            — list user's bookmarks (paginated)
POST   /bookmarks            — create a bookmark
DELETE /bookmarks/{id}       — remove a bookmark
GET    /bookmarks/check/{entity_type}/{entity_id}  — check if bookmarked
PATCH  /bookmarks/{id}       — update notes on a bookmark
"""
from __future__ import annotations

import uuid
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from auth.middleware import User, get_current_user
from core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])

VALID_ENTITY_TYPES = {"opportunity", "paper", "concept", "domain"}


# ── DB HELPER ─────────────────────────────────────────────────────────────────

async def _get_conn() -> asyncpg.Connection:
    dsn = settings.POSTGRES_DSN.replace("+asyncpg", "")
    return await asyncpg.connect(dsn)


# ── REQUEST / RESPONSE MODELS ─────────────────────────────────────────────────

class BookmarkCreate(BaseModel):
    entity_type: str        # opportunity | paper | concept | domain
    entity_id: str
    entity_title: str | None = None
    notes: str | None = None


class BookmarkUpdate(BaseModel):
    notes: str | None = None
    entity_title: str | None = None


class BookmarkOut(BaseModel):
    id: str
    entity_type: str
    entity_id: str
    entity_title: str | None
    notes: str | None
    created_at: str


# ── ENDPOINTS ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_bookmarks(
    current_user: Annotated[User, Depends(get_current_user)],
    entity_type: str | None = Query(None, description="Filter by type: opportunity, paper, concept, domain"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all bookmarks for the authenticated user."""
    conn = await _get_conn()
    try:
        args: list = [current_user.id]
        where = "WHERE user_id = $1"

        if entity_type:
            if entity_type not in VALID_ENTITY_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"entity_type must be one of: {', '.join(VALID_ENTITY_TYPES)}",
                )
            args.append(entity_type)
            where += f" AND entity_type = ${len(args)}"

        args.extend([limit, offset])

        rows = await conn.fetch(
            f"""
            SELECT id, entity_type, entity_id, entity_title, notes, created_at
            FROM user_bookmarks
            {where}
            ORDER BY created_at DESC
            LIMIT ${len(args) - 1}
            OFFSET ${len(args)}
            """,
            *args,
        )

        # Count total for pagination
        count_args = args[: -2]  # strip limit/offset
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM user_bookmarks {where}",
            *count_args,
        )

        return {
            "bookmarks": [
                {
                    **dict(r),
                    "id": str(r["id"]),
                    "created_at": r["created_at"].isoformat(),
                }
                for r in rows
            ],
            "total": count,
            "offset": offset,
            "limit": limit,
        }
    finally:
        await conn.close()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_bookmark(
    req: BookmarkCreate,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Bookmark an entity. Idempotent — re-bookmarking returns the existing entry."""
    if req.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"entity_type must be one of: {', '.join(VALID_ENTITY_TYPES)}",
        )

    conn = await _get_conn()
    try:
        # Upsert: update notes/title if already bookmarked
        row = await conn.fetchrow(
            """
            INSERT INTO user_bookmarks (id, user_id, entity_type, entity_id, entity_title, notes)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id, entity_type, entity_id)
            DO UPDATE SET
                entity_title = COALESCE(EXCLUDED.entity_title, user_bookmarks.entity_title),
                notes        = COALESCE(EXCLUDED.notes,        user_bookmarks.notes)
            RETURNING id, entity_type, entity_id, entity_title, notes, created_at
            """,
            str(uuid.uuid4()),
            current_user.id,
            req.entity_type,
            req.entity_id,
            req.entity_title,
            req.notes,
        )
        return {
            **dict(row),
            "id": str(row["id"]),
            "created_at": row["created_at"].isoformat(),
        }
    finally:
        await conn.close()


@router.get("/check/{entity_type}/{entity_id}")
async def check_bookmark(
    entity_type: str,
    entity_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Check whether a specific entity is bookmarked by the current user."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, notes, created_at
            FROM user_bookmarks
            WHERE user_id = $1 AND entity_type = $2 AND entity_id = $3
            """,
            current_user.id,
            entity_type,
            entity_id,
        )
        if row:
            return {
                "bookmarked": True,
                "bookmark_id": str(row["id"]),
                "notes": row["notes"],
                "created_at": row["created_at"].isoformat(),
            }
        return {"bookmarked": False}
    finally:
        await conn.close()


@router.patch("/{bookmark_id}")
async def update_bookmark(
    bookmark_id: str,
    req: BookmarkUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Update notes or title on a bookmark."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            UPDATE user_bookmarks
            SET notes        = COALESCE($1, notes),
                entity_title = COALESCE($2, entity_title)
            WHERE id = $3 AND user_id = $4
            RETURNING id, entity_type, entity_id, entity_title, notes, created_at
            """,
            req.notes,
            req.entity_title,
            bookmark_id,
            current_user.id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Bookmark not found")
        return {
            **dict(row),
            "id": str(row["id"]),
            "created_at": row["created_at"].isoformat(),
        }
    finally:
        await conn.close()


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(
    bookmark_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Delete a bookmark by ID."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM user_bookmarks WHERE id = $1 AND user_id = $2",
            bookmark_id,
            current_user.id,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=404, detail="Bookmark not found")
    finally:
        await conn.close()
