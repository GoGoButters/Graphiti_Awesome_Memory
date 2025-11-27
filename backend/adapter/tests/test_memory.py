import pytest
from httpx import AsyncClient
from app.main import app
from app.core.config import settings

@pytest.mark.asyncio
async def test_append_memory():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/memory/append",
            json={
                "user_id": "test_user",
                "text": "Hello world",
                "role": "user"
            },
            headers={"X-API-KEY": settings.ADAPTER_API_KEY}
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "id" in data

@pytest.mark.asyncio
async def test_query_memory():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post(
            "/memory/query",
            json={
                "user_id": "test_user",
                "query": "Hello"
            },
            headers={"X-API-KEY": settings.ADAPTER_API_KEY}
        )
    assert response.status_code == 200
    data = response.json()
    assert "hits" in data
    assert isinstance(data["hits"], list)
