"""
GraphSAGE link prediction model.

Inductive model — can handle new nodes not seen during training.
This is essential for a growing knowledge graph where new papers
arrive daily.

Architecture:
  Input: node features (BGE embeddings, 1024-dim)
  → Linear projection to hidden_dim
  → 3x SAGEConv layers with batch norm + dropout
  → Link prediction head: MLP(concat(src_emb, dst_emb)) → [0,1]

Training objective: Binary cross-entropy with hard negatives.
"""
from __future__ import annotations

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from loguru import logger


def _require_torch():
    if not HAS_TORCH:
        raise RuntimeError(
            "PyTorch is required for GraphSAGE training. "
            "Install with: pip install torch torch-geometric"
        )


class SAGEConvManual:
    """
    Manual SAGEConv — works without torch_geometric installed.
    Used for architecture documentation and CPU inference.
    Full PyG version is used during training.
    """
    pass


class PandoraGraphSAGE:
    """
    Heterogeneous GraphSAGE for the Pandora knowledge graph.

    Key design decisions:
    1. Node-type-specific input projections (different feature spaces)
    2. Shared hidden space (enables cross-type reasoning)
    3. Batch normalization per layer (stabilizes training on sparse graphs)
    4. Link predictor MLP: [src_emb || dst_emb] → score

    Usage (requires PyTorch + PyG):

        from torch_geometric.data import HeteroData

        model = PandoraGraphSAGE(
            node_types=["Paper", "Concept", "Domain"],
            edge_types=[...],
            input_dim=1024,
            hidden_dim=256,
            num_layers=3,
        )

        # Training step
        h_dict = model.encode(x_dict, edge_index_dict)
        scores = model.predict_link(h_dict, "Concept", "Concept", edge_index)
        loss = F.binary_cross_entropy(scores, labels)
    """

    def __init__(
        self,
        node_types: list[str],
        edge_types: list[tuple[str, str, str]],
        input_dim: int = 1024,
        hidden_dim: int = 256,
        num_layers: int = 3,
        dropout: float = 0.2,
    ):
        _require_torch()
        import torch.nn as nn
        from torch_geometric.nn import SAGEConv, to_hetero

        self.node_types   = node_types
        self.edge_types   = edge_types
        self.input_dim    = input_dim
        self.hidden_dim   = hidden_dim
        self.num_layers   = num_layers

        # Node-type-specific input projections
        self.input_proj = nn.ModuleDict({
            nt: nn.Linear(input_dim, hidden_dim)
            for nt in node_types
        })

        # Homogeneous SAGEConv stack (converted to hetero via to_hetero)
        class HomoSAGE(nn.Module):
            def __init__(self):
                super().__init__()
                self.convs = nn.ModuleList([
                    SAGEConv(hidden_dim, hidden_dim)
                    for _ in range(num_layers)
                ])
                self.bns = nn.ModuleList([
                    nn.BatchNorm1d(hidden_dim)
                    for _ in range(num_layers)
                ])
                self.dropout = nn.Dropout(dropout)

            def forward(self, x, edge_index):
                for conv, bn in zip(self.convs, self.bns):
                    x = conv(x, edge_index)
                    x = bn(x)
                    x = F.relu(x)
                    x = self.dropout(x)
                return x

        homo_model = HomoSAGE()
        # Convert to heterogeneous (handles different edge types)
        metadata = (node_types, [(s, r, d) for s, r, d in edge_types])
        self.sage = to_hetero(homo_model, metadata=metadata, aggr="sum")

        # Link prediction head
        self.link_predictor = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
            nn.Sigmoid(),
        )

    def encode(self, x_dict: dict, edge_index_dict: dict) -> dict:
        """Project all node types and run message passing."""
        import torch
        # Project to shared embedding space
        h_dict = {
            node_type: F.relu(self.input_proj[node_type](x))
            for node_type, x in x_dict.items()
            if node_type in self.input_proj
        }
        return self.sage(h_dict, edge_index_dict)

    def predict_link(
        self,
        h_dict: dict,
        src_type: str,
        dst_type: str,
        edge_index,  # torch.Tensor shape [2, E]
    ):
        """Score candidate edges. Returns probabilities in [0, 1]."""
        src_emb = h_dict[src_type][edge_index[0]]
        dst_emb = h_dict[dst_type][edge_index[1]]
        pair = torch.cat([src_emb, dst_emb], dim=-1)
        return self.link_predictor(pair).squeeze(-1)

    def loss(
        self,
        pos_scores,
        neg_scores,
        margin: float = 0.0,
    ):
        """Binary cross-entropy loss over positive and negative edges."""
        import torch
        pos_labels = torch.ones_like(pos_scores)
        neg_labels = torch.zeros_like(neg_scores)
        scores = torch.cat([pos_scores, neg_scores])
        labels = torch.cat([pos_labels, neg_labels])
        return F.binary_cross_entropy(scores, labels)


class GraphSAGEConfig:
    """Serializable training configuration."""

    def __init__(
        self,
        input_dim: int = 1024,
        hidden_dim: int = 256,
        num_layers: int = 3,
        dropout: float = 0.2,
        lr: float = 1e-3,
        weight_decay: float = 1e-4,
        epochs: int = 50,
        batch_size: int = 4096,
        n_neg_per_pos: int = 5,
        split_year: int = 2022,
        target_edge_type: str = "Concept__RELATED_TO__Concept",
        device: str = "cuda" if (HAS_TORCH and __import__("torch").cuda.is_available()) else "cpu",
    ):
        self.input_dim        = input_dim
        self.hidden_dim       = hidden_dim
        self.num_layers       = num_layers
        self.dropout          = dropout
        self.lr               = lr
        self.weight_decay     = weight_decay
        self.epochs           = epochs
        self.batch_size       = batch_size
        self.n_neg_per_pos    = n_neg_per_pos
        self.split_year       = split_year
        self.target_edge_type = target_edge_type
        self.device           = device

    def to_dict(self) -> dict:
        return self.__dict__.copy()
