"""
PostgreSQL-backed ingestion state.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg
from loguru import logger

from core.config import get_settings


_pool: asyncpg.Pool | None = None
_pool_loop: asyncio.AbstractEventLoop | None = None
_schema_ready: bool = False


def _asyncpg_dsn() -> str:
    dsn = get_settings().POSTGRES_DSN
    return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)


def _json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return dict(value)


async def get_pool() -> asyncpg.Pool:
    """
    Return a connection pool bound to the *currently running* event loop.

    Celery (via core.async_utils.run_async) creates a fresh event loop per
    task. asyncpg pools and connections are bound to the loop they were
    created on and become unusable once that loop closes. Rather than rely
    solely on cleanup happening after every task (cleanup can be skipped by
    a crash, an unexpected exception, or simply by code that doesn't call
    it), this checks loop identity on every acquisition and transparently
    discards/recreates a stale pool. This makes pool reuse safe even if a
    caller forgets to close it.
    """
    global _pool, _pool_loop
    current_loop = asyncio.get_running_loop()

    if _pool is not None and _pool_loop is not current_loop:
        stale_pool = _pool
        _pool = None
        _pool_loop = None
        try:
            await stale_pool.close()
        except Exception as exc:
            logger.debug(f"Discarding stale Postgres pool (close failed, ignoring): {exc}")

    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=_asyncpg_dsn(),
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
        _pool_loop = current_loop
        await ensure_ingestion_state_schema()

    return _pool


async def close_pool() -> None:
    global _pool, _pool_loop
    pool, _pool = _pool, None
    _pool_loop = None
    if pool is not None:
        await pool.close()


@dataclass(frozen=True)
class IngestionState:
    source: str
    cursor: str | None
    last_sync_timestamp: datetime | None
    checkpoint: dict[str, Any]
    papers_ingested: int


async def ensure_ingestion_state_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    pool = _pool
    if pool is None:
        return

    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_sources (
                    id TEXT PRIMARY KEY,
                    last_checkpoint JSONB DEFAULT '{}',
                    papers_ingested BIGINT DEFAULT 0,
                    last_run_at TIMESTAMPTZ,
                    status TEXT DEFAULT 'active',
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            await conn.execute(
                """
                ALTER TABLE ingestion_sources
                ADD COLUMN IF NOT EXISTS cursor TEXT
                """
            )
            await conn.execute(
                """
                ALTER TABLE ingestion_sources
                ADD COLUMN IF NOT EXISTS last_sync_timestamp TIMESTAMPTZ
                """
            )
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingestion_sources_sync
                ON ingestion_sources (id, last_sync_timestamp DESC)
                """
            )
    except (
        asyncpg.exceptions.DuplicateTableError,
        asyncpg.exceptions.UniqueViolationError,
        asyncpg.exceptions.DuplicateObjectError,
    ):
        # Another worker process won the race and created the same
        # table/column/index concurrently on cold start. The DDL above is
        # otherwise idempotent, so this is safe to ignore.
        logger.debug("Ingestion schema already created by a concurrent worker; continuing")

    _schema_ready = True


async def get_ingestion_state(source: str) -> IngestionState:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO ingestion_sources (id)
            VALUES ($1)
            ON CONFLICT (id) DO UPDATE SET id = EXCLUDED.id
            RETURNING id, cursor, last_sync_timestamp, last_checkpoint, papers_ingested
            """,
            source,
        )

    return IngestionState(
        source=row["id"],
        cursor=row["cursor"],
        last_sync_timestamp=row["last_sync_timestamp"],
        checkpoint=_json_object(row["last_checkpoint"]),
        papers_ingested=int(row["papers_ingested"] or 0),
    )


async def update_ingestion_state(
    source: str,
    *,
    cursor: str | None = None,
    last_sync_timestamp: datetime | None = None,
    checkpoint: dict[str, Any] | None = None,
    papers_ingested_delta: int = 0,
) -> None:
    pool = await get_pool()
    sync_timestamp = last_sync_timestamp or datetime.now(timezone.utc)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO ingestion_sources (
                id, cursor, last_sync_timestamp, last_checkpoint,
                papers_ingested, last_run_at
            )
            VALUES ($1, $2, $3, COALESCE($4::jsonb, '{}'::jsonb), $5, NOW())
            ON CONFLICT (id) DO UPDATE SET
                cursor = COALESCE(EXCLUDED.cursor, ingestion_sources.cursor),
                last_sync_timestamp = COALESCE(
                    EXCLUDED.last_sync_timestamp,
                    ingestion_sources.last_sync_timestamp
                ),
                last_checkpoint = ingestion_sources.last_checkpoint || COALESCE(
                    EXCLUDED.last_checkpoint,
                    '{}'::jsonb
                ),
                papers_ingested = ingestion_sources.papers_ingested + EXCLUDED.papers_ingested,
                last_run_at = NOW()
            """,
            source,
            cursor,
            sync_timestamp,
            json.dumps(checkpoint or {}),
            papers_ingested_delta,
        )
    logger.debug(f"Updated ingestion state for {source}: cursor={cursor}")