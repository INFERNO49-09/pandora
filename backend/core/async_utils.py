"""
Async helpers for sync worker contexts.
"""
import asyncio
from collections.abc import Coroutine
from typing import Any

from loguru import logger


async def _close_loop_bound_clients() -> None:
    """Close cached async clients before their event loop is closed."""
    try:
        from knowledge_graph.client import close_driver

        await close_driver()
    except Exception as exc:
        logger.warning(f"Failed to close Neo4j driver: {exc}")

    try:
        from core.nim_client import close_nim_client

        await close_nim_client()
    except Exception as exc:
        logger.warning(f"Failed to close LLM client: {exc}")

    try:
        from vector_store.client import close_qdrant

        await close_qdrant()
    except Exception as exc:
        logger.warning(f"Failed to close Qdrant client: {exc}")

    try:
        from ingestion.state import close_pool

        await close_pool()
    except Exception as exc:
        logger.warning(f"Failed to close Postgres pool: {exc}")


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """
    Run an async coroutine from a synchronous Celery task.

    Celery workers create temporary event loops for these tasks. Async clients
    such as Neo4j's driver keep loop-bound connection state, so they must be
    closed before the loop itself is closed.
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        try:
            loop.run_until_complete(_close_loop_bound_clients())
        finally:
            asyncio.set_event_loop(None)
            loop.close()