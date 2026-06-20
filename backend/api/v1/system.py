"""
System API — LLM provider status and configuration.

GET  /system/llm           — current provider, model, and reachability
POST /system/llm/test       — send a tiny test prompt and time the response
"""
from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from core.config import get_settings
from core.nim_client import check_llm_health, nim_chat

settings = get_settings()
router = APIRouter(prefix="/system", tags=["system"])


@router.get("/llm")
async def llm_status():
    """
    Returns the active LLM provider, configured models, and a quick
    reachability probe. Use this to power a status indicator in the UI
    (e.g. "● Local — llama3.1 — 42ms" or "● NIM — unreachable").
    """
    health = await check_llm_health()
    return {
        **health,
        "is_local": settings.is_local_llm,
        "embed_dim": settings.active_embed_dim,
        "note": (
            "Switching LLM_PROVIDER changes the embedding dimension. "
            "Existing Qdrant vectors won't match the new model — re-run "
            "ingestion or wipe collections after switching providers."
        ),
    }


class TestPromptRequest(BaseModel):
    prompt: str = "Say 'pandora is online' and nothing else."


@router.post("/llm/test")
async def llm_test(req: TestPromptRequest):
    """
    Send a small test prompt through the active provider and report
    latency + the raw response. Useful for verifying a freshly-configured
    local model actually works end-to-end before running ingestion.
    """
    t0 = time.monotonic()
    try:
        response = await nim_chat(
            messages=[{"role": "user", "content": req.prompt}],
            max_tokens=50,
            temperature=0.1,
        )
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        return {
            "ok": True,
            "provider": settings.LLM_PROVIDER,
            "model": settings.active_chat_model,
            "response": response,
            "latency_ms": elapsed_ms,
        }
    except Exception as e:
        elapsed_ms = round((time.monotonic() - t0) * 1000)
        return {
            "ok": False,
            "provider": settings.LLM_PROVIDER,
            "model": settings.active_chat_model,
            "error": str(e),
            "latency_ms": elapsed_ms,
        }
