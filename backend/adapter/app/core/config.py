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
    
    # Graphiti
    GRAPHITI_URL: str
    GRAPHITI_USE_SDK: bool = True
    
    # Redis
    REDIS_URL: str
    
    # OpenAI
    OPENAI_BASE_URL: str
    OPENAI_API_KEY: str
    LLM_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    
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
