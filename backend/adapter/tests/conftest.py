
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.main import app
from app.services.graphiti_client import graphiti_client
from app.core.auth import get_api_key

@pytest.fixture
def mock_graphiti():
    """
    Mock the graphiti client to prevent actual DB calls.
    """
    # Create a mock object that mimics GraphitiWrapper
    mock = MagicMock()
    
    # Mock async methods
    mock.get_user_episodes = AsyncMock(return_value=[])
    mock.add_episode = AsyncMock(return_value="test_uuid")
    mock.search = AsyncMock(return_value=[])
    mock.get_user_graph = AsyncMock(return_value={"nodes": [], "edges": []})
    mock.save_pending_episode = AsyncMock()
    mock.delete_pending_episode = AsyncMock()
    mock.delete_file_episodes = AsyncMock(return_value=True)
    
    # Replace the actual client instance with our mock
    # We need to monkeypatch the module-level variable
    original_client = graphiti_client
    
    # Since graphiti_client is imported in api/v1/memory.py, we should patch it there?
    # Actually, usually patching where it is used is best, but for global singleton, 
    # we can try to patch the instance attributes.
    
    # Better approach for singleton:
    # We will use dependency override or direct patching.
    # Since the code imports the instance `graphiti_client`, we can just modify its methods?
    # No, safer to return a mock and let `override_dependencies` use it, 
    # OR rely on `unittest.mock.patch` in the tests.
    
    # However, the test signature asks for `mock_graphiti` fixture.
    
    return mock

@pytest.fixture
def override_dependencies(mock_graphiti):
    """
    Override FastAPI dependencies.
    """
    # Override API key dependency
    app.dependency_overrides[get_api_key] = lambda: "test_key"
    
    # We also need to patch the graphiti_client used by the app.
    # Since it's a global imported instance, we can patch `app.api.v1.memory.graphiti_client`
    with pytest.MonkeyPatch.context() as m:
        m.setattr("app.api.v1.memory.graphiti_client", mock_graphiti)
        m.setattr("app.api.v1.admin.graphiti_client", mock_graphiti)
        yield
    
    # Clean up
    app.dependency_overrides = {}
