"""
TransE knowledge graph embedding model.

TransE models: h + r ≈ t
Score: -||h + r - t||_p  (higher = more plausible)

Best suited for Pandora relationships that are:
- Hierarchical: SUBDOMAIN_OF, VARIANT_OF
- Functional: SOLVES, APPLIED_IN
- Transitive: if A IMPROVES B and B IMPROVES C → A likely related to C

NOT suitable for symmetric or one-to-many relationships
(use RotatE for those — included as an extension).

We train one TransE model per major relationship type.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from loguru import logger


@dataclass
class TransEConfig:
    num_entities: int
    num_relations: int
    embedding_dim: int = 200
    margin: float = 1.0
    norm: int = 2                  # L1 or L2 norm
    lr: float = 1e-3
    weight_decay: float = 1e-5
    epochs: int = 100
    batch_size: int = 2048
    n_neg_per_pos: int = 5
    split_year: int = 2022
    device: str = "cpu"

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class PandoraTransE:
    """
    TransE for predicting typed relationships in the Pandora KG.

    Key implementation details:
    1. Entity embeddings L2-normalized (TransE requirement)
    2. Relation embeddings NOT normalized (allows asymmetry)
    3. Self-adversarial negative sampling (ROTATE paper technique):
       weight negatives by softmax(scores) to focus on hard cases
    4. Filtered evaluation: exclude known true triples when ranking

    The model is trained separately per relation type.
    At inference, we load the appropriate model for the query.
    """

    def __init__(self, config: TransEConfig):
        if not HAS_TORCH:
            raise RuntimeError("PyTorch required. pip install torch")

        self.config = config
        self.entity_emb = nn.Embedding(
            config.num_entities, config.embedding_dim
        )
        self.relation_emb = nn.Embedding(
            config.num_relations, config.embedding_dim
        )
        self._init_embeddings()

    def _init_embeddings(self):
        """Xavier init + L2 normalize entity embeddings."""
        nn.init.xavier_uniform_(self.entity_emb.weight)
        nn.init.xavier_uniform_(self.relation_emb.weight)
        with torch.no_grad():
            self.entity_emb.weight.data = F.normalize(
                self.entity_emb.weight.data, p=2, dim=1
            )

    def score(
        self,
        heads: "torch.Tensor",
        relations: "torch.Tensor",
        tails: "torch.Tensor",
    ) -> "torch.Tensor":
        """
        Score function: -||h + r - t||_L2
        Lower score = more plausible triple.
        Negated so higher = better (consistent with other models).
        """
        h = self.entity_emb(heads)
        r = self.relation_emb(relations)
        t = self.entity_emb(tails)
        return -torch.norm(h + r - t, p=self.config.norm, dim=-1)

    def margin_loss(
        self,
        pos_scores: "torch.Tensor",
        neg_scores: "torch.Tensor",
    ) -> "torch.Tensor":
        """Max-margin (hinge) ranking loss with self-adversarial weighting."""
        # Self-adversarial weights: focus training on hard negatives
        weights = F.softmax(neg_scores.detach() * 0.5, dim=-1)
        loss = (weights * torch.relu(
            self.config.margin - pos_scores.unsqueeze(1) + neg_scores
        )).sum(dim=-1).mean()
        return loss

    def parameters(self):
        return list(self.entity_emb.parameters()) + list(self.relation_emb.parameters())

    def get_entity_embeddings(self) -> "torch.Tensor":
        """Return all entity embeddings as tensor for export to Qdrant."""
        return self.entity_emb.weight.detach().cpu()

    def predict_tail(
        self,
        head_id: int,
        relation_id: int,
        top_k: int = 10,
        exclude_ids: list[int] | None = None,
    ) -> list[tuple[int, float]]:
        """
        Given (head, relation), predict the most likely tail entities.
        Returns [(entity_id, score)] sorted descending.
        """
        with torch.no_grad():
            h = self.entity_emb.weight[head_id]
            r = self.relation_emb.weight[relation_id]
            query = h + r

            # Score all entities as potential tails
            all_tails = self.entity_emb.weight
            scores = -torch.norm(query.unsqueeze(0) - all_tails, p=self.config.norm, dim=1)

            if exclude_ids:
                scores[exclude_ids] = float("-inf")

            top_scores, top_indices = torch.topk(scores, top_k)
            return list(zip(top_indices.tolist(), top_scores.tolist()))


class RotatE(PandoraTransE):
    """
    RotatE extension: models relations as rotations in complex space.
    Better than TransE for:
    - Symmetric relations (RELATED_TO: if A~B then B~A)
    - Antisymmetric (IMPROVES: if A→B, not B→A necessarily)
    - Composition (A EXTENDS B, B EXTENDS C → A related to C)

    Uses complex embeddings: entity dim = embedding_dim // 2 complex numbers.
    """

    def __init__(self, config: TransEConfig):
        # RotatE needs even embedding_dim for real/imag split
        assert config.embedding_dim % 2 == 0, "embedding_dim must be even for RotatE"
        super().__init__(config)
        # Override: entity embeddings are complex (re, im pairs)
        # Relation embeddings are phase angles only (no magnitude)
        self.relation_emb = nn.Embedding(
            config.num_relations, config.embedding_dim // 2
        )

    def score(self, heads, relations, tails):
        """RotatE score: ||h ∘ r - t|| in complex space."""
        emb_dim = self.config.embedding_dim // 2

        h = self.entity_emb(heads)
        t = self.entity_emb(tails)
        phase_r = self.relation_emb(relations)

        # Split real and imaginary
        h_re, h_im = h[:, :emb_dim], h[:, emb_dim:]
        t_re, t_im = t[:, :emb_dim], t[:, emb_dim:]

        # Rotation: multiply by e^(i*phase)
        r_re = torch.cos(phase_r)
        r_im = torch.sin(phase_r)

        # Complex multiplication: (h_re + i*h_im) * (r_re + i*r_im)
        rot_re = h_re * r_re - h_im * r_im
        rot_im = h_re * r_im + h_im * r_re

        # Distance to tail
        diff_re = rot_re - t_re
        diff_im = rot_im - t_im
        dist = torch.norm(torch.stack([diff_re, diff_im], dim=-1), dim=-1)
        return -dist.sum(dim=-1)
