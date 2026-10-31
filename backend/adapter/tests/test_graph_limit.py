
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.auth import verify_jwt
from unittest.mock import AsyncMock

GRAPH_RESPONSE = {
    "nodes": [],
    "edges": [],
    "total_nodes": 0,
    "total_edges": 0,
    "truncated": False,
    "limit": 300,
}


@pytest.fixture(autouse=True)
def override_admin_auth():
    """Allow /admin endpoints without a real JWT."""
    app.dependency_overrides[verify_jwt] = lambda: "admin"
    yield
    app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_graph_limit_passed_to_service(mock_graphiti, override_dependencies):
    """Limit param is parsed and passed to the service."""
    user_id = "test_user"
    mock_graphiti.get_user_graph = AsyncMock(return_value=dict(GRAPH_RESPONSE))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/admin/users/{user_id}/graph", params={"limit": 50})

    assert response.status_code == 200
    mock_graphiti.get_user_graph.assert_called_once_with(user_id, limit=50)


@pytest.mark.asyncio
async def test_graph_default_limit(mock_graphiti, override_dependencies):
    """Without limit, the default GRAPH_DEFAULT_NODES is used."""
    user_id = "test_user"
    mock_graphiti.get_user_graph = AsyncMock(return_value=dict(GRAPH_RESPONSE))

    from app.core.config import settings

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/admin/users/{user_id}/graph")

    assert response.status_code == 200
    mock_graphiti.get_user_graph.assert_called_once_with(
        user_id, limit=settings.GRAPH_DEFAULT_NODES
    )


@pytest.mark.asyncio
async def test_graph_limit_above_max_422(mock_graphiti, override_dependencies):
    """limit > GRAPH_MAX_NODES -> 422."""
    user_id = "test_user"

    from app.core.config import settings

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(
            f"/admin/users/{user_id}/graph",
            params={"limit": settings.GRAPH_MAX_NODES + 1},
        )

    assert response.status_code == 422
    mock_graphiti.get_user_graph.assert_not_called()


@pytest.mark.asyncio
async def test_graph_limit_below_10_422(mock_graphiti, override_dependencies):
    """limit < 10 -> 422."""
    user_id = "test_user"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/admin/users/{user_id}/graph", params={"limit": 5})

    assert response.status_code == 422
    mock_graphiti.get_user_graph.assert_not_called()


@pytest.mark.asyncio
async def test_graph_service_error_500(mock_graphiti, override_dependencies):
    """Service error propagates as HTTP 500, not an empty graph."""
    user_id = "test_user"
    mock_graphiti.get_user_graph = AsyncMock(side_effect=RuntimeError("boom"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get(f"/admin/users/{user_id}/graph", params={"limit": 50})

    assert response.status_code == 500
