#!/usr/bin/env python3
"""
MCP Server for Graphiti Memory Platform.

This server provides tools to interact with the Graphiti episodic memory system,
including memory append, query, and management capabilities.

Two profiles are supported (GRAPHITI_PROFILE):

* ``full`` (default) — the personal-agent tool set:
  append / query / recall_context / episodes / stats / delete_file.
* ``code`` — a restricted profile for coding agents: reads and writes are pinned
  to one scope (GRAPHITI_USER_ID), the scope is not exposed as a tool argument,
  deletes are not available, and writes are typed (request / result / project) so
  episodes keep a uniform shape.

When ``GRAPHITI_USER_ID`` is set, every operation is pinned to that scope and any
``user_id`` passed by the client is ignored.
"""

import os
import sys
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from enum import Enum
from urllib.parse import quote

import httpx
from pydantic import BaseModel, Field, field_validator, ConfigDict
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROFILE = os.getenv("GRAPHITI_PROFILE", "full").strip().lower()
PINNED_USER_ID = os.getenv("GRAPHITI_USER_ID", "").strip() or None

if PROFILE not in ("full", "code"):
    raise SystemExit("GRAPHITI_PROFILE must be 'full' or 'code', got %r" % PROFILE)

if PROFILE == "code" and not PINNED_USER_ID:
    raise SystemExit("GRAPHITI_PROFILE=code requires GRAPHITI_USER_ID (the scope to pin to)")

# The pinned scope as a plain str: the code profile always has one.
SCOPE: str = PINNED_USER_ID or ""


def _transport_security_settings() -> Optional[TransportSecuritySettings]:
    """Host/Origin allow-list for the HTTP transport.

    FastMCP only accepts ``127.0.0.1``/``localhost`` Host headers by default, so a
    server reached over the LAN answers 421 Misdirected Request. Set
    ``MCP_ALLOWED_HOSTS`` (comma separated, ``host:*`` wildcard for any port) to
    widen it; the DNS-rebinding protection stays on.
    """
    allowed_hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    allowed_origins = [o.strip() for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    if not allowed_hosts and not allowed_origins:
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts or ["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=allowed_origins,
    )


mcp = FastMCP("graphiti_mcp", transport_security=_transport_security_settings())

API_BASE_URL = os.getenv("GRAPHITI_API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("GRAPHITI_API_KEY", "adapter-secret-api-key")
MCP_SERVER_HOST = os.getenv("MCP_SERVER_HOST", "127.0.0.1")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8001"))


def _resolve_user_id(user_id: Optional[str]) -> str:
    """Pin the scope when GRAPHITI_USER_ID is configured, otherwise require it."""
    if PINNED_USER_ID:
        return PINNED_USER_ID
    if not user_id:
        raise ValueError("user_id is required when GRAPHITI_USER_ID is not set")
    return user_id


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class MemoryAppendInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: Optional[str] = Field(
        default=None,
        description="User identifier (e.g., 'user123', 'alice'). Ignored when the server is pinned to a scope.",
        min_length=1,
        max_length=200
    )
    text: str = Field(..., description="Text content to remember", min_length=1, max_length=10000)
    role: str = Field(default="user", description="Role: 'user', 'assistant', or 'system'")
    source: Optional[str] = Field(default=None, description="Source of the memory (e.g., 'n8n', 'chat')")

    @field_validator('role')
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("user", "assistant", "system"):
            raise ValueError("Role must be 'user', 'assistant', or 'system'")
        return v


class MemoryQueryInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: Optional[str] = Field(
        default=None,
        description="User identifier. Ignored when the server is pinned to a scope.",
        min_length=1,
        max_length=200
    )
    query: str = Field(..., description="Search query text", min_length=1, max_length=1000)
    limit: int = Field(default=10, description="Maximum results to return", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class GetEpisodesInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: Optional[str] = Field(
        default=None,
        description="User identifier. Ignored when the server is pinned to a scope.",
        min_length=1,
        max_length=200
    )
    limit: Optional[int] = Field(default=None, description="Maximum episodes to return", ge=1, le=1000)


class DeleteFileInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: Optional[str] = Field(
        default=None,
        description="User identifier. Ignored when the server is pinned to a scope.",
        min_length=1,
        max_length=200
    )
    file_name: str = Field(..., description="File name to delete", min_length=1, max_length=500)


class RecallContextInput(BaseModel):
    """Input for memory recall context injection."""
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: Optional[str] = Field(
        default=None,
        description="User identifier. Ignored when the server is pinned to a scope.",
        min_length=1,
        max_length=200
    )
    query: str = Field(..., description="Current conversation query to find relevant memories for", min_length=1, max_length=1000)
    limit: int = Field(default=5, description="Maximum memories to recall", ge=1, le=20)


async def _make_request(endpoint: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
    """Make API request to Graphiti adapter."""
    headers = {"X-API-KEY": API_KEY}
    if "json" in kwargs:
        headers["Content-Type"] = "application/json"

    url = f"{API_BASE_URL}{endpoint}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()


def _handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        if e.response.status_code == 401:
            return "Error: Unauthorized. Check your API key."
        elif e.response.status_code == 403:
            return "Error: Forbidden. You don't have access."
        elif e.response.status_code == 404:
            return "Error: User not found."
        elif e.response.status_code == 429:
            return "Error: Rate limit exceeded. Please wait."
        return f"Error: HTTP {e.response.status_code}: {e.response.text[:200]}"
    elif isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out."
    return f"Error: {type(e).__name__}: {str(e)}"


async def _append(user_id: str, text: str, role: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Append one episode for the given scope."""
    payload = {
        "user_id": user_id,
        "text": text,
        "role": role,
        "metadata": metadata or {}
    }
    return await _make_request("/memory/append", method="POST", json=payload)


def _append_ack(user_id: str, result: Dict[str, Any]) -> str:
    return f"""# Memory Appended Successfully

- **User**: {user_id}
- **Episode ID**: {result.get('id', 'N/A')}
- **Timestamp**: {result.get('created_ts', 'N/A')}
- **Status**: {'Success' if result.get('ok') else 'Failed'}
"""


if PROFILE == "full":

    @mcp.tool(
        name="graphiti_append_memory",
        annotations={
            "title": "Append Memory to Graphiti",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def graphiti_append_memory(params: MemoryAppendInput) -> str:
        """Add a new memory episode to a user's knowledge graph."""
        try:
            user_id = _resolve_user_id(params.user_id)
            metadata = {}
            if params.source:
                metadata["source"] = params.source

            result = await _append(user_id, params.text, params.role, metadata)
            return _append_ack(user_id, result)

        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="graphiti_query_memory",
        annotations={
            "title": "Query Graphiti Memory",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def graphiti_query_memory(params: MemoryQueryInput) -> str:
        """Search a user's memory using semantic search."""
        try:
            user_id = _resolve_user_id(params.user_id)
            payload = {
                "user_id": user_id,
                "query": params.query,
                "limit": params.limit
            }

            result = await _make_request("/memory/query", method="POST", json=payload)
            hits = result.get("hits", [])
            total = result.get("total", 0)

            if params.response_format == ResponseFormat.JSON:
                import json
                return json.dumps(result, indent=2, default=str)

            if not hits:
                return f"# No memories found for '{params.query}'\n\nNo relevant memories found for user **{user_id}**."

            lines = [f"# Memory Search Results: '{params.query}'", ""]
            lines.append(f"Found **{total}** relevant memories")
            lines.append("")

            for i, hit in enumerate(hits, 1):
                lines.append(f"## Result {i}")
                lines.append(f"- **Fact**: {hit.get('fact', 'N/A')}")
                lines.append(f"- **Score**: {hit.get('score', 0):.2f}")
                lines.append(f"- **Date**: {hit.get('created_at', 'N/A')}")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="graphiti_get_episodes",
        annotations={
            "title": "Get User Episodes",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def graphiti_get_episodes(params: GetEpisodesInput) -> str:
        """Retrieve episodes for a specific user."""
        try:
            user_id = _resolve_user_id(params.user_id)
            url = f"/memory/users/{quote(user_id, safe='')}/episodes"
            if params.limit:
                url += f"?limit={params.limit}"

            result = await _make_request(url)
            episodes = result.get("episodes", [])
            total = result.get("total", 0)

            if not episodes:
                return f"# No episodes for user **{user_id}**\n\nThis user has no memory records."

            lines = [f"# User Episodes: {user_id}", ""]
            lines.append(f"Showing **{len(episodes)}** of **{total}** total episodes")
            lines.append("")

            for i, ep in enumerate(episodes, 1):
                lines.append(f"## Episode {i}")
                lines.append(f"- **Date**: {ep.get('created_at', 'N/A')}")
                lines.append(f"- **Source**: {ep.get('source', 'N/A')}")
                content = ep.get('content', 'N/A')
                lines.append(f"- **Content**: {content[:200]}...")
                lines.append("")

            return "\n".join(lines)

        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="graphiti_delete_file",
        annotations={
            "title": "Delete File Data",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def graphiti_delete_file(params: DeleteFileInput) -> str:
        """Delete all data associated with a specific file."""
        try:
            user_id = _resolve_user_id(params.user_id)
            url = f"/memory/files?user_id={quote(user_id, safe='')}&file_name={quote(params.file_name, safe='')}"

            result = await _make_request(url, method="DELETE")

            if result.get("ok"):
                return f"# File Deleted Successfully\n\n- **User**: {user_id}\n- **File**: {params.file_name}\n- **Status**: Deleted"

            return f"# Deletion Failed\n\n{result.get('message', 'Unknown error')}"

        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="graphiti_get_user_stats",
        annotations={
            "title": "Get User Statistics",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def graphiti_get_user_stats(user_id: Optional[str] = None) -> str:
        """Get statistics for a user."""
        try:
            uid = _resolve_user_id(user_id)
            # The adapter's `total` reflects the number of episodes in the response,
            # so a small limit makes the count meaningless. Request the adapter max
            # (1000) and report that count; if it equals the cap, report it as ">= ".
            result = await _make_request(f"/memory/users/{quote(uid, safe='')}/episodes?limit=1000")

            total = result.get("total", 0)
            try:
                total = int(total)
            except (TypeError, ValueError):
                total = len(result.get("episodes", []) or [])
            capped = total >= 1000
            shown = f">= {total} (capped at 1000)" if capped else str(total)

            return f"# User Statistics: {uid}\n\n- **Total Episodes**: {shown}"

        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="graphiti_recall_context",
        annotations={
            "title": "Recall Memory Context",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def graphiti_recall_context(params: RecallContextInput) -> str:
        """Retrieve relevant memories and format them as context for the current conversation.

        Use this tool BEFORE responding to a user to recall what you know about them.
        The returned block should be prepended to your response context.
        """
        try:
            user_id = _resolve_user_id(params.user_id)
            payload = {
                "user_id": user_id,
                "query": params.query,
                "limit": params.limit
            }

            result = await _make_request("/memory/query", method="POST", json=payload)
            hits = result.get("hits", [])

            if not hits:
                return f"## Memory Recall: {user_id}\n\nNo relevant memories found."

            lines = [f"## Memory Recall: {user_id}", ""]
            lines.append("Relevant facts from long-term memory:")
            lines.append("")

            for hit in hits:
                fact = hit.get('fact', 'N/A')
                score = hit.get('score', 0)
                date = hit.get('created_at', 'N/A')
                lines.append(f"- {fact} (confidence: {score:.0%}, from: {date})")

            lines.append("")
            lines.append("Use these facts to personalize your response to the user.")

            return "\n".join(lines)

        except Exception as e:
            return _handle_error(e)


else:
    # -----------------------------------------------------------------------
    # code profile: pinned scope, typed writes, read-only lookup, no deletes
    # -----------------------------------------------------------------------

    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


    @mcp.tool(
        name="code_recall",
        annotations={
            "title": "Recall Project / Coding Memory",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False
        }
    )
    async def code_recall(query: str, limit: int = 10) -> str:
        """Search long-term memory of past coding and infrastructure work.

        Call this at the start of a session, and whenever the user says things like
        "посмотри в graphiti", "посмотри в памяти", "мы с hermes делали ...",
        "я правил код с другим ИИ", "что мы решали по <проект>".
        """
        try:
            payload = {"user_id": SCOPE, "query": query, "limit": max(1, min(int(limit), 50))}
            result = await _make_request("/memory/query", method="POST", json=payload)
            hits = result.get("hits", [])
            if not hits:
                return f"# Memory: nothing found for '{query}'"
            lines = [f"# Memory: '{query}'", ""]
            for hit in hits:
                lines.append(
                    f"- {hit.get('fact', 'N/A')} _(score {hit.get('score', 0):.2f}, {hit.get('created_at', 'N/A')})_"
                )
            return "\n".join(lines)
        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="code_append_request",
        annotations={
            "title": "Save User Request",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def code_append_request(project: str, request: str, context: str = "") -> str:
        """Save a USER REQUEST about code or infrastructure, as verbatim as possible.

        Only the request itself and its context — never tool output, commands,
        stack traces, diffs or step-by-step logs. One episode per task, not per step.
        """
        try:
            text = (
                f"[code] {_today()} | проект: {project} | тип: request\n"
                f"Запрос: {request}\n"
                f"Контекст: {context or '—'}"
            )
            metadata = {"source": "opencode", "kind": "request", "project": project}
            result = await _append(SCOPE, text, "user", metadata)
            return _append_ack(SCOPE, result)
        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="code_append_result",
        annotations={
            "title": "Save Work Result",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def code_append_result(project: str, done: str, verified: str = "", decisions: str = "", left: str = "") -> str:
        """Save the RESULT of work: what was done, how it was verified, decisions, what is left.

        Text only — no tool output, no commands, no diffs, no logs. Must be
        self-contained: another agent reading it should understand what was asked
        and what came out of it.
        """
        try:
            text = (
                f"[code] {_today()} | проект: {project} | тип: result\n"
                f"Сделано: {done}\n"
                f"Проверено: {verified or '—'}\n"
                f"Решения: {decisions or '—'}\n"
                f"Осталось: {left or '—'}"
            )
            metadata = {"source": "opencode", "kind": "result", "project": project}
            result = await _append(SCOPE, text, "assistant", metadata)
            return _append_ack(SCOPE, result)
        except Exception as e:
            return _handle_error(e)


    @mcp.tool(
        name="code_append_project",
        annotations={
            "title": "Save Project Description",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False
        }
    )
    async def code_append_project(project: str, description: str, status: str = "") -> str:
        """Save or update a PROJECT DESCRIPTION: what it is, stack, where it lives, current state.

        Before saving, call code_recall for the project name. If a description already
        exists, save only what changed (delta), not a second full version.
        """
        try:
            text = (
                f"[code] {_today()} | проект: {project} | тип: project\n"
                f"Описание: {description}\n"
                f"Состояние: {status or '—'}"
            )
            metadata = {"source": "opencode", "kind": "project", "project": project}
            result = await _append(SCOPE, text, "system", metadata)
            return _append_ack(SCOPE, result)
        except Exception as e:
            return _handle_error(e)


if __name__ == "__main__":
    if "--server" in sys.argv[1:]:
        import uvicorn

        logger.info(
            "Graphiti MCP over streamable HTTP on %s:%s (profile=%s, scope=%s)",
            MCP_SERVER_HOST, MCP_SERVER_PORT, PROFILE, PINNED_USER_ID or "<per-request>"
        )
        uvicorn.run(
            mcp.streamable_http_app(),
            host=MCP_SERVER_HOST,
            port=MCP_SERVER_PORT,
            log_level="info"
        )
    else:
        mcp.run()
