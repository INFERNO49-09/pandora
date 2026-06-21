"""
Batch-oriented Neo4j graph writer.
"""
from __future__ import annotations

import hashlib
from typing import Any

from loguru import logger

from knowledge_graph.client import run_query
from models.types import ExtractionResult, RawPaper


def _stable_id(prefix: str, value: str) -> str:
    normalized = (value or "").lower().strip()
    return f"{prefix}:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:16]}"


def _concept_id(name: str) -> str:
    return _stable_id("concept", name)


def _domain_id(name: str) -> str:
    return _stable_id("domain", name)


def _method_id(name: str) -> str:
    return _stable_id("method", name)


def _author_id(name: str, openalex_id: str | None = None) -> str:
    return f"openalex:{openalex_id}" if openalex_id else _stable_id("author", name)


def _institution_id(name: str, openalex_id: str | None = None) -> str:
    return f"openalex:{openalex_id}" if openalex_id else _stable_id("institution", name)


def _paper_id(paper: RawPaper, extraction: ExtractionResult | None = None) -> str:
    if extraction:
        return extraction.paper_id
    if paper.openalex_id:
        return f"openalex:{paper.openalex_id}"
    if paper.source == "openalex" and paper.source_id:
        return f"openalex:{paper.source_id}"
    if paper.doi:
        return f"doi:{paper.doi.lower()}"
    if paper.arxiv_id:
        return f"arxiv:{paper.arxiv_id}"
    if paper.openalex_id:
        return f"openalex:{paper.openalex_id}"
    return f"{paper.source}:{paper.source_id}"


class GraphWriter:
    async def write_paper_with_extraction(
        self,
        paper: RawPaper,
        extraction: ExtractionResult,
    ) -> str:
        await self.write_batch([(paper, extraction)])
        return extraction.paper_id

    async def write_batch(
        self,
        items: list[tuple[RawPaper, ExtractionResult]],
    ) -> list[str]:
        if not items:
            return []

        paper_rows = [self._paper_row(paper, extraction) for paper, extraction in items]
        author_rows = self._author_rows(items)
        institution_rows = self._institution_rows(items)
        affiliation_rows = self._affiliation_rows(items)
        authorship_rows = self._authorship_rows(items)
        citation_rows = self._citation_rows(items)
        concept_rows = self._concept_rows(items)
        domain_rows = self._domain_rows(items)
        method_rows = self._method_rows(items)
        relation_rows = self._relation_rows(items)

        await self._write_papers(paper_rows)
        await self._write_authors(author_rows)
        await self._write_institutions(institution_rows)
        await self._write_affiliations(affiliation_rows)
        await self._write_authorships(authorship_rows)
        await self._write_citations(citation_rows)
        await self._write_concepts(concept_rows)
        await self._write_domains(domain_rows)
        await self._write_methods(method_rows)
        await self._write_entity_relations(relation_rows)

        paper_ids = [row["id"] for row in paper_rows]
        logger.debug(f"Batch graph write complete for {len(paper_ids)} papers")
        return paper_ids

    def _paper_row(self, paper: RawPaper, extraction: ExtractionResult) -> dict[str, Any]:
        return {
            "id": extraction.paper_id,
            "source_id": paper.source_id,
            "openalex_id": paper.openalex_id,
            "doi": paper.doi,
            "arxiv_id": paper.arxiv_id,
            "title": paper.title,
            "abstract": (paper.abstract or "")[:5000],
            "year": paper.year,
            "venue": paper.venue,
            "citation_count": paper.citation_count or 0,
            "source": paper.source,
            "keywords": paper.keywords,
            "primary_topic": (paper.primary_topic or {}).get("name") if paper.primary_topic else None,
            "content_hash": paper.content_hash,
        }

    def _author_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        authors: dict[str, dict[str, Any]] = {}
        for paper, _ in items:
            if paper.authorships:
                for authorship in paper.authorships:
                    name = authorship.get("name")
                    if not name:
                        continue
                    author_id = _author_id(name, authorship.get("openalex_id"))
                    authors[author_id] = {
                        "id": author_id,
                        "name": name,
                        "openalex_id": authorship.get("openalex_id"),
                    }
            else:
                for name in paper.authors[:50]:
                    if name:
                        author_id = _author_id(name)
                        authors[author_id] = {"id": author_id, "name": name, "openalex_id": None}
        return list(authors.values())

    def _institution_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        institutions: dict[str, dict[str, Any]] = {}
        for paper, _ in items:
            for institution in paper.institutions:
                name = institution.get("name")
                if not name:
                    continue
                institution_id = _institution_id(name, institution.get("openalex_id"))
                institutions[institution_id] = {
                    "id": institution_id,
                    "name": name,
                    "country": institution.get("country"),
                    "openalex_id": institution.get("openalex_id"),
                    "ror": institution.get("ror"),
                }
        return list(institutions.values())

    def _affiliation_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        rows: set[tuple[str, str]] = set()
        institution_names: dict[str, str] = {}
        for paper, _ in items:
            for institution in paper.institutions:
                if institution.get("openalex_id"):
                    institution_names[institution["openalex_id"]] = institution.get("name") or ""
            for authorship in paper.authorships:
                name = authorship.get("name")
                if not name:
                    continue
                author_id = _author_id(name, authorship.get("openalex_id"))
                for institution_id in authorship.get("institutions") or []:
                    rows.add((author_id, _institution_id(institution_names.get(institution_id, institution_id), institution_id)))
        return [{"author_id": author_id, "institution_id": institution_id} for author_id, institution_id in rows]

    def _authorship_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        rows: set[tuple[str, str]] = set()
        for paper, extraction in items:
            paper_id = _paper_id(paper, extraction)
            if paper.authorships:
                for authorship in paper.authorships:
                    name = authorship.get("name")
                    if name:
                        rows.add((_author_id(name, authorship.get("openalex_id")), paper_id))
            else:
                for name in paper.authors[:50]:
                    if name:
                        rows.add((_author_id(name), paper_id))
        return [{"author_id": author_id, "paper_id": paper_id} for author_id, paper_id in rows]

    def _citation_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        rows: set[tuple[str, str, str]] = set()
        for paper, extraction in items:
            citing_id = _paper_id(paper, extraction)
            for ref in (paper.references or [])[:200]:
                if not ref:
                    continue
                ref = ref.strip()
                cited_id = ref if ":" in ref else f"openalex:{ref}"
                rows.add((citing_id, cited_id, ref))
        return [{"citing_id": citing_id, "cited_id": cited_id, "source_id": source_id} for citing_id, cited_id, source_id in rows]

    def _concept_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for paper, extraction in items:
            paper_id = _paper_id(paper, extraction)
            for concept in extraction.concepts:
                name = concept.canonical_name or concept.name
                if name:
                    rows[(paper_id, _concept_id(name))] = {
                        "paper_id": paper_id,
                        "concept_id": _concept_id(name),
                        "name": name,
                        "domain": concept.domain,
                        "score": concept.confidence,
                    }
            for concept in paper.concepts:
                name = concept.get("name")
                if name:
                    rows[(paper_id, concept.get("id") or _concept_id(name))] = {
                        "paper_id": paper_id,
                        "concept_id": concept.get("id") or _concept_id(name),
                        "name": name,
                        "domain": None,
                        "score": concept.get("score"),
                    }
            if paper.primary_topic and paper.primary_topic.get("name"):
                name = paper.primary_topic["name"]
                rows[(paper_id, paper.primary_topic.get("id") or _concept_id(name))] = {
                    "paper_id": paper_id,
                    "concept_id": paper.primary_topic.get("id") or _concept_id(name),
                    "name": name,
                    "domain": str(paper.primary_topic.get("domain") or ""),
                    "score": paper.primary_topic.get("score"),
                }
        return list(rows.values())

    def _domain_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for paper, extraction in items:
            paper_id = _paper_id(paper, extraction)
            for domain in extraction.domains:
                if domain:
                    rows[(paper_id, _domain_id(domain))] = {
                        "paper_id": paper_id,
                        "domain_id": _domain_id(domain),
                        "name": domain,
                    }
            if paper.primary_topic:
                for part in ("domain", "field", "subfield"):
                    value = paper.primary_topic.get(part)
                    if isinstance(value, dict):
                        value = value.get("display_name")
                    if value:
                        rows[(paper_id, _domain_id(str(value)))] = {
                            "paper_id": paper_id,
                            "domain_id": _domain_id(str(value)),
                            "name": str(value),
                        }
        return list(rows.values())

    def _method_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        rows: dict[tuple[str, str], dict[str, Any]] = {}
        for paper, extraction in items:
            paper_id = _paper_id(paper, extraction)
            for method in extraction.methods:
                name = method.canonical_name or method.name
                if name:
                    rows[(paper_id, _method_id(name))] = {
                        "paper_id": paper_id,
                        "method_id": _method_id(name),
                        "name": name,
                        "category": method.category,
                        "score": method.confidence,
                    }
        return list(rows.values())

    def _relation_rows(self, items: list[tuple[RawPaper, ExtractionResult]]) -> list[dict[str, Any]]:
        allowed = {"USES", "IMPROVES", "EXTENDS", "INTRODUCES", "EVALUATED_ON", "RELATED_TO", "CONTRADICTS"}
        rows = []
        for paper, extraction in items:
            paper_id = _paper_id(paper, extraction)
            for rel in extraction.relations:
                if not rel.head or not rel.tail:
                    continue
                rows.append(
                    {
                        "head_id": _method_id(rel.head) if rel.head_type == "method" else _concept_id(rel.head),
                        "tail_id": _method_id(rel.tail) if rel.tail_type == "method" else _concept_id(rel.tail),
                        "relation": rel.relation if rel.relation in allowed else "RELATED_TO",
                        "paper_id": paper_id,
                        "confidence": rel.confidence,
                    }
                )
        return rows

    async def _write_papers(self, rows: list[dict[str, Any]]) -> None:
        await run_query(
            """
            UNWIND $rows AS row
            MERGE (p:Paper {id: row.id})
            SET p.source_id = row.source_id,
                p.openalex_id = row.openalex_id,
                p.doi = row.doi,
                p.arxiv_id = row.arxiv_id,
                p.title = row.title,
                p.abstract = row.abstract,
                p.year = row.year,
                p.venue = row.venue,
                p.citation_count = row.citation_count,
                p.source = row.source,
                p.keywords = row.keywords,
                p.primary_topic = row.primary_topic,
                p.content_hash = row.content_hash,
                p.updated_at = datetime()
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_authors(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MERGE (a:Author {id: row.id})
            SET a.name = row.name,
                a.full_name = row.name,
                a.openalex_id = row.openalex_id,
                a.updated_at = datetime()
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_institutions(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MERGE (i:Institution {id: row.id})
            SET i.name = row.name,
                i.country = row.country,
                i.openalex_id = row.openalex_id,
                i.ror = row.ror,
                i.updated_at = datetime()
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_affiliations(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MATCH (a:Author {id: row.author_id})
            MATCH (i:Institution {id: row.institution_id})
            MERGE (a)-[:AFFILIATED_WITH]->(i)
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_authorships(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MATCH (a:Author {id: row.author_id})
            MATCH (p:Paper {id: row.paper_id})
            MERGE (a)-[:AUTHORED]->(p)
            MERGE (p)-[:AUTHORED_BY]->(a)
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_citations(self, rows: list[dict[str, str]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MATCH (citing:Paper {id: row.citing_id})
            MERGE (cited:Paper {id: row.cited_id})
            ON CREATE SET cited.source_id = row.source_id, cited.source = 'openalex_stub'
            MERGE (citing)-[:CITES]->(cited)
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_concepts(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MERGE (c:Concept {id: row.concept_id})
            SET c.canonical_name = row.name,
                c.name = row.name,
                c.domain = coalesce(row.domain, c.domain),
                c.updated_at = datetime()
            WITH row, c
            MATCH (p:Paper {id: row.paper_id})
            MERGE (p)-[r:USES]->(c)
            SET r.score = row.score
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_domains(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MERGE (d:Domain {id: row.domain_id})
            SET d.name = row.name,
                d.updated_at = datetime()
            WITH row, d
            MATCH (p:Paper {id: row.paper_id})
            MERGE (p)-[:IN_DOMAIN]->(d)
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_methods(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        await run_query(
            """
            UNWIND $rows AS row
            MERGE (m:Method {id: row.method_id})
            SET m.name = row.name,
                m.category = row.category,
                m.updated_at = datetime()
            WITH row, m
            MATCH (p:Paper {id: row.paper_id})
            MERGE (p)-[r:USES]->(m)
            SET r.score = row.score
            """,
            params={"rows": rows},
            write=True,
        )

    async def _write_entity_relations(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(row["relation"], []).append(row)

        for relation, relation_rows in grouped.items():
            await run_query(
                f"""
                UNWIND $rows AS row
                MATCH (h {{id: row.head_id}})
                MATCH (t {{id: row.tail_id}})
                MERGE (h)-[r:{relation} {{source_paper: row.paper_id}}]->(t)
                SET r.confidence = row.confidence
                """,
                params={"rows": relation_rows},
                write=True,
            )
