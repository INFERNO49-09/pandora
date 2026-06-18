"""
NVIDIA NIM client.
NIM exposes an OpenAI-compatible API, so we use the openai SDK
pointed at the NIM base URL.
"""
from functools import lru_cache
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger
from core.config import get_settings

settings = get_settings()


@lru_cache
def get_nim_client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=settings.NVIDIA_NIM_API_KEY,
        base_url=settings.NVIDIA_NIM_BASE_URL,
    )


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
    Call NIM chat completion. Returns the text content of the response.
    Temperature 0.1 for extraction tasks (deterministic).
    Temperature 0.7 for hypothesis generation (creative).
    """
    client = get_nim_client()

    full_messages = []
    if system_prompt:
        full_messages.append({"role": "system", "content": system_prompt})
    full_messages.extend(messages)

    kwargs = dict(
        model=settings.NIM_CHAT_MODEL,
        messages=full_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def nim_embed(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings via NIM embedding model.
    Returns list of float vectors, one per input text.
    Batches automatically handled by NIM.
    """
    client = get_nim_client()

    # NIM embedding models have input limits — chunk if needed
    BATCH_SIZE = 96
    all_embeddings = []

    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        response = await client.embeddings.create(
            model=settings.NIM_EMBED_MODEL,
            input=batch,
            encoding_format="float",
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

    return all_embeddings


async def nim_embed_single(text: str) -> list[float]:
    results = await nim_embed([text])
    return results[0]
