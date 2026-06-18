"""
LangGraph Multi-Agent Discovery System.

Agents collaborate to answer complex research discovery queries.
Each agent is a node in a LangGraph StateGraph.

Agent roster:
  router          — classifies query intent and plans agent path
  literature      — finds relevant papers via graph + vector search
  opportunity     — surfaces research gaps using CARGS
  hypothesis      — generates scientific hypotheses for gaps
  trend           — analyses research velocity and trajectories
  synthesizer     — assembles final response with citations

Flow:
  User query
    → router (classifies intent)
    → [literature, opportunity, trend] in parallel (based on intent)
    → hypothesis (if opportunities found)
    → synthesizer
    → streamed response

Dependencies: langgraph, openai (for NIM via OpenAI-compatible API)
"""
from __future__ import annotations

import asyncio
import json
from typing import Annotated, TypedDict, Literal
import operator

from loguru import logger

try:
    from langgraph.graph import StateGraph, END, START
    from langgraph.checkpoint.memory import MemorySaver
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    logger.warning("langgraph not installed — agent features disabled")

from core.nim_client import nim_chat
from knowledge_graph.client import run_query
from discovery.cargs import CARGSScorer


# ── AGENT STATE ────────────────────────────────────────────────────────────────

class AgentState(TypedDict):
    # Input
    query: str
    intent: str                                     # discovery|trend|hypothesis|literature|general

    # Accumulated outputs (operator.add = append-only lists)
    papers_found:        Annotated[list[dict], operator.add]
    opportunities_found: Annotated[list[dict], operator.add]
    trends_found:        Annotated[list[dict], operator.add]
    hypotheses:          Annotated[list[str],  operator.add]
    agent_trace:         Annotated[list[str],  operator.add]

    # Final output
    response: str
    citations: list[dict]
    done: bool


# ── AGENT IMPLEMENTATIONS ──────────────────────────────────────────────────────

async def router_agent(state: AgentState) -> dict:
    """
    Classify the query intent to route to the right agents.
    Fast: single LLM call with a small model.
    """
    raw = await nim_chat(
        messages=[{
            "role": "user",
            "content": f"""Classify this scientific research query into one of these intents:
- discovery: finding unknown/unexplored research opportunities or gaps
- trend: understanding what's growing fast or emerging in a field  
- hypothesis: generating a testable hypothesis about a specific topic
- literature: finding papers, authors, or existing work on a topic
- general: anything else

Query: {state["query"]}

Reply with only the intent word, nothing else.""",
        }],
        temperature=0.0,
        max_tokens=10,
    )
    intent = raw.strip().lower()
    if intent not in ("discovery", "trend", "hypothesis", "literature", "general"):
        intent = "general"

    return {
        "intent": intent,
        "agent_trace": [f"router → intent={intent}"],
    }


async def literature_agent(state: AgentState) -> dict:
    """
    Finds relevant papers via full-text + semantic search.
    Runs Neo4j full-text search + Qdrant similarity.
    """
    query = state["query"]

    # Graph search: full-text on title + abstract
    papers = await run_query(
        """
        CALL db.index.fulltext.queryNodes('paper_fulltext', $query)
        YIELD node AS p, score
        RETURN p.id AS id, p.title AS title, p.year AS year,
               p.abstract AS abstract, p.citation_count AS citations,
               score
        ORDER BY score DESC
        LIMIT 10
        """,
        params={"query": query},
    )

    # Semantic search via Qdrant
    from vector_store.client import search_similar
    from core.nim_client import nim_embed_single
    try:
        vec = await nim_embed_single(query)
        semantic_hits = await search_similar("papers", vec, top_k=5, score_threshold=0.6)
        for h in semantic_hits:
            payload = h["payload"]
            if not any(p["id"] == payload.get("node_id") for p in papers):
                papers.append({
                    "id": payload.get("node_id", ""),
                    "title": payload.get("title", ""),
                    "year": payload.get("year"),
                    "abstract": "",
                    "citations": 0,
                    "score": h["score"],
                })
    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")

    return {
        "papers_found": papers[:10],
        "agent_trace": [f"literature → found {len(papers)} papers"],
    }


async def opportunity_agent(state: AgentState) -> dict:
    """
    Surfaces research gaps relevant to the query.
    Extracts domain mentions from query, then runs CARGS.
    """
    query = state["query"]

    # Extract domain mentions from query via NIM
    raw = await nim_chat(
        messages=[{
            "role": "user",
            "content": f"""Extract research domain names from this query.
Query: {query}
Return a JSON array of domain names (2-5 words each), e.g. ["Machine Learning", "Drug Discovery"]
Return only the JSON array, nothing else.""",
        }],
        temperature=0.0,
        max_tokens=100,
    )
    try:
        import re
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        domains = json.loads(m.group()) if m else []
    except Exception:
        domains = []

    if not domains:
        return {
            "opportunities_found": [],
            "agent_trace": ["opportunity → no domains extracted"],
        }

    # Fetch top opportunities for those domains
    domain_filter = " OR ".join(
        f"(toLower(o.domain_a) CONTAINS toLower('{d}') OR toLower(o.domain_b) CONTAINS toLower('{d}'))"
        for d in domains[:3]
    )
    opps = await run_query(
        f"""
        MATCH (o:ResearchOpportunity)
        WHERE {domain_filter}
          AND o.opportunity_score >= 0.50
        RETURN o.id AS id, o.title AS title,
               o.domain_a AS domain_a, o.domain_b AS domain_b,
               o.opportunity_score AS score,
               o.hypothesis AS hypothesis
        ORDER BY o.opportunity_score DESC
        LIMIT 5
        """,
    )

    return {
        "opportunities_found": opps,
        "agent_trace": [f"opportunity → found {len(opps)} opportunities for domains {domains}"],
    }


async def trend_agent(state: AgentState) -> dict:
    """Identifies fast-growing research areas related to the query."""
    query = state["query"]

    # Extract key concept from query
    concept_raw = await nim_chat(
        messages=[{
            "role": "user",
            "content": f"Extract the main research topic (2-4 words) from: '{query}'. Reply with only the topic.",
        }],
        temperature=0.0,
        max_tokens=20,
    )
    topic = concept_raw.strip().strip('"')

    trending = await run_query(
        """
        MATCH (d:Domain)
        WHERE toLower(d.name) CONTAINS toLower($topic)
        MATCH (p:Paper)-[:IN_DOMAIN]->(d)
        WITH d, count(CASE WHEN p.year >= date().year - 2 THEN 1 END) AS recent,
             count(p) AS total
        WHERE total > 5
        RETURN d.name AS domain, recent AS recent_papers, total AS total_papers,
               toFloat(recent) / total AS growth_ratio
        ORDER BY growth_ratio DESC
        LIMIT 5
        """,
        params={"topic": topic},
    )

    trending_concepts = await run_query(
        """
        MATCH (c:Concept)<-[:USES]-(p:Paper)
        WHERE toLower(c.canonical_name) CONTAINS toLower($topic)
          AND p.year >= date().year - 3
        RETURN c.canonical_name AS concept, count(p) AS recent_papers
        ORDER BY recent_papers DESC
        LIMIT 5
        """,
        params={"topic": topic},
    )

    return {
        "trends_found": trending + trending_concepts,
        "agent_trace": [f"trend → found {len(trending)} domain trends, {len(trending_concepts)} concept trends"],
    }


async def hypothesis_agent(state: AgentState) -> dict:
    """
    Generates a testable hypothesis based on discovered opportunities.
    Only runs if opportunity_agent found something.
    """
    if not state.get("opportunities_found"):
        return {
            "hypotheses": [],
            "agent_trace": ["hypothesis → skipped (no opportunities)"],
        }

    top_opp = state["opportunities_found"][0]
    query   = state["query"]

    raw = await nim_chat(
        messages=[{
            "role": "user",
            "content": f"""Based on this research opportunity, generate a specific testable hypothesis.

User question: {query}

Research opportunity:
- Domain A: {top_opp.get('domain_a', 'Unknown')}
- Domain B: {top_opp.get('domain_b', 'Unknown')}
- Existing hypothesis: {top_opp.get('hypothesis', 'None')}
- Opportunity score: {top_opp.get('score', 0):.2f}

Generate one specific, falsifiable hypothesis in 2-3 sentences.
Start with "We hypothesize that...".""",
        }],
        temperature=0.6,
        max_tokens=200,
    )

    return {
        "hypotheses": [raw.strip()],
        "agent_trace": ["hypothesis → generated 1 hypothesis"],
    }


async def synthesizer_agent(state: AgentState) -> dict:
    """
    Assembles the final response from all agent outputs.
    Streams to user via the API SSE endpoint.
    """
    query          = state["query"]
    papers         = state.get("papers_found", [])
    opportunities  = state.get("opportunities_found", [])
    trends         = state.get("trends_found", [])
    hypotheses     = state.get("hypotheses", [])

    # Build context block
    context_parts = []

    if opportunities:
        opp_text = "\n".join(
            f"- {o['title']} (score: {o.get('score', 0):.2f}): {o.get('hypothesis', '')[:200]}"
            for o in opportunities[:3]
        )
        context_parts.append(f"RESEARCH OPPORTUNITIES:\n{opp_text}")

    if trends:
        trend_text = "\n".join(
            f"- {t.get('domain') or t.get('concept', 'Unknown')}: "
            f"{t.get('recent_papers', 0)} recent papers, "
            f"growth ratio {t.get('growth_ratio', 0)*100:.0f}%"
            for t in trends[:5]
        )
        context_parts.append(f"TREND ANALYSIS:\n{trend_text}")

    if papers:
        paper_text = "\n".join(
            f"- [{p.get('year','?')}] {p.get('title','Unknown')}"
            for p in papers[:5]
        )
        context_parts.append(f"RELEVANT PAPERS:\n{paper_text}")

    if hypotheses:
        context_parts.append(f"GENERATED HYPOTHESIS:\n{hypotheses[0]}")

    context = "\n\n".join(context_parts) if context_parts else "No specific data found."

    response = await nim_chat(
        messages=[{
            "role": "user",
            "content": f"""Answer this research discovery question using the provided data.

Question: {query}

Data from knowledge graph:
{context}

Provide a precise, evidence-based answer (3-5 paragraphs).
Ground every claim in the data above.
End with 2-3 concrete next steps for the researcher.""",
        }],
        temperature=0.3,
        max_tokens=800,
    )

    # Build citation list
    citations = [
        {
            "paper_id": p.get("id"),
            "title": p.get("title"),
            "year": p.get("year"),
            "citations": p.get("citations", 0),
        }
        for p in papers[:5]
        if p.get("id")
    ]

    return {
        "response": response,
        "citations": citations,
        "done": True,
        "agent_trace": ["synthesizer → response assembled"],
    }


# ── GRAPH BUILDER ──────────────────────────────────────────────────────────────

def _intent_router(state: AgentState) -> list[str]:
    """Conditional edge: returns which agents to run based on intent."""
    intent = state.get("intent", "general")
    routes = {
        "discovery":   ["literature", "opportunity"],
        "trend":       ["literature", "trend"],
        "hypothesis":  ["literature", "opportunity"],
        "literature":  ["literature"],
        "general":     ["literature", "opportunity", "trend"],
    }
    return routes.get(intent, ["literature"])


def build_agent_graph():
    """Build and compile the LangGraph agent graph."""
    if not HAS_LANGGRAPH:
        raise RuntimeError("langgraph not installed. pip install langgraph")

    g = StateGraph(AgentState)

    # Register nodes
    g.add_node("router",      router_agent)
    g.add_node("literature",  literature_agent)
    g.add_node("opportunity", opportunity_agent)
    g.add_node("trend",       trend_agent)
    g.add_node("hypothesis",  hypothesis_agent)
    g.add_node("synthesizer", synthesizer_agent)

    # Entry
    g.add_edge(START, "router")

    # Conditional fan-out after router
    g.add_conditional_edges(
        "router",
        _intent_router,
        {
            "literature":  "literature",
            "opportunity": "opportunity",
            "trend":       "trend",
        },
    )

    # All research agents feed into hypothesis
    for agent in ["literature", "opportunity", "trend"]:
        g.add_edge(agent, "hypothesis")

    # hypothesis feeds synthesizer
    g.add_edge("hypothesis", "synthesizer")
    g.add_edge("synthesizer", END)

    return g.compile(checkpointer=MemorySaver())


# Singleton — compiled once at startup
_compiled_graph = None


def get_agent_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
    return _compiled_graph


async def run_discovery_query(query: str, thread_id: str = "default") -> AgentState:
    """
    Run the full agent graph for a user query.
    Returns the final state.
    """
    graph = get_agent_graph()
    initial_state: AgentState = {
        "query":              query,
        "intent":             "",
        "papers_found":       [],
        "opportunities_found": [],
        "trends_found":       [],
        "hypotheses":         [],
        "agent_trace":        [],
        "response":           "",
        "citations":          [],
        "done":               False,
    }

    config = {"configurable": {"thread_id": thread_id}}
    final = await graph.ainvoke(initial_state, config=config)
    return final
