"""Tests for tenant isolation, retry queue, search post-processing and new endpoints."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1.memory import is_trivial_message
from app.core.auth import verify_jwt
from app.core.config import settings
from app.main import app
from app.services.graphiti_client import graphiti_client


def _records(*rows):
    return SimpleNamespace(records=[dict(r) for r in rows])


@pytest.fixture
def fake_driver(monkeypatch):
    """Replace the Neo4j driver behind the real GraphitiWrapper."""
    driver = MagicMock()
    driver.execute_query = AsyncMock(return_value=_records())
    fake_client = MagicMock()
    fake_client.driver = driver
    monkeypatch.setattr(graphiti_client, "client", fake_client)
    monkeypatch.setattr(graphiti_client, "_inflight", set())
    return driver


def _queries(driver):
    return [call.args[0] for call in driver.execute_query.call_args_list]


# --- tenant isolation -------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,args",
    [
        ("get_user_episodes", ("35145416",)),
        ("get_user_files", ("35145416",)),
        ("delete_user", ("35145416",)),
        ("delete_file_episodes", ("35145416", "doc.pdf")),
    ],
)
async def test_user_scoped_queries_use_exact_group_id(fake_driver, method, args):
    await getattr(graphiti_client, method)(*args)
    queries = _queries(fake_driver)
    assert queries, "expected at least one query"
    for query in queries:
        assert "STARTS WITH" not in query
    for call in fake_driver.execute_query.call_args_list:
        # never a "35145416_" style prefix parameter that would match "35145416-code"
        assert all(not str(v).endswith("_") for v in call.kwargs.values())
    assert any(
        "35145416" == v for call in fake_driver.execute_query.call_args_list for v in call.kwargs.values()
    )


# --- retry queue ------------------------------------------------------------

@pytest.mark.asyncio
async def test_stuck_episodes_skip_inflight_and_respect_attempts(fake_driver):
    fake_driver.execute_query.return_value = _records(
        {"user_id": "u", "content": "a", "source": "s", "file_name": None, "uuid": "p1"},
        {"user_id": "u", "content": "b", "source": "s", "file_name": None, "uuid": "p2"},
    )
    graphiti_client._inflight.add("p1")
    stuck = await graphiti_client.get_stuck_pending_episodes(minutes=30)
    assert [s["uuid"] for s in stuck] == ["p2"]
    call = fake_driver.execute_query.call_args
    assert call.kwargs["max_attempts"] == settings.EPISODE_MAX_ATTEMPTS
    assert "coalesce(p.attempts, 0) < $max_attempts" in call.args[0]


@pytest.mark.asyncio
async def test_add_episode_marks_failed_after_max_attempts(fake_driver, monkeypatch):
    monkeypatch.setattr(graphiti_client, "_add_episode", AsyncMock(side_effect=RuntimeError("llm down")))
    marks = []

    async def fake_mark(uuid, status, error=None):
        marks.append(status)
        return settings.EPISODE_MAX_ATTEMPTS

    monkeypatch.setattr(graphiti_client, "_mark_pending", fake_mark)
    with pytest.raises(RuntimeError):
        await graphiti_client.add_episode("u", "text", {}, pending_uuid="p1")
    assert marks == ["processing", "pending", "failed"]
    assert "p1" not in graphiti_client._inflight


@pytest.mark.asyncio
async def test_add_episode_deletes_pending_by_uuid(fake_driver, monkeypatch):
    monkeypatch.setattr(graphiti_client, "_add_episode", AsyncMock(return_value="u_ts"))
    monkeypatch.setattr(graphiti_client, "_mark_pending", AsyncMock(return_value=1))
    await graphiti_client.add_episode("u", "text", {}, pending_uuid="p1")
    delete_call = fake_driver.execute_query.call_args
    assert "PendingEpisode {uuid: $uuid}" in delete_call.args[0]
    assert delete_call.kwargs["uuid"] == "p1"


# --- search post-processing -------------------------------------------------

def _edge(uuid, days_old, invalid=False, expired=False):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        uuid=uuid,
        fact=f"fact {uuid}",
        episodes=[],
        created_at=now - timedelta(days=days_old),
        valid_at=now - timedelta(days=days_old),
        invalid_at=now - timedelta(days=1) if invalid else None,
        expired_at=now - timedelta(days=1) if expired else None,
        source_node_uuid="a",
        target_node_uuid="b",
    )


@pytest.mark.asyncio
async def test_search_drops_stale_facts_and_keeps_scores_aligned(fake_driver, monkeypatch):
    monkeypatch.setattr(settings, "USE_RERANKER", True)
    monkeypatch.setattr(settings, "SEARCH_RECENCY_WEIGHT", 0.0)
    edges = [_edge("old-invalid", 1, invalid=True), _edge("ok", 1), _edge("superseded", 1, expired=True)]
    graphiti_client.client.search_ = AsyncMock(
        return_value=SimpleNamespace(edges=edges, edge_reranker_scores=[0.9, 0.8, 0.7])
    )
    hits = await graphiti_client.search("u", "q", limit=5)
    assert [(h.uuid, h.score) for h in hits] == [("ok", 0.8)]

    hits = await graphiti_client.search("u", "q", limit=5, include_invalid=True)
    assert [h.uuid for h in hits] == ["old-invalid", "ok", "superseded"]


@pytest.mark.asyncio
async def test_search_recency_reorders_close_scores(fake_driver, monkeypatch):
    monkeypatch.setattr(settings, "USE_RERANKER", True)
    monkeypatch.setattr(settings, "SEARCH_RECENCY_WEIGHT", 0.5)
    edges = [_edge("old", 900), _edge("new", 1)]
    graphiti_client.client.search_ = AsyncMock(
        return_value=SimpleNamespace(edges=edges, edge_reranker_scores=[0.80, 0.78])
    )
    hits = await graphiti_client.search("u", "q", limit=2)
    assert [h.uuid for h in hits] == ["new", "old"]
    # reported score stays the relevance score
    assert hits[0].score == 0.78


@pytest.mark.asyncio
async def test_search_node_distance_uses_center_node(fake_driver, monkeypatch):
    monkeypatch.setattr(graphiti_client, "_center_cache", {})
    fake_driver.execute_query.return_value = _records({"uuid": "center-1"})
    graphiti_client.client.search_ = AsyncMock(return_value=SimpleNamespace(edges=[_edge("e", 1)]))
    hits = await graphiti_client.search("u", "q", limit=3, search_mode="node_distance")
    assert [h.uuid for h in hits] == ["e"]
    assert graphiti_client.client.search_.call_args.kwargs["center_node_uuid"] == "center-1"


# --- endpoints --------------------------------------------------------------

@pytest.mark.parametrize("text", ["ok", "Ок!", "спасибо", "👍", "да."])
def test_trivial_messages(text):
    assert is_trivial_message(text)


@pytest.mark.parametrize("text", ["Меня зовут Вадим", "I live in Berlin"])
def test_non_trivial_messages(text):
    assert not is_trivial_message(text)


@pytest.mark.asyncio
async def test_append_skips_trivial_and_passes_pending_uuid(mock_graphiti, override_dependencies):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        skipped = await ac.post("/memory/append", json={"user_id": "u", "text": "ок"})
        kept = await ac.post("/memory/append", json={"user_id": "u", "text": "Я работаю в Яндексе"})
    assert skipped.json()["id"] == "skipped"
    assert kept.json()["id"] == "pending-uuid"
    mock_graphiti.save_pending_episode.assert_awaited_once()
    assert mock_graphiti.add_episode.call_args.kwargs["pending_uuid"] == "pending-uuid"


@pytest.mark.asyncio
async def test_bulk_append(mock_graphiti, override_dependencies):
    payload = {
        "user_id": "u",
        "items": [
            {"text": "chunk one of the file", "metadata": {"file_name": "a.txt"}},
            {"text": "ok"},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post("/memory/append/bulk", json=payload)
    assert response.status_code == 200
    assert response.json()["accepted"] == 1
    assert response.json()["skipped"] == 1
    mock_graphiti.add_episodes_bulk.assert_awaited_once()


@pytest.mark.asyncio
async def test_query_forwards_search_options(mock_graphiti, override_dependencies):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/memory/query",
            json={"user_id": "u", "query": "q", "search_mode": "node_distance", "include_invalid": True},
        )
    assert response.status_code == 200
    kwargs = mock_graphiti.search.call_args.kwargs
    assert kwargs["search_mode"] == "node_distance"
    assert kwargs["include_invalid"] is True


@pytest.mark.asyncio
async def test_community_endpoints(mock_graphiti, override_dependencies):
    app.dependency_overrides[verify_jwt] = lambda: "admin"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        listing = await ac.get("/admin/users/u/communities")
        build = await ac.post("/admin/users/u/communities/build")
        members = await ac.get("/admin/users/u/communities/c1/members", params={"limit": 50})
    assert listing.json() == {"communities": [], "total": 0}
    assert build.json() == {"status": "started"}
    assert members.status_code == 200
    mock_graphiti.get_community_members_graph.assert_awaited_once_with("u", "c1", limit=50)
