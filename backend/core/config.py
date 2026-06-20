from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    ENV: str = "development"
    SECRET_KEY: str = "change-me"
    API_PREFIX: str = "/api/v1"

    # LLM Provider — "nim" (NVIDIA NIM, cloud) or "local" (Ollama / LM Studio / llama.cpp)
    LLM_PROVIDER: str = "nim"

    # NVIDIA NIM (only required when LLM_PROVIDER=nim)
    NVIDIA_NIM_API_KEY: str = ""
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NIM_CHAT_MODEL: str = "meta/llama-3.1-70b-instruct"
    NIM_EMBED_MODEL: str = "nvidia/nv-embedqa-e5-v5"
    NIM_EMBED_DIM: int = 1024

    # Local LLM (only used when LLM_PROVIDER=local)
    # Works with any OpenAI-compatible server: Ollama (>=0.1.26 with /v1), LM Studio, llama.cpp server, vLLM, text-generation-webui.
    LOCAL_LLM_BASE_URL: str = "http://localhost:11434/v1"   # Ollama's OpenAI-compatible endpoint
    LOCAL_LLM_API_KEY: str = "not-needed"                    # most local servers ignore this but the SDK requires a value
    LOCAL_CHAT_MODEL: str = "llama3.1"
    LOCAL_EMBED_MODEL: str = "nomic-embed-text"
    LOCAL_EMBED_DIM: int = 768                                # nomic-embed-text is 768-dim; mxbai-embed-large is 1024-dim, etc.
    LOCAL_LLM_TIMEOUT: float = 120.0                          # local inference is slower than cloud — generous timeout
    # Ollama doesn't natively serve OpenAI's /v1/embeddings on older versions; set true to use its native /api/embeddings instead
    LOCAL_USE_OLLAMA_NATIVE_EMBEDDINGS: bool = False

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "pandora_secret"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333

    # Postgres
    POSTGRES_DSN: str = "postgresql+asyncpg://pandora:pandora_secret@localhost:5432/pandora"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Ingestion
    INGESTION_BATCH_SIZE: int = 100
    MAX_PAPERS_PER_RUN: int = 10_000

    # Discovery
    OPPORTUNITY_MIN_SCORE: float = 0.55
    LINK_PREDICTION_TOP_K: int = 20
    CARGS_SCAN_DOMAIN_LIMIT: int = 500

    @property
    def is_dev(self) -> bool:
        return self.ENV == "development"

    @property
    def is_local_llm(self) -> bool:
        return self.LLM_PROVIDER == "local"

    @property
    def active_chat_model(self) -> str:
        return self.LOCAL_CHAT_MODEL if self.is_local_llm else self.NIM_CHAT_MODEL

    @property
    def active_embed_model(self) -> str:
        return self.LOCAL_EMBED_MODEL if self.is_local_llm else self.NIM_EMBED_MODEL

    @property
    def active_embed_dim(self) -> int:
        return self.LOCAL_EMBED_DIM if self.is_local_llm else self.NIM_EMBED_DIM

    def model_post_init(self, __context) -> None:
        if self.LLM_PROVIDER not in ("nim", "local"):
            raise ValueError(f"LLM_PROVIDER must be 'nim' or 'local', got {self.LLM_PROVIDER!r}")
        if self.LLM_PROVIDER == "nim" and not self.NVIDIA_NIM_API_KEY:
            raise ValueError(
                "NVIDIA_NIM_API_KEY is required when LLM_PROVIDER=nim. "
                "Set LLM_PROVIDER=local in .env to use a local model instead (Ollama, LM Studio, etc.)."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
