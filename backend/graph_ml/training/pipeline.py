"""
Graph ML training pipeline.

Orchestrates:
1. Load graph data from Neo4j → GraphData
2. Temporal train/val/test split
3. Hard negative sampling
4. Train GraphSAGE or TransE
5. Evaluate with MRR + Hits@K (filtered)
6. Save model + register in PostgreSQL model registry
7. Export embeddings to Qdrant for inference

Run via: python -m graph_ml.training.pipeline --model graphsage --edge-type Concept__RELATED_TO__Concept
Or trigger via Celery task: graph_ml.tasks.train_model
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger

from graph_ml.data_loader import GraphMLDataLoader, GraphData, NODE_TYPES, EDGE_TYPES
from graph_ml.models.graphsage import GraphSAGEConfig
from graph_ml.models.transe import TransEConfig


@dataclass
class EvalMetrics:
    mrr: float
    hits_at_1: float
    hits_at_10: float
    hits_at_100: float
    num_test_triples: int

    def __str__(self) -> str:
        return (
            f"MRR={self.mrr:.4f} "
            f"H@1={self.hits_at_1:.4f} "
            f"H@10={self.hits_at_10:.4f} "
            f"H@100={self.hits_at_100:.4f} "
            f"(n={self.num_test_triples})"
        )

    def to_dict(self) -> dict:
        return self.__dataclass_fields__ and {
            "mrr": self.mrr,
            "hits_at_1": self.hits_at_1,
            "hits_at_10": self.hits_at_10,
            "hits_at_100": self.hits_at_100,
            "num_test_triples": self.num_test_triples,
        }


def evaluate_link_prediction(
    model,
    test_src: "torch.Tensor",
    test_dst: "torch.Tensor",
    all_embeddings: "torch.Tensor",
    known_positive_set: set[tuple[int, int]],
    k_values: list[int] = [1, 10, 100],
) -> EvalMetrics:
    """
    Filtered MRR + Hits@K evaluation.

    FILTERED = when ranking candidates for (h, r, ?), we mask out
    other known true tails. This prevents penalizing correct predictions
    that happen to not be the test triple.

    Args:
        model: scoring model with .score() method
        test_src/dst: test edge indices
        all_embeddings: [N, D] tensor of all entity embeddings
        known_positive_set: set of (src, dst) known true edges (for filtering)
        k_values: which Hits@K to compute
    """
    try:
        import torch
    except ImportError:
        raise RuntimeError("PyTorch required for evaluation")

    ranks = []
    n_entities = all_embeddings.shape[0]

    with torch.no_grad():
        for src_idx, true_dst in zip(test_src.tolist(), test_dst.tolist()):
            # Score all entities as candidate tails
            src_emb = all_embeddings[src_idx].unsqueeze(0).expand(n_entities, -1)
            dst_embs = all_embeddings

            # Simple dot-product scoring (works for normalized embeddings)
            scores = (src_emb * dst_embs).sum(dim=-1)

            # Filtered: mask known positives (except the test triple itself)
            for known_dst in range(n_entities):
                if (src_idx, known_dst) in known_positive_set and known_dst != true_dst:
                    scores[known_dst] = float("-inf")

            # Rank of the true tail (1-indexed)
            rank = (scores > scores[true_dst]).sum().item() + 1
            ranks.append(rank)

    ranks_t = torch.tensor(ranks, dtype=torch.float)
    mrr = (1.0 / ranks_t).mean().item()
    hits = {k: (ranks_t <= k).float().mean().item() for k in k_values}

    return EvalMetrics(
        mrr=mrr,
        hits_at_1=hits.get(1, 0.0),
        hits_at_10=hits.get(10, 0.0),
        hits_at_100=hits.get(100, 0.0),
        num_test_triples=len(ranks),
    )


async def train_graphsage(config: GraphSAGEConfig) -> dict:
    """
    Full GraphSAGE training pipeline.

    Returns metrics dict for model registry.
    """
    try:
        import torch
        from torch_geometric.data import HeteroData
    except ImportError:
        logger.error("torch and torch_geometric required. Install in container with GPU.")
        return {"error": "torch not installed"}

    logger.info(f"Training GraphSAGE on edge type: {config.target_edge_type}")

    # Load data
    loader = GraphMLDataLoader()
    data = await loader.load(node_limit=100_000)

    if config.target_edge_type not in data.edges:
        logger.error(f"Edge type {config.target_edge_type} not found in graph")
        return {"error": f"edge type not found"}

    # Build PyG HeteroData
    pyg_data = HeteroData()
    for node_type in NODE_TYPES:
        if node_type in data.features:
            pyg_data[node_type].x = torch.tensor(
                data.features[node_type], dtype=torch.float32
            )

    for edge_key, (src, dst) in data.edges.items():
        parts = edge_key.split("__")
        if len(parts) == 3:
            s_type, rel, d_type = parts
            edge_index = torch.stack([
                torch.tensor(src, dtype=torch.long),
                torch.tensor(dst, dtype=torch.long),
            ])
            pyg_data[s_type, rel, d_type].edge_index = edge_index

    # Temporal split on target edge type
    train_mask, val_mask, test_mask = loader.temporal_split(
        data, config.target_edge_type, config.split_year
    )

    src_arr, dst_arr = data.edges[config.target_edge_type]
    train_src = torch.tensor(src_arr[train_mask], dtype=torch.long)
    train_dst = torch.tensor(dst_arr[train_mask], dtype=torch.long)
    val_src   = torch.tensor(src_arr[val_mask], dtype=torch.long)
    val_dst   = torch.tensor(dst_arr[val_mask], dtype=torch.long)
    test_src  = torch.tensor(src_arr[test_mask], dtype=torch.long)
    test_dst  = torch.tensor(dst_arr[test_mask], dtype=torch.long)

    # Import model
    from graph_ml.models.graphsage import PandoraGraphSAGE
    model = PandoraGraphSAGE(
        node_types=NODE_TYPES,
        edge_types=EDGE_TYPES,
        input_dim=config.input_dim,
        hidden_dim=config.hidden_dim,
        num_layers=config.num_layers,
        dropout=config.dropout,
    )

    device = torch.device(config.device)
    optimizer = torch.optim.Adam(
        model.sage.parameters(),
        lr=config.lr,
        weight_decay=config.weight_decay,
    )

    best_val_mrr = 0.0
    best_state = None

    src_type, rel_type, dst_type = config.target_edge_type.split("__")

    for epoch in range(config.epochs):
        model.sage.train()
        optimizer.zero_grad()

        # Encode all nodes
        x_dict = {nt: pyg_data[nt].x for nt in NODE_TYPES if hasattr(pyg_data[nt], 'x')}
        edge_index_dict = {}
        for s, r, d in EDGE_TYPES:
            key = (s, r, d)
            if hasattr(pyg_data[s, r, d], 'edge_index'):
                edge_index_dict[key] = pyg_data[s, r, d].edge_index

        h_dict = model.encode(x_dict, edge_index_dict)

        # Hard negative sampling
        neg_src_np, neg_dst_np = loader.hard_negative_sample(
            data, config.target_edge_type, train_mask, config.n_neg_per_pos
        )
        neg_src = torch.tensor(neg_src_np, dtype=torch.long)
        neg_dst = torch.tensor(neg_dst_np, dtype=torch.long)

        # Score positives and negatives
        pos_edge_index = torch.stack([train_src, train_dst])
        neg_edge_index = torch.stack([neg_src, neg_dst])

        pos_scores = model.predict_link(h_dict, src_type, dst_type, pos_edge_index)
        neg_scores = model.predict_link(h_dict, src_type, dst_type, neg_edge_index)

        loss = model.loss(pos_scores, neg_scores)
        loss.backward()
        optimizer.step()

        if epoch % 10 == 0:
            logger.info(f"Epoch {epoch}/{config.epochs} — Loss: {loss.item():.4f}")

    # Final test evaluation
    model.sage.eval()
    with torch.no_grad():
        h_dict = model.encode(x_dict, edge_index_dict)
        embeddings = h_dict[src_type].cpu()

    known_pos = set(zip(src_arr.tolist(), dst_arr.tolist()))
    test_metrics = evaluate_link_prediction(
        model, test_src, test_dst, embeddings, known_pos
    )
    logger.info(f"Test metrics: {test_metrics}")

    # Save model
    save_path = Path(f"/tmp/pandora_graphsage_{config.target_edge_type}.pt")
    torch.save({
        "model_state": model.sage.state_dict(),
        "config": config.to_dict(),
        "test_metrics": test_metrics.to_dict(),
    }, save_path)

    return {
        "model_path": str(save_path),
        "test_mrr": test_metrics.mrr,
        "hits_at_1": test_metrics.hits_at_1,
        "hits_at_10": test_metrics.hits_at_10,
        "edge_type": config.target_edge_type,
    }


async def train_transe(config: TransEConfig, edge_key: str) -> dict:
    """
    TransE training pipeline for a single relationship type.
    """
    try:
        import torch
    except ImportError:
        return {"error": "torch not installed"}

    logger.info(f"Training TransE on: {edge_key}")

    loader = GraphMLDataLoader()
    data = await loader.load(node_limit=100_000)

    if edge_key not in data.edges:
        return {"error": f"edge type {edge_key} not found"}

    src_arr, dst_arr = data.edges[edge_key]
    train_mask, val_mask, test_mask = loader.temporal_split(data, edge_key, config.split_year)

    from graph_ml.models.transe import PandoraTransE
    model = PandoraTransE(config)

    optimizer = torch.optim.Adam(model.parameters(), lr=config.lr, weight_decay=config.weight_decay)

    relation_id = torch.zeros(len(src_arr[train_mask]), dtype=torch.long)  # single relation type

    for epoch in range(config.epochs):
        optimizer.zero_grad()

        pos_src = torch.tensor(src_arr[train_mask], dtype=torch.long)
        pos_dst = torch.tensor(dst_arr[train_mask], dtype=torch.long)

        # Corrupt tails for negatives
        neg_dst = torch.randint(0, config.num_entities, (len(pos_src) * config.n_neg_per_pos,))
        neg_src = pos_src.repeat(config.n_neg_per_pos)
        neg_rel = relation_id.repeat(config.n_neg_per_pos)

        pos_scores = model.score(pos_src, relation_id, pos_dst)
        neg_scores = model.score(neg_src, neg_rel, neg_dst).view(-1, config.n_neg_per_pos)

        loss = model.margin_loss(pos_scores, neg_scores)
        loss.backward()

        # Re-normalize entity embeddings after update (TransE constraint)
        with torch.no_grad():
            import torch.nn.functional as F
            model.entity_emb.weight.data = F.normalize(model.entity_emb.weight.data, p=2, dim=1)

        optimizer.step()

        if epoch % 20 == 0:
            logger.info(f"Epoch {epoch}/{config.epochs} — Loss: {loss.item():.4f}")

    # Save
    save_path = Path(f"/tmp/pandora_transe_{edge_key}.pt")
    torch.save({
        "entity_emb": model.entity_emb.weight.detach(),
        "relation_emb": model.relation_emb.weight.detach(),
        "config": config.to_dict(),
    }, save_path)

    return {"model_path": str(save_path), "edge_type": edge_key}
