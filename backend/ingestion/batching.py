"""
Batching utilities for ingestion tasks.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from itertools import islice
from typing import TypeVar

from loguru import logger

from core.config import get_settings


T = TypeVar("T")
DEFAULT_BATCH_SIZE = 100


def configured_batch_size(batch_size: int | None = None) -> int:
    size = batch_size or get_settings().INGESTION_BATCH_SIZE or DEFAULT_BATCH_SIZE
    return max(1, int(size))


def chunked(iterable: Iterable[T], size: int | None = None) -> Iterator[list[T]]:
    batch_size = configured_batch_size(size)
    iterator = iter(iterable)

    while True:
        batch = list(islice(iterator, batch_size))
        if not batch:
            break
        yield batch


def queue_paper_batches(
    papers: Sequence[dict],
    ingest_batch_task,
    *,
    queue: str = "ingestion",
    batch_size: int | None = None,
) -> list[str]:
    task_ids: list[str] = []
    for batch in chunked(papers, batch_size):
        task = ingest_batch_task.apply_async(args=[batch], queue=queue)
        task_ids.append(task.id)

    logger.info(
        f"Queued {len(papers)} papers as {len(task_ids)} ingestion batches "
        f"(batch_size={configured_batch_size(batch_size)})"
    )
    return task_ids
