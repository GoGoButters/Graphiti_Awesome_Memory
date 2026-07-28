# Graphiti MCP Server for OpenClaw

MCP server providing long-term memory for OpenClaw via the Graphiti platform.

## Installation

```bash
cd mcp_server && pip install -r requirements.txt
```

## OpenClaw Configuration

Add to your OpenClaw MCP config:

```json
{
  "mcpServers": {
    "graphiti-memory": {
      "command": "python3",
      "args": ["/path/to/graphiti/mcp_server/graphiti_mcp.py"],
      "env": {
        "GRAPHITI_API_BASE_URL": "http://YOUR_SERVER:8001",
        "GRAPHITI_API_KEY": "adapter-secret-api-key"
      }
    }
  }
}
```

## Tools

| Tool | Description |
|------|-------------|
| `graphiti_append_memory` | Add a new memory episode to a user's knowledge graph. Accepts user_id, text, role (user/assistant/system), and optional source. |
| `graphiti_query_memory` | Semantic search across a user's memories. Returns scored facts with timestamps. Supports markdown or JSON output. |
| `graphiti_get_episodes` | Retrieve the episode history for a specific user, with optional limit. |
| `graphiti_delete_file` | Delete all data associated with a specific file for a user. |
| `graphiti_get_user_stats` | Get statistics (episode count) for a user. |

## Environment Variables

- `GRAPHITI_API_BASE_URL` — Adapter API URL (default: http://localhost:8001)
- `GRAPHITI_API_KEY` — API key for authentication (default: adapter-secret-api-key)

## Usage within OpenClaw

Once configured, OpenClaw can use Graphiti as persistent memory:

- **Remembering**: Call `graphiti_append_memory` to store facts about users
- **Recalling**: Call `graphiti_query_memory` to retrieve relevant memories during conversations
- **Auditing**: Use `graphiti_get_episodes` to review what's been stored

The memory system uses a Neo4j knowledge graph with semantic embeddings for retrieval.
Facts extracted from text are linked as entities and relationships, enabling complex queries.