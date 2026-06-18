"""
Graph writer.
Writes extracted knowledge into Neo4j using MERGE strategy.
MERGE = upsert: create if not exists, update if exists.
This means the pipeline is fully idempotent — safe to re-run.
"""
import hashlib
from loguru import logger
from knowledge_graph.client import run_query
from models.types import RawPaper, ExtractionResult


def _concept_id(name: str) -> str:
    """Stable concept ID from canonical name."""
    normalized = name.lower().strip()
    return f"concept:{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"


def _domain_id(name: str) -> str:
    normalized = name.lower().strip()
    return f"domain:{hashlib.sha256(normalized.encode()).hexdigest()[:12]}"


def _method_id(name: str) -> str:
    normalized = name.lower().strip()
    return f"method:{hashlib.sha256(normalized.encode()).hexdigest()[:16]}"


def _author_id(name: str) -> str:
    normalized = name.lower().strip()
    return f"author:{hashlib.sha256(normalized.encode()).hexdigest()[:12]}"


class GraphWriter:
    async def write_paper_with_extraction(
        self,
        paper: RawPaper,
        extraction: ExtractionResult,
    ) -> str:
        """
        Full graph write for a single paper + its extracted knowledge.
        Returns the paper node ID.
        """
        paper_id = extraction.paper_id

        # 1. Write paper node
        await self._write_paper(paper, paper_id)

        # 2. Write domains + link to paper
        for domain_name in extraction.domains:
            if domain_name:
                await self._write_domain(domain_name, paper_id)

        # 3. Write concepts + link to paper
        for concept in extraction.concepts:
            if concept.name:
                await self._write_concept(concept.name, concept.domain, paper_id)

        # 4. Write methods + link to paper
        for method in extraction.methods:
            if method.name:
                await self._write_method(method.name, method.category, paper_id)

        # 5. Write relations between entities
        for rel in extraction.relations:
            if rel.head and rel.tail:
                await self._write_relation(rel, paper_id)

        # 6. Write citation edges (paper → paper)
        for ref_id in (paper.references or [])[:50]:
            await self._write_citation(paper_id, ref_id)

        # 7. Write authors
        for author_name in paper.authors[:10]:
            if author_name:
                await self._write_author(author_name, paper_id)

        logger.debug(f"Graph write complete for paper: {paper_id}")
        return paper_id

    async def _write_paper(self, paper: RawPaper, paper_id: str):
        await run_query(
            """
            MERGE (p:Paper {id: $id})
            SET p.title = $title,
                p.abstract = $abstract,
                p.year = $year,
                p.doi = $doi,
                p.arxiv_id = $arxiv_id,
                p.venue = $venue,
                p.citation_count = $citation_count,
                p.source = $source,
                p.updated_at = datetime()
            """,
            params={
                "id": paper_id,
                "title": paper.title,
                "abstract": paper.abstract[:2000] if paper.abstract else "",
                "year": paper.year,
                "doi": paper.doi,
                "arxiv_id": paper.arxiv_id,
                "venue": paper.venue,
                "citation_count": paper.citation_count,
                "source": paper.source,
            },
            write=True,
        )

    async def _write_domain(self, domain_name: str, paper_id: str):
        domain_id = _domain_id(domain_name)
        await run_query(
            """
            MERGE (d:Domain {id: $domain_id})
            ON CREATE SET d.name = $name, d.paper_count = 0
            SET d.paper_count = d.paper_count + 1

            WITH d
            MATCH (p:Paper {id: $paper_id})
            MERGE (p)-[:IN_DOMAIN]->(d)
            """,
            params={
                "domain_id": domain_id,
                "name": domain_name,
                "paper_id": paper_id,
            },
            write=True,
        )

    async def _write_concept(
        self, 
        concept_name: str, 
        domain: str | None,
        paper_id: str
    ):
        concept_id = _concept_id(concept_name)
        await run_query(
            """
            MERGE (c:Concept {id: $concept_id})
            ON CREATE SET c.canonical_name = $name,
                          c.paper_count = 0,
                          c.domain = $domain
            SET c.paper_count = c.paper_count + 1

            WITH c
            MATCH (p:Paper {id: $paper_id})
            MERGE (p)-[:USES]->(c)
            """,
            params={
                "concept_id": concept_id,
                "name": concept_name,
                "domain": domain,
                "paper_id": paper_id,
            },
            write=True,
        )

    async def _write_method(
        self,
        method_name: str,
        category: str | None,
        paper_id: str,
    ):
        method_id = _method_id(method_name)
        await run_query(
            """
            MERGE (m:Method {id: $method_id})
            ON CREATE SET m.name = $name,
                          m.category = $category,
                          m.paper_count = 0
            SET m.paper_count = m.paper_count + 1

            WITH m
            MATCH (p:Paper {id: $paper_id})
            MERGE (p)-[:USES]->(m)
            """,
            params={
                "method_id": method_id,
                "name": method_name,
                "category": category,
                "paper_id": paper_id,
            },
            write=True,
        )

    async def _write_relation(self, rel, paper_id: str):
        """Write a typed relation between two entities."""
        head_id = (
            _concept_id(rel.head) if rel.head_type == "concept"
            else _method_id(rel.head)
        )
        tail_id = (
            _concept_id(rel.tail) if rel.tail_type == "concept"
            else _method_id(rel.tail)
        )

        # Validate relationship type
        allowed_rels = {
            "USES", "IMPROVES", "EXTENDS", "INTRODUCES",
            "EVALUATED_ON", "RELATED_TO", "CONTRADICTS"
        }
        rel_type = rel.relation if rel.relation in allowed_rels else "RELATED_TO"

        await run_query(
            f"""
            MATCH (h {{id: $head_id}})
            MATCH (t {{id: $tail_id}})
            MERGE (h)-[r:{rel_type} {{source_paper: $paper_id}}]->(t)
            SET r.confidence = $confidence
            """,
            params={
                "head_id": head_id,
                "tail_id": tail_id,
                "paper_id": paper_id,
                "confidence": rel.confidence,
            },
            write=True,
        )

    async def _write_citation(self, citing_paper_id: str, cited_ref: str):
        """Write CITES relationship between papers."""
        # Attempt to find the cited paper by DOI or arXiv ID
        await run_query(
            """
            MATCH (citing:Paper {id: $citing_id})
            OPTIONAL MATCH (cited:Paper)
            WHERE cited.doi = $ref OR cited.arxiv_id = $ref OR cited.id = $ref
            WITH citing, cited
            WHERE cited IS NOT NULL
            MERGE (citing)-[:CITES]->(cited)
            """,
            params={"citing_id": citing_paper_id, "ref": cited_ref},
            write=True,
        )

    async def _write_author(self, author_name: str, paper_id: str):
        author_id = _author_id(author_name)
        await run_query(
            """
            MERGE (a:Author {id: $author_id})
            ON CREATE SET a.full_name = $name, a.paper_count = 0
            SET a.paper_count = a.paper_count + 1

            WITH a
            MATCH (p:Paper {id: $paper_id})
            MERGE (p)-[:AUTHORED_BY]->(a)
            """,
            params={
                "author_id": author_id,
                "name": author_name,
                "paper_id": paper_id,
            },
            write=True,
        )
