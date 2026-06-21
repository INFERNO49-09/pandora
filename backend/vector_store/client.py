from functools import lru_cache
import inspect
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
    SearchRequest,
)
from loguru import logger
from core.config import get_settings

settings = get_settings()

COLLECTIONS = {
    "concepts": {
        "size": settings.active_embed_dim,
        "distance": Distance.COSINE,
    },
    "papers": {
        "size": settings.active_embed_dim,
        "distance": Distance.COSINE,
    },
    "domains": {
        "size": settings.active_embed_dim,
        "distance": Distance.COSINE,
    },
}


@lru_cache
def get_qdrant() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        host=settings.QDRANT_HOST,
        port=settings.QDRANT_PORT,
        timeout=30,
    )


async def close_qdrant() -> None:
    """Close the cached async Qdrant client, if one exists."""
    if get_qdrant.cache_info().currsize == 0:
        return

    client = get_qdrant()
    result = client.close()
    if inspect.isawaitable(result):
        await result
    get_qdrant.cache_clear()


async def setup_collections():
    """
    Create Qdrant collections if they don't exist. Idempotent.

    Also detects the case where a collection already exists but was created
    with a different vector size than the currently active embedding model
    (e.g. after switching LLM_PROVIDER between NIM and a local model with a
    different embedding dimension). In that case the collection is dropped
    and recreated at the new size — any previously indexed vectors are lost
    and need to be re-ingested, but this avoids every subsequent upsert
    failing silently with a dimension-mismatch error forever.
    """
    client = get_qdrant()
    existing = {c.name for c in (await client.get_collections()).collections}

    for name, params in COLLECTIONS.items():
        if name not in existing:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=params["size"],
                    distance=params["distance"],
                ),
            )
            logger.info(f"Created Qdrant collection: {name}")
            continue

        info = await client.get_collection(name)
        current_size = info.config.params.vectors.size
        if current_size != params["size"]:
            logger.warning(
                f"Qdrant collection '{name}' has vector size {current_size}, "
                f"but the active embedding model produces {params['size']}-dim "
                f"vectors. Recreating the collection at the new size; "
                f"previously indexed vectors will need to be re-ingested."
            )
            await client.delete_collection(name)
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=params["size"],
                    distance=params["distance"],
                ),
            )
            logger.info(f"Recreated Qdrant collection: {name} (size={params['size']})")
        else:
            logger.debug(f"Qdrant collection exists: {name}")


async def upsert_vectors(
    collection: str,
    points: list[dict],  # {"id": str, "vector": list[float], "payload": dict}
):
    """
    Upsert embedding vectors with metadata payload.
    """
    client = get_qdrant()
    qdrant_points = [
        PointStruct(
            id=p["id"],
            vector=p["vector"],
            payload=p["payload"],
        )
        for p in points
    ]
    await client.upsert(collection_name=collection, points=qdrant_points)


async def search_similar(
    collection: str,
    query_vector: list[float],
    top_k: int = 10,
    score_threshold: float = 0.5,
    filter_payload: dict | None = None,
) -> list[dict]:
    """
    Semantic similarity search. Returns list of {id, score, payload}.
    """
    client = get_qdrant()

    query_filter = None
    if filter_payload:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filter_payload.items()
        ]
        query_filter = Filter(must=conditions)

    results = await client.search(
        collection_name=collection,
        query_vector=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=query_filter,
        with_payload=True,
    )

    return [
        {"id": r.id, "score": r.score, "payload": r.payload}
        for r in results
    ]