
import pytest
from httpx import AsyncClient
from app.main import app
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_get_episodes_limit_param(mock_graphiti, override_dependencies):
    """
    Test that the limit parameter is correctly parsed and passed to the service.
    """
    user_id = "test_user"
    mock_graphiti.get_user_episodes = AsyncMock(return_value=[
        {"uuid": "1", "content": "test1", "created_at": "2024-01-01", "status": "processed"},
        {"uuid": "2", "content": "test2", "created_at": "2024-01-02", "status": "processed"}
    ])
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get(
            f"/memory/users/{user_id}/episodes",
            params={"limit": 5},
            headers={"X-API-Key": "test_key"}
        )
    
    assert response.status_code == 200
    # Verify the service was called with the correct limit
    mock_graphiti.get_user_episodes.assert_called_once_with(user_id, limit=5)
