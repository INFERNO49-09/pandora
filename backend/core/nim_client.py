"""
LLM client — routes to NVIDIA NIM (cloud) or a local model server, based on
settings.LLM_PROVIDER. Every other module imports nim_chat / nim_embed /
nim_embed_single and is unaware of which backend is actually serving the
request — switching providers is a single .env change.

Local provider supports any OpenAI-compatible server:
  - Ollama (>= 0.1.26, via its /v1 compatibility layer)
  - LM Studio (built-in OpenAI-compatible server)
  - llama.cpp server (--api-server-port with /v1 routes)
  - vLLM / text-generation-webui (OpenAI-compatible mode)

Ollama's older native embeddings endpoint (/api/embeddings) is also
supported via LOCAL_USE_OLLAMA_NATIVE_EMBEDDINGS, for setups where the
/v1/embeddings route isn't available.
"""
from functools import lru_cache
import inspect

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from core.config import get_settings

settings = get_settings()


# ── CLIENT FACTORY ────────────────────────────────────────────────────────────

@lru_cache
def get_nim_client() -> AsyncOpenAI:
    """
    Returns an OpenAI-compatible client pointed at whichever backend is active.
    Cached so we reuse the same connection pool across calls.
    """
    if settings.is_local_llm:
        return AsyncOpenAI(
            api_key=settings.LOCAL_LLM_API_KEY,
            base_url=settings.LOCAL_LLM_BASE_URL,
            timeout=settings.LOCAL_LLM_TIMEOUT,
        )
    return AsyncOpenAI(
        api_key=settings.NVIDIA_NIM_API_KEY,
        base_url=settings.NVIDIA_NIM_BASE_URL,
    )


async def close_nim_client() -> None:
    """Close the cached OpenAI-compatible async client, if one exists."""
    if get_nim_client.cache_info().currsize == 0:
        return

    client = get_nim_client()
    result = client.close()
    if inspect.isawaitable(result):
        await result
    get_nim_client.cache_clear()


def get_active_provider() -> str:
    """Returns 'local' or 'nim' — used by health checks and the UI."""
    return settings.LLM_PROVIDER


# ── CHAT ──────────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def nim_chat(
    messages: list[dict],
    system_prompt: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    response_format: dict | None = None,
) -> str:
    """
    Call chat completion on the active provider. Returns the text content.
    Temperature 0.1 for extraction tasks (deterministic).
    Temperature 0.7 for hypothesis generation (creative).

    Note: response_format (strict JSON mode) is only sent to providers that
    support it. Many local models (via Ollama/llama.cpp) either ignore it or
    error on unknown fields, so we drop it for the local provider — callers
    already parse JSON defensively (see extraction/engine.py._parse_json).
    """
    client = get_nim_client()

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    kwargs = dict(
        model=settings.active_chat_model,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_format and not settings.is_local_llm:
        kwargs["response_format"] = response_format

    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception as e:
        if settings.is_local_llm:
            logger.error(
                f"Local LLM call failed ({settings.LOCAL_LLM_BASE_URL}, "
                f"model={settings.active_chat_model}): {e}. "
                f"Is the local server running? (e.g. `ollama serve`, or check LM Studio's server tab)"
            )
        raise
    return response.choices[0].message.content


# ── EMBEDDINGS ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def nim_embed(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings via the active provider.
    Returns list of float vectors, one per input text.
    """
    return await nim_embed_with_input_type(texts, input_type="passage")


async def nim_embed_with_input_type(
    texts: list[str],
    input_type: str = "passage",
) -> list[list[float]]:
    """
    Generate embeddings with provider-specific input type metadata.
    NVIDIA embedding models require input_type; local OpenAI-compatible
    servers usually ignore or reject that extra field, so only NIM receives it.
    """
    if settings.is_local_llm and settings.LOCAL_USE_OLLAMA_NATIVE_EMBEDDINGS:
        return await _ollama_native_embed(texts)

    client = get_nim_client()

    # Cap batch size — local servers in particular can choke on huge batches
    BATCH_SIZE = 16 if settings.is_local_llm else 96
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        try:
            kwargs = {
                "model": settings.active_embed_model,
                "input": batch,
                "encoding_format": "float",
            }
            if not settings.is_local_llm:
                kwargs["extra_body"] = {"input_type": input_type}
            response = await client.embeddings.create(**kwargs)
        except Exception as e:
            if settings.is_local_llm:
                logger.error(
                    f"Local embedding call failed (model={settings.active_embed_model}): {e}. "
                    f"If using Ollama, ensure the model is pulled (`ollama pull {settings.active_embed_model}`) "
                    f"or set LOCAL_USE_OLLAMA_NATIVE_EMBEDDINGS=true if your Ollama version lacks /v1/embeddings."
                )
            raise
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


async def _ollama_native_embed(texts: list[str]) -> list[list[float]]:
    """
    Fallback path for Ollama installs that don't expose /v1/embeddings.
    Uses Ollama's native /api/embeddings, one request per text (no native batching).
    """
    native_base = settings.LOCAL_LLM_BASE_URL.rstrip("/").removesuffix("/v1")
    url = f"{native_base}/api/embeddings"

    embeddings: list[list[float]] = []
    async with httpx.AsyncClient(timeout=settings.LOCAL_LLM_TIMEOUT) as client:
        for text in texts:
            try:
                resp = await client.post(
                    url,
                    json={"model": settings.active_embed_model, "prompt": text},
                )
                resp.raise_for_status()
                embeddings.append(resp.json()["embedding"])
            except Exception as e:
                logger.error(f"Ollama native embedding failed for text chunk: {e}")
                raise

    return embeddings


async def nim_embed_single(text: str) -> list[float]:
    results = await nim_embed_with_input_type([text], input_type="query")
    return results[0]


# ── HEALTH CHECK ──────────────────────────────────────────────────────────────

async def check_llm_health() -> dict:
    """
    Probe the active LLM provider. Used by /system/llm and /health/detailed.
    Returns provider, models, reachability, and latency — never raises.
    """
    import time

    result: dict = {
        "provider": settings.LLM_PROVIDER,
        "chat_model": settings.active_chat_model,
        "embed_model": settings.active_embed_model,
        "base_url": settings.LOCAL_LLM_BASE_URL if settings.is_local_llm else settings.NVIDIA_NIM_BASE_URL,
        "status": "unknown",
    }

    if settings.is_local_llm:
        # Try listing models — cheapest way to confirm the server is up
        # without burning a real generation.
        native_base = settings.LOCAL_LLM_BASE_URL.rstrip("/").removesuffix("/v1")
        try:
            t0 = time.monotonic()
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{native_base}/api/tags")  # Ollama-native
                if resp.status_code == 200:
                    tags = resp.json().get("models", [])
                    result["available_models"] = [m.get("name") for m in tags]
                else:
                    # Not Ollama — try the OpenAI-compatible /v1/models route instead
                    resp = await client.get(f"{settings.LOCAL_LLM_BASE_URL.rstrip('/')}/models")
                    resp.raise_for_status()
                    result["available_models"] = [m.get("id") for m in resp.json().get("data", [])]
            result["latency_ms"] = round((time.monotonic() - t0) * 1000)
            result["status"] = "ok"
            chat_model_available = (
                not result.get("available_models")
                or settings.active_chat_model in result["available_models"]
            )
            if not chat_model_available:
                result["status"] = "model_not_pulled"
                result["warning"] = (
                    f"Server is reachable but '{settings.active_chat_model}' isn't loaded. "
                    f"Run: ollama pull {settings.active_chat_model}"
                )
        except Exception as e:
            result["status"] = "unreachable"
            result["error"] = str(e)
            result["hint"] = "Is the local server running? Try `ollama serve` or check your LM Studio server tab."
    else:
        try:
            t0 = time.monotonic()
            await nim_chat(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
            result["latency_ms"] = round((time.monotonic() - t0) * 1000)
            result["status"] = "ok"
        except Exception as e:
            result["status"] = "unreachable"
            result["error"] = str(e)

    return result
