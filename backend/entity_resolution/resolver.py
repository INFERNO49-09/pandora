"""
Deterministic entity resolution for extracted scientific entities.

This is intentionally conservative: it canonicalizes exact and near-exact
aliases before graph write without collapsing unrelated scientific terms.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from loguru import logger

from models.types import ExtractedConcept, ExtractedMethod, ExtractedRelation, ExtractionResult


_STOPWORDS = {
    "a",
    "an",
    "and",
    "based",
    "for",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
}

_ALIASES = {
    "ai": "Artificial Intelligence",
    "artificial intelligence": "Artificial Intelligence",
    "cnn": "Convolutional Neural Networks",
    "convolutional neural network": "Convolutional Neural Networks",
    "convolutional neural networks": "Convolutional Neural Networks",
    "gcn": "Graph Convolutional Networks",
    "gnn": "Graph Neural Networks",
    "graph neural network": "Graph Neural Networks",
    "graph neural networks": "Graph Neural Networks",
    "llm": "Large Language Models",
    "large language model": "Large Language Models",
    "large language models": "Large Language Models",
    "ml": "Machine Learning",
    "machine learning": "Machine Learning",
    "nlp": "Natural Language Processing",
    "natural language processing": "Natural Language Processing",
    "rnn": "Recurrent Neural Networks",
    "transformer": "Transformers",
    "transformers": "Transformers",
}


@dataclass(frozen=True)
class ResolutionStats:
    concepts_seen: int = 0
    methods_seen: int = 0
    concepts_merged: int = 0
    methods_merged: int = 0


def normalize_entity_name(name: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", " ", name or "").strip().lower()
    terms = [part for part in text.split() if part not in _STOPWORDS]
    return " ".join(terms)


def canonicalize_name(name: str) -> str:
    normalized = normalize_entity_name(name)
    if not normalized:
        return name.strip()
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    return " ".join(part.upper() if part in {"ai", "ml", "nlp"} else part.capitalize() for part in normalized.split())


def _similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.92


def _canonical_lookup(names: Iterable[str]) -> dict[str, str]:
    canonical_by_norm: dict[str, str] = {}
    lookup: dict[str, str] = {}

    for name in names:
        normalized = normalize_entity_name(name)
        if not normalized:
            continue
        canonical = canonicalize_name(name)
        matched_key = next((key for key in canonical_by_norm if _similar(normalized, key)), None)
        if matched_key:
            lookup[name] = canonical_by_norm[matched_key]
        else:
            canonical_by_norm[normalized] = canonical
            lookup[name] = canonical
    return lookup


class EntityResolver:
    """
    Resolve extracted concepts and methods to canonical names.
    """

    def resolve_extraction(self, extraction: ExtractionResult) -> tuple[ExtractionResult, ResolutionStats]:
        concept_lookup = _canonical_lookup(c.name for c in extraction.concepts if c.name)
        method_lookup = _canonical_lookup(m.name for m in extraction.methods if m.name)

        concepts = [
            concept.model_copy(update={"canonical_name": concept_lookup.get(concept.name, concept.canonical_name)})
            for concept in extraction.concepts
        ]
        methods = [
            method.model_copy(update={"canonical_name": method_lookup.get(method.name, method.canonical_name)})
            for method in extraction.methods
        ]

        relations = [
            self._resolve_relation(relation, concept_lookup, method_lookup)
            for relation in extraction.relations
        ]
        resolved = extraction.model_copy(
            update={
                "concepts": self._dedupe_concepts(concepts),
                "methods": self._dedupe_methods(methods),
                "relations": relations,
                "domains": sorted({canonicalize_name(domain) for domain in extraction.domains if domain}),
            }
        )
        stats = ResolutionStats(
            concepts_seen=len(extraction.concepts),
            methods_seen=len(extraction.methods),
            concepts_merged=max(0, len(extraction.concepts) - len(resolved.concepts)),
            methods_merged=max(0, len(extraction.methods) - len(resolved.methods)),
        )
        if stats.concepts_merged or stats.methods_merged:
            logger.debug(f"Entity resolution merged entities for {extraction.paper_id}: {stats}")
        return resolved, stats

    def resolve_batch(self, extractions: list[ExtractionResult]) -> tuple[list[ExtractionResult], ResolutionStats]:
        resolved: list[ExtractionResult] = []
        total = ResolutionStats()
        for extraction in extractions:
            item, stats = self.resolve_extraction(extraction)
            resolved.append(item)
            total = ResolutionStats(
                concepts_seen=total.concepts_seen + stats.concepts_seen,
                methods_seen=total.methods_seen + stats.methods_seen,
                concepts_merged=total.concepts_merged + stats.concepts_merged,
                methods_merged=total.methods_merged + stats.methods_merged,
            )
        return resolved, total

    def _resolve_relation(
        self,
        relation: ExtractedRelation,
        concept_lookup: dict[str, str],
        method_lookup: dict[str, str],
    ) -> ExtractedRelation:
        head_lookup = method_lookup if relation.head_type == "method" else concept_lookup
        tail_lookup = method_lookup if relation.tail_type == "method" else concept_lookup
        return relation.model_copy(
            update={
                "head": head_lookup.get(relation.head, canonicalize_name(relation.head)),
                "tail": tail_lookup.get(relation.tail, canonicalize_name(relation.tail)),
            }
        )

    def _dedupe_concepts(self, concepts: list[ExtractedConcept]) -> list[ExtractedConcept]:
        by_name: dict[str, ExtractedConcept] = {}
        for concept in concepts:
            key = normalize_entity_name(concept.canonical_name or concept.name)
            existing = by_name.get(key)
            if existing is None or concept.confidence > existing.confidence:
                by_name[key] = concept
        return list(by_name.values())

    def _dedupe_methods(self, methods: list[ExtractedMethod]) -> list[ExtractedMethod]:
        by_name: dict[str, ExtractedMethod] = {}
        for method in methods:
            key = normalize_entity_name(method.canonical_name or method.name)
            existing = by_name.get(key)
            if existing is None or method.confidence > existing.confidence:
                by_name[key] = method
        return list(by_name.values())
