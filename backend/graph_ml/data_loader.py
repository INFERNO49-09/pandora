"""
Graph ML Data Loader.

Exports the Neo4j knowledge graph into PyTorch Geometric HeteroData
format for training GraphSAGE and TransE models.

Design:
- Node features: BGE embeddings fetched from Qdrant (768-dim)
- Edge index: built from Neo4j adjacency
- Temporal split: edges are split by year to prevent data leakage
- Negative sampling: community-aware hard negatives
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from knowledge_graph.client import run_query
from vector_store.client import get_qdrant
from loguru import logger


# Node types we model
NODE_TYPES = ["Paper", "Concept", "Domain", "Method", "Author"]

# Edge types we model (src_type, rel_type, dst_type)
EDGE_TYPES = [
    ("Paper",   "CITES",        "Paper"),
    ("Paper",   "IN_DOMAIN",    "Domain"),
    ("Paper",   "USES",         "Concept"),
    ("Paper",   "USES",         "Method"),
    ("Concept", "RELATED_TO",   "Concept"),
    ("Method",  "VARIANT_OF",   "Method"),
    ("Domain",  "SUBDOMAIN_OF", "Domain"),
]

EMBED_DIM = 1024   # NIM nv-embedqa-e5-v5 dimension


@dataclass
class GraphData:
    """
    Container for graph data. Intentionally NOT a PyG object
    so it can be serialized and inspected without PyG installed.
    Convert to HeteroData in training script.
    """
    # node_id_map[node_type][neo4j_id] = integer index
    node_id_map: dict[str, dict[str, int]] = field(default_factory=dict)
    # features[node_type] = np.array(N, EMBED_DIM)
    features: dict[str, np.ndarray] = field(default_factory=dict)
    # edges[edge_type_str] = (src_indices, dst_indices) both np.int64
    edges: dict[str, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict)
    # edge metadata (year for temporal split)
    edge_years: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def num_nodes(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.node_id_map.items()}

    @property
    def num_edges(self) -> dict[str, int]:
        return {k: len(v[0]) for k, v in self.edges.items()}


class GraphMLDataLoader:

    async def load(
        self,
        node_limit: int = 50_000,
        embed_batch_size: int = 96,
    ) -> GraphData:
        """
        Full graph export pipeline:
        1. Load node IDs from Neo4j
        2. Fetch embeddings from Qdrant
        3. Load edges from Neo4j
        4. Build integer index maps
        """
        logger.info("Starting graph ML data export...")
        data = GraphData()

        # Step 1: Load nodes
        await self._load_nodes(data, node_limit)
        logger.info(f"Loaded nodes: {data.num_nodes}")

        # Step 2: Fetch embeddings
        await self._load_embeddings(data, embed_batch_size)
        logger.info("Embeddings loaded")

        # Step 3: Load edges
        await self._load_edges(data)
        logger.info(f"Loaded edges: {data.num_edges}")

        return data

    async def _load_nodes(self, data: GraphData, limit: int):
        """Load node IDs for each type. Assign integer indices."""
        for node_type in NODE_TYPES:
            results = await run_query(
                f"""
                MATCH (n:{node_type})
                RETURN n.id AS id
                LIMIT $limit
                """,
                params={"limit": limit},
            )
            id_map = {r["id"]: i for i, r in enumerate(results) if r["id"]}
            data.node_id_map[node_type] = id_map
            # Initialize zero embeddings (filled in next step)
            data.features[node_type] = np.zeros(
                (len(id_map), EMBED_DIM), dtype=np.float32
            )

    async def _load_embeddings(self, data: GraphData, batch_size: int):
        """
        Fetch embeddings from Qdrant and fill feature matrices.
        Qdrant payload stores node_id → we look up the integer index.
        """
        client = get_qdrant()
        collection_map = {
            "Concept": "concepts",
            "Domain":  "domains",
            "Paper":   "papers",
            "Method":  "concepts",   # methods share concepts collection
            "Author":  "concepts",
        }

        for node_type, collection in collection_map.items():
            if node_type not in data.node_id_map:
                continue

            id_map = data.node_id_map[node_type]
            feature_matrix = data.features[node_type]
            filled = 0

            try:
                # Scroll through Qdrant collection
                offset = None
                while True:
                    scroll_result = await client.scroll(
                        collection_name=collection,
                        limit=batch_size,
                        offset=offset,
                        with_vectors=True,
                        with_payload=True,
                    )
                    points, next_offset = scroll_result

                    for point in points:
                        node_id = point.payload.get("node_id")
                        if node_id and node_id in id_map:
                            idx = id_map[node_id]
                            vec = point.vector
                            if vec and len(vec) == EMBED_DIM:
                                feature_matrix[idx] = np.array(vec, dtype=np.float32)
                                filled += 1

                    if next_offset is None:
                        break
                    offset = next_offset

            except Exception as e:
                logger.warning(f"Embedding load failed for {node_type}/{collection}: {e}")

            logger.debug(f"{node_type}: filled {filled}/{len(id_map)} embeddings")

    async def _load_edges(self, data: GraphData):
        """Load edges for each edge type and build sparse index arrays."""
        for src_type, rel_type, dst_type in EDGE_TYPES:
            src_map = data.node_id_map.get(src_type, {})
            dst_map = data.node_id_map.get(dst_type, {})
            if not src_map or not dst_map:
                continue

            edge_key = f"{src_type}__{rel_type}__{dst_type}"

            # Fetch edges with optional year
            results = await run_query(
                f"""
                MATCH (src:{src_type})-[r:{rel_type}]->(dst:{dst_type})
                WHERE src.id IS NOT NULL AND dst.id IS NOT NULL
                RETURN src.id AS src_id, dst.id AS dst_id,
                       coalesce(r.year, src.year, 0) AS year
                LIMIT 500000
                """,
            )

            src_indices, dst_indices, years = [], [], []
            for row in results:
                s = src_map.get(row["src_id"])
                d = dst_map.get(row["dst_id"])
                if s is not None and d is not None:
                    src_indices.append(s)
                    dst_indices.append(d)
                    years.append(int(row["year"] or 0))

            if src_indices:
                data.edges[edge_key] = (
                    np.array(src_indices, dtype=np.int64),
                    np.array(dst_indices, dtype=np.int64),
                )
                data.edge_years[edge_key] = np.array(years, dtype=np.int32)

    def temporal_split(
        self,
        data: GraphData,
        edge_key: str,
        split_year: int = 2022,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Split edges into train/val/test by year.
        CRITICAL: test set must only contain edges from AFTER split_year.
        Training on future edges and predicting past = data leakage.

        Returns: (train_mask, val_mask, test_mask) boolean arrays.
        """
        years = data.edge_years.get(edge_key)
        if years is None:
            raise ValueError(f"No year data for edge key: {edge_key}")

        train_mask = years < split_year - 1
        val_mask   = years == split_year - 1
        test_mask  = years >= split_year

        logger.info(
            f"{edge_key} split: "
            f"train={train_mask.sum()}, val={val_mask.sum()}, test={test_mask.sum()}"
        )
        return train_mask, val_mask, test_mask

    def hard_negative_sample(
        self,
        data: GraphData,
        edge_key: str,
        mask: np.ndarray,
        n_per_positive: int = 5,
        seed: int = 42,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Community-aware hard negative sampling.

        For each positive edge (u, v), sample negatives from nodes
        in the same domain community as v — these are plausible but wrong.
        This forces the model to learn fine-grained structure.

        Simple implementation: corrupt the tail node from within
        the same node type, excluding known positive edges.
        """
        rng = random.Random(seed)
        src_arr, dst_arr = data.edges[edge_key]

        pos_src = src_arr[mask]
        pos_dst = dst_arr[mask]

        # Build positive edge set for fast lookup
        pos_set = set(zip(pos_src.tolist(), pos_dst.tolist()))

        dst_type = edge_key.split("__")[2]
        n_dst = len(data.node_id_map.get(dst_type, {}))

        neg_src, neg_dst = [], []
        for s, d in zip(pos_src.tolist(), pos_dst.tolist()):
            sampled = 0
            attempts = 0
            while sampled < n_per_positive and attempts < n_per_positive * 10:
                # Sample from a small window around d (locality = hard negatives)
                offset = rng.randint(-50, 50)
                candidate = max(0, min(n_dst - 1, d + offset))
                if (s, candidate) not in pos_set and candidate != d:
                    neg_src.append(s)
                    neg_dst.append(candidate)
                    sampled += 1
                attempts += 1

        return (
            np.array(neg_src, dtype=np.int64),
            np.array(neg_dst, dtype=np.int64),
        )
