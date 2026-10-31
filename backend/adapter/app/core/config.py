import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "graphiti-memory"
    ENVIRONMENT: str = "development"
    
    # Neo4j
    NEO4J_URI: str
    NEO4J_USER: str
    NEO4J_PASSWORD: str
    
    # Redis
    REDIS_URL: str
    
    # LLM
    LLM_BASE_URL: str
    LLM_API_KEY: str
    LLM_MODEL: str = "gpt-4o-mini"
    
    # Fast LLM (for simple operations like deduplication)
    LLM_FAST_BASE_URL: str
    LLM_FAST_API_KEY: str
    LLM_FAST_MODEL: str = "qwen2.5:7b"
    
    # Embeddings
    EMBEDDING_BASE_URL: str
    EMBEDDING_API_KEY: str
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    
    # Reranker
    RERANKER_BASE_URL: str
    RERANKER_API_KEY: str
    RERANKER_MODEL: str = "reranker-001"
    
    # Extraction quality
    CUSTOM_EXTRACTION_INSTRUCTIONS: str = ""
    
    # Search quality
    SEARCH_MIN_SCORE: float = 0.0  # Min relevance score (0.0 = no filtering)
    USE_RERANKER: bool = True  # Use cross-encoder reranker; false = fallback to RRF
    RERANKER_TIMEOUT: int = 30
    RERANKER_MAX_RETRIES: int = 1
    
    # Adapter
    ADAPTER_API_KEY: str
    JWT_SECRET: str
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str
    ALLOWED_ORIGINS: str = "http://localhost:3000"

    # Graph (per-user node limit for GET /admin/users/{id}/graph)
    GRAPH_DEFAULT_NODES: int = 300
    GRAPH_MAX_NODES: int = 3000
    GRAPH_MAX_EDGES_FACTOR: int = 4

    # LLM request tuning. Graphiti only sends reasoning effort to gpt-5/o-series models,
    # so other reasoning models (deepseek via litellm) fall back to the provider default
    # (often "high") and burn the whole output budget. "" = do not inject.
    LLM_REASONING_EFFORT: str = "low"
    LLM_MAX_TOKENS: int = 16384

    # Episode processing (PendingEpisode retry queue)
    EPISODE_MAX_ATTEMPTS: int = 3
    EPISODE_CONCURRENCY: int = 4
    EPISODE_RETRY_AFTER_MINUTES: int = 30

    # Search: temporal validity and recency
    SEARCH_EXCLUDE_INVALID: bool = True  # drop facts invalidated/expired by newer ones
    SEARCH_RECENCY_WEIGHT: float = 0.15  # 0 = pure relevance ordering
    SEARCH_RECENCY_HALF_LIFE_DAYS: float = 180.0

    # Ingestion: skip LLM extraction for trivial acknowledgements ("ok", "спасибо")
    SKIP_TRIVIAL_MESSAGES: bool = True

    # Nightly consolidation ("sleep-time" maintenance)
    CONSOLIDATION_ENABLED: bool = True
    CONSOLIDATION_HOUR_UTC: int = 3
    CONSOLIDATION_DELETE_ORPHANS: bool = False  # report only by default
    CONSOLIDATION_BUILD_COMMUNITIES: bool = False  # LLM-heavy, opt-in
    
    @property
    def allowed_origins_list(self) -> List[str]:
        """Parse ALLOWED_ORIGINS string into list"""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

settings = Settings()
