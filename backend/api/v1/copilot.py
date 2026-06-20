"""
Copilot API — streaming agent responses via Server-Sent Events.

The agent graph runs asynchronously and streams tokens to the client
as they're produced. Each SSE event has a `type` field:
  thinking   — agent trace message (which agent is running)
  token      — response text chunk
  citation   — paper citation card
  opportunity — research opportunity card
  complete   — end of stream
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from auth.middleware import User, optional_user, rate_limiter

router = APIRouter(prefix="/copilot", tags=["copilot"])

bearer_scheme = HTTPBearer(auto_error=False)


class CopilotRequest(BaseModel):
    query: str
    thread_id: str | None = None


def _sse(event_type: str, data: dict | str) -> str:
    """Format a Server-Sent Event."""
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"data: {json.dumps({'type': event_type, 'content': payload})}\n\n"


@router.post("/query")
async def copilot_query(
    req: CopilotRequest,
    current_user: User | None = Depends(optional_user),
):
    """
    Main copilot endpoint. Streams agent execution as SSE.
    Rate-limited: free tier users get 50 queries/month.

    Example curl:
        curl -N -X POST http://localhost:8000/api/v1/copilot/query \\
          -H "Content-Type: application/json" \\
          -d '{"query": "What are unexplored opportunities in federated learning?"}'
    """
    # Enforce rate limit for authenticated users
    if current_user:
        allowed = await rate_limiter.check_and_increment(current_user, "query")
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Monthly query limit reached",
                    "tier": current_user.tier,
                    "limit": current_user.monthly_query_limit,
                    "upgrade": "Upgrade to researcher tier for unlimited queries.",
                },
            )

    thread_id = req.thread_id or str(uuid.uuid4())
    start_ms = int(time.time() * 1000)

    async def event_stream():
        try:
            # Try to import and run the agent graph
            try:
                from agents.discovery_graph import run_discovery_query, HAS_LANGGRAPH
                if not HAS_LANGGRAPH:
                    raise ImportError("langgraph not available")
            except ImportError:
                # Graceful fallback: direct NIM call without agents
                async for chunk in _fallback_response(req.query):
                    yield chunk
                return

            from agents.discovery_graph import get_agent_graph
            graph = get_agent_graph()

            initial_state = {
                "query": req.query,
                "intent": "",
                "papers_found": [],
                "opportunities_found": [],
                "trends_found": [],
                "hypotheses": [],
                "agent_trace": [],
                "response": "",
                "citations": [],
                "done": False,
            }
            config = {"configurable": {"thread_id": thread_id}}

            # Stream intermediate agent trace events while graph runs
            yield _sse("thinking", {"message": "Analyzing your query...", "agent": "router"})

            async for output in graph.astream(initial_state, config=config, stream_mode="updates"):
                for node_name, node_state in output.items():
                    if "agent_trace" in node_state:
                        for trace in node_state["agent_trace"]:
                            yield _sse("thinking", {"message": trace, "agent": node_name})
                    # Stream opportunities early if found
                    if "opportunities_found" in node_state:
                        for opp in node_state["opportunities_found"][:3]:
                            yield _sse("opportunity", {
                                "id":    opp.get("id"),
                                "title": opp.get("title"),
                                "domain_a": opp.get("domain_a"),
                                "domain_b": opp.get("domain_b"),
                                "score": opp.get("score", 0),
                            })

            # Get final state
            final_state_wrapper = await graph.aget_state(config)
            final_state = final_state_wrapper.values

            # Stream response text word by word (simulated streaming)
            response = final_state.get("response", "")
            words = response.split()
            chunk_size = 5
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield _sse("token", chunk)
                await asyncio.sleep(0.02)

            # Stream citations
            for citation in final_state.get("citations", []):
                yield _sse("citation", citation)

            # Done
            yield _sse("complete", {
                "thread_id": thread_id,
                "agents_used": list({
                    t.split(" →")[0] for t in final_state.get("agent_trace", [])
                }),
            })

            # Log query to history (fire-and-forget)
            agents = list({t.split(" →")[0] for t in final_state.get("agent_trace", [])})
            elapsed = int(time.time() * 1000) - start_ms
            from api.v1.query_history import log_query
            await log_query(
                user_id=current_user.id if current_user else None,
                query_text=req.query,
                query_type="copilot",
                response_ms=elapsed,
                agents_used=agents,
            )

        except Exception as e:
            yield _sse("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _fallback_response(query: str):
    """
    Direct NIM response without agents.
    Used when langgraph is not installed.
    """
    from core.nim_client import nim_chat
    from knowledge_graph.client import run_query

    yield _sse("thinking", {"message": "Searching knowledge graph...", "agent": "direct"})

    # Simple graph search
    papers = await run_query(
        """
        CALL db.index.fulltext.queryNodes('paper_fulltext', $query)
        YIELD node AS p, score
        RETURN p.id AS id, p.title AS title, p.year AS year, score
        ORDER BY score DESC LIMIT 5
        """,
        params={"query": query},
    )

    opps = await run_query(
        """
        MATCH (o:ResearchOpportunity)
        WHERE toLower(o.title) CONTAINS toLower($q)
           OR toLower(o.domain_a) CONTAINS toLower($q)
           OR toLower(o.domain_b) CONTAINS toLower($q)
        RETURN o.id AS id, o.title AS title,
               o.domain_a AS domain_a, o.domain_b AS domain_b,
               o.opportunity_score AS score
        ORDER BY o.opportunity_score DESC
        LIMIT 3
        """,
        params={"q": query[:50]},
    )

    context = ""
    if papers:
        context += "Relevant papers:\n" + "\n".join(
            f"- [{p['year']}] {p['title']}" for p in papers
        )
    if opps:
        context += "\n\nResearch opportunities:\n" + "\n".join(
            f"- {o['title']} ({o['domain_a']} × {o['domain_b']}, score={o['score']:.2f})"
            for o in opps
        )

    response = await nim_chat(
        messages=[{
            "role": "user",
            "content": f"Answer this research question using the graph data below.\n\nQuestion: {query}\n\nData:\n{context or 'No specific data found.'}\n\nBe precise and cite the papers/opportunities above.",
        }],
        temperature=0.3,
        max_tokens=600,
    )

    for opp in opps:
        yield _sse("opportunity", opp)

    words = response.split()
    for i in range(0, len(words), 5):
        yield _sse("token", " ".join(words[i:i+5]) + " ")
        await asyncio.sleep(0.02)

    for p in papers:
        if p.get("id"):
            yield _sse("citation", {"paper_id": p["id"], "title": p["title"], "year": p["year"]})

    yield _sse("complete", {"thread_id": "direct", "agents_used": ["direct_nim"]})


@router.get("/history/{thread_id}")
async def get_conversation_history(thread_id: str):
    """
    Retrieve past conversation turns for a thread.
    Requires langgraph MemorySaver to be active.
    """
    try:
        from agents.discovery_graph import get_agent_graph
        graph = get_agent_graph()
        config = {"configurable": {"thread_id": thread_id}}
        state = await graph.aget_state(config)
        return {
            "thread_id": thread_id,
            "state": state.values if state else {},
        }
    except Exception as e:
        return {"thread_id": thread_id, "error": str(e), "state": {}}
