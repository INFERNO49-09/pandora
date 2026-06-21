from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any
from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession
from loguru import logger
from core.config import get_settings

settings = get_settings()

_driver: AsyncDriver | None = None


async def get_driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            max_connection_pool_size=50,
        )
    return _driver


async def close_driver():
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    driver = await get_driver()
    async with driver.session(database="neo4j") as session:
        yield session


async def run_query(
    cypher: str,
    params: dict | None = None,
    write: bool = False
) -> list[dict[str, Any]]:
    """
    Execute a Cypher query and return results as list of dicts.
    Always use parameterized queries — never string interpolation.
    """
    async with get_session() as session:
        if write:
            result = await session.run(cypher, parameters=params or {})
        else:
            result = await session.run(cypher, parameters=params or {})
        records = await result.data()
        return records


async def setup_schema():
    """
    Idempotent schema setup — safe to call on every startup.
    Creates constraints and indexes if they don't exist.
    """
    logger.info("Setting up Neo4j schema...")

    schema_queries = [
        # ── CONSTRAINTS (enforce uniqueness) ──────────────────────────────
        "CREATE CONSTRAINT paper_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.id IS UNIQUE",
        "CREATE CONSTRAINT paper_source_id IF NOT EXISTS FOR (p:Paper) REQUIRE p.source_id IS UNIQUE",
        "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT author_id IF NOT EXISTS FOR (a:Author) REQUIRE a.id IS UNIQUE",
        "CREATE CONSTRAINT institution_id IF NOT EXISTS FOR (i:Institution) REQUIRE i.id IS UNIQUE",
        "CREATE CONSTRAINT method_id IF NOT EXISTS FOR (m:Method) REQUIRE m.id IS UNIQUE",
        "CREATE CONSTRAINT dataset_id IF NOT EXISTS FOR (d:Dataset) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT domain_id IF NOT EXISTS FOR (d:Domain) REQUIRE d.id IS UNIQUE",
        "CREATE CONSTRAINT metric_id IF NOT EXISTS FOR (m:Metric) REQUIRE m.id IS UNIQUE",
        "CREATE CONSTRAINT opportunity_id IF NOT EXISTS FOR (o:ResearchOpportunity) REQUIRE o.id IS UNIQUE",
        "CREATE CONSTRAINT problem_id IF NOT EXISTS FOR (p:ResearchProblem) REQUIRE p.id IS UNIQUE",

        # ── RANGE INDEXES ─────────────────────────────────────────────────
        "CREATE INDEX paper_year IF NOT EXISTS FOR (p:Paper) ON (p.year)",
        "CREATE INDEX paper_citations IF NOT EXISTS FOR (p:Paper) ON (p.citation_count)",
        "CREATE INDEX concept_growth IF NOT EXISTS FOR (c:Concept) ON (c.growth_rate)",
        "CREATE INDEX domain_paper_count IF NOT EXISTS FOR (d:Domain) ON (d.paper_count)",
        "CREATE INDEX opportunity_score IF NOT EXISTS FOR (o:ResearchOpportunity) ON (o.opportunity_score)",

        # ── FULL-TEXT INDEXES ──────────────────────────────────────────────
        """CREATE FULLTEXT INDEX paper_fulltext IF NOT EXISTS
           FOR (p:Paper) ON EACH [p.title, p.abstract]""",
        """CREATE FULLTEXT INDEX concept_fulltext IF NOT EXISTS
           FOR (c:Concept) ON EACH [c.canonical_name]""",
        """CREATE FULLTEXT INDEX domain_fulltext IF NOT EXISTS
           FOR (d:Domain) ON EACH [d.name]""",
    ]

    async with get_session() as session:
        for query in schema_queries:
            try:
                await session.run(query)
            except Exception as e:
                # Constraint/index already exists — safe to ignore
                if "already exists" not in str(e).lower():
                    logger.warning(f"Schema query warning: {e}")

    logger.info("Neo4j schema setup complete")
