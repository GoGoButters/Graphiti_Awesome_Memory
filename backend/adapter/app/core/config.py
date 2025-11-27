import os
from typing import List
from pydantic_settings import BaseSettings

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
    
    # Embeddings
    EMBEDDING_BASE_URL: str
    EMBEDDING_API_KEY: str
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    
    # Reranker
    RERANKER_BASE_URL: str
    RERANKER_API_KEY: str
    RERANKER_MODEL: str = "reranker-001"
    
    # Adapter
    ADAPTER_API_KEY: str
    JWT_SECRET: str
    ADMIN_USERNAME: str
    ADMIN_PASSWORD: str
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
