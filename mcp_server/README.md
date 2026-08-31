# Graphiti MCP Server

MCP server for Graphiti episodic memory platform.

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### stdio mode (default)
```bash
python graphiti_mcp.py
```

### HTTP server mode
```bash
python graphiti_mcp.py --server
```

## Environment Variables

- `GRAPHITI_API_BASE_URL` - Adapter API URL (default: http://localhost:8000)
- `GRAPHITI_API_KEY` - API key (default: adapter-secret-api-key)

## Tools

| Tool | Description |
|------|-------------|
| `graphiti_append_memory` | Add memory to user's knowledge graph |
| `graphiti_query_memory` | Semantic search across user memories |
| `graphiti_get_episodes` | Get user episode history |
| `graphiti_delete_file` | Delete file data |
| `graphiti_get_user_stats` | Get user statistics |

## Docker

```bash
docker build -t graphiti-mcp mcp_server/
docker run -p 8000:8000 -e GRAPHITI_API_BASE_URL=http://adapter:8000 graphiti-mcp
```
