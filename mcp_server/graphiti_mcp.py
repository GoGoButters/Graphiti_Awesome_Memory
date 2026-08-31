#!/usr/bin/env python3
"""
MCP Server for Graphiti Memory Platform.

This server provides tools to interact with the Graphiti episodic memory system,
including memory append, query, and management capabilities.
"""

import os
import logging
from typing import Optional, List, Dict, Any
from enum import Enum

import httpx
from pydantic import BaseModel, Field, field_validator, ConfigDict
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("graphiti_mcp")

API_BASE_URL = os.getenv("GRAPHITI_API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("GRAPHITI_API_KEY", "adapter-secret-api-key")
MCP_SERVER_PORT = int(os.getenv("MCP_SERVER_PORT", "8001"))


class ResponseFormat(str, Enum):
    MARKDOWN = "markdown"
    JSON = "json"


class MemoryAppendInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: str = Field(..., description="User identifier (e.g., 'user123', 'alice')", min_length=1, max_length=200)
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

    user_id: str = Field(..., description="User identifier", min_length=1, max_length=200)
    query: str = Field(..., description="Search query text", min_length=1, max_length=1000)
    limit: int = Field(default=10, description="Maximum results to return", ge=1, le=100)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN, description="Output format")


class GetEpisodesInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: str = Field(..., description="User identifier", min_length=1, max_length=200)
    limit: Optional[int] = Field(default=None, description="Maximum episodes to return", ge=1, le=1000)


class DeleteFileInput(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        validate_assignment=True
    )

    user_id: str = Field(..., description="User identifier", min_length=1, max_length=200)
    file_name: str = Field(..., description="File name to delete", min_length=1, max_length=500)


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
        metadata = {}
        if params.source:
            metadata["source"] = params.source
        
        payload = {
            "user_id": params.user_id,
            "text": params.text,
            "role": params.role,
            "metadata": metadata
        }
        
        result = await _make_request("/memory/append", method="POST", json=payload)
        
        return f"""# Memory Appended Successfully

- **User**: {params.user_id}
- **Episode ID**: {result.get('id', 'N/A')}
- **Timestamp**: {result.get('created_ts', 'N/A')}
- **Status**: {'Success' if result.get('ok') else 'Failed'}
"""

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
        payload = {
            "user_id": params.user_id,
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
            return f"# No memories found for '{params.query}'\n\nNo relevant memories found for user **{params.user_id}**."
        
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
        url = f"/memory/users/{params.user_id}/episodes"
        if params.limit:
            url += f"?limit={params.limit}"
        
        result = await _make_request(url)
        episodes = result.get("episodes", [])
        total = result.get("total", 0)
        
        if not episodes:
            return f"# No episodes for user **{params.user_id}**\n\nThis user has no memory records."
        
        lines = [f"# User Episodes: {params.user_id}", ""]
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
        url = f"/memory/files?user_id={params.user_id}&file_name={params.file_name}"
        
        result = await _make_request(url, method="DELETE")
        
        if result.get("ok"):
            return f"# File Deleted Successfully\n\n- **User**: {params.user_id}\n- **File**: {params.file_name}\n- **Status**: Deleted"
        
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
async def graphiti_get_user_stats(user_id: str) -> str:
    """Get statistics for a user."""
    try:
        result = await _make_request(f"/memory/users/{user_id}/episodes?limit=1")
        
        total = result.get("total", 0)
        
        return f"# User Statistics: {user_id}\n\n- **Total Episodes**: {total}"

    except Exception as e:
        return _handle_error(e)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--server":
        import uvicorn
        from mcp.server.fastmcp import FastMCP
        mcp = FastMCP("graphiti_mcp")
        # Re-register tools - they use closure, need to be re-created
        # Actually run differently - use uvicorn directly
        uvicorn.run(
            "graphiti_mcp:mcp",
            host="0.0.0.0",
            port=MCP_SERVER_PORT,
            reload=False
        )
    else:
        mcp.run()
