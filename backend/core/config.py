from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    ENV: str = "development"
    SECRET_KEY: str = "change-me"
    API_PREFIX: str = "/api/v1"

    # NVIDIA NIM
    NVIDIA_NIM_API_KEY: str
    NVIDIA_NIM_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NIM_CHAT_MODEL: str = "meta/llama-3.1-70b-instruct"
    NIM_EMBED_MODEL: str = "nvidia/nv-embedqa-e5-v5"
    NIM_EMBED_DIM: int = 1024

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
