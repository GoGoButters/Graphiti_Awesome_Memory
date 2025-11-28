import os
import pytest
from unittest.mock import patch

# Set environment variables before any imports
os.environ.update({
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "password",
    "REDIS_URL": "redis://localhost:6379/0",
    "LLM_BASE_URL": "https://api.openai.com/v1",
    "LLM_API_KEY": "sk-test",
    "LLM_MODEL": "gpt-4o-mini",
    "EMBEDDING_BASE_URL": "https://api.openai.com/v1",
    "EMBEDDING_API_KEY": "sk-test",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "RERANKER_BASE_URL": "https://api.openai.com/v1",
    "RERANKER_API_KEY": "sk-test",
    "RERANKER_MODEL": "reranker-001",
    "ADAPTER_API_KEY": "test-key",
    "JWT_SECRET": "test-secret",
    "ADMIN_USERNAME": "admin",
    "ADMIN_PASSWORD": "password"
})

@pytest.fixture(scope="session", autouse=True)
def mock_settings():
    """Mock environment variables for testing (redundant but keeps it safe)"""
    yield

@pytest.fixture(autouse=True)
def mock_graphiti():
    """Mock Graphiti client to avoid DB connection"""
    from unittest.mock import AsyncMock
    
    with patch("app.api.v1.memory.graphiti_client") as mock_client:
        # Mock add_episode
        mock_client.add_episode = AsyncMock(return_value="test_episode_id")
        
        # Mock search
        from app.models.schemas import MemoryHit
        from datetime import datetime
        mock_client.search = AsyncMock(return_value=[
            MemoryHit(
                fact="Test fact",
                score=1.0,
                uuid="test_uuid",
                created_at=datetime.now(),
                metadata={}
            )
        ])
        
        # Mock get_summary
        mock_client.get_summary = AsyncMock(return_value="Test summary")
        
        yield mock_client
