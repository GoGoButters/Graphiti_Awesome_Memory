<div align="center">
  <img src="logo.png" alt="Graphiti Logo" width="400"/>

# Full-stack Graphiti Memory Platform

</div>

A production-ready dev setup for a Graphiti memory platform, featuring a FastAPI adapter, React Admin UI, and background worker.

## Architecture

- **Graphiti**: Python framework for episodic/temporal knowledge graphs (integrated in Adapter and Worker).
- **Neo4j**: Graph database backend.
- **Adapter**: FastAPI service providing `append`, `query`, and `summary` endpoints.
- **Worker**: Redis + RQ background worker for async tasks.
- **MCP Server**: OpenClaw/Claude integration via stdio transport for long-term memory.
- **Frontend**: React Admin UI for visualization and management.
- **Redis**: Message broker and cache.

## Features

- **Episodic Memory**: Store and retrieve user memories with temporal context.
- **Graph Visualization**: Interactive 3D knowledge graph with degree-based node coloring (Red=Top1, Yellow=Top2, Green=Top3, Blue=Others).
- **Admin Dashboard**: View user statistics, manage memories, and monitor system health.
- **Background Processing**: Async task queue for heavy operations.
- **Secure**: API Key authentication for API, JWT for Admin UI.
- **OpenClaw MCP Ready**: 6 MCP tools for AI agents — memory append, query, recall context injection, episodes, stats, file cleanup.
- **Memory Summarization**: Automatic summary generation with LLM (falls back to structured extraction if LLM unavailable).

## Quick Setup

### 1. Clone & Configure

```bash
git clone https://github.com/GoGoButters/Graphiti_Awesome_Memory.git
cd Graphiti_Awesome_Memory

# Configure secrets
nano config.yml
```

Update `config.yml` with your API keys (LLM, Embeddings, Neo4j, etc.).

### 2. Start Services

```bash
# Generate env files and start Docker containers
bash scripts/generate_envs.sh
docker compose up -d --build
```

That's it! Services will be available at:

- **Adapter API**: <http://localhost:8000/docs>
- **Admin UI**: <http://localhost:3000>
- **Neo4j Browser**: <http://localhost:7474>

Ports are configurable via `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `ADAPTER_PORT` | 8000 | Adapter API port |
| `FRONTEND_PORT` | 3000 | Admin UI port |
| `NEO4J_HTTP_PORT` | 7474 | Neo4j Browser port |
| `NEO4J_BOLT_PORT` | 7687 | Neo4j Bolt port |
| `REDIS_PORT` | 6379 | Redis port |

## API Usage

All API endpoints use `X-API-KEY` header for authentication (default: `adapter-secret-api-key`).

### Append Memory

Add a new memory episode for a user:

```bash
curl -X POST http://<SERVER_IP>:8000/memory/append \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","text":"My name is Alice. I like robotics.","role":"user","metadata":{"source":"n8n"}}'
```

**Response:**

```json
{
  "ok": true,
  "id": "f3e92aaa-a6a9-4218-b8d6-6be7253925b7",
  "created_ts": "2025-12-01T12:00:00.000000Z"
}
```

#### With File Metadata (Document RAG)

This feature is designed for **Document RAG** scenarios where you use an **external text extractor and chunking** (e.g., n8n, LangChain). By passing `file_name`, you link multiple chunks to a single source document.

```bash
curl -X POST http://<SERVER_IP>:8000/memory/append \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{
    "user_id":"user123",
    "text":"Chunk #1 content...",
    "metadata":{
      "source":"n8n",
      "file_name":"report_2024.pdf"
    }
  }'
```

This allows for bulk deletion of all chunks belonging to this file later.

### Query Memory

Search user's memories using semantic search:

```bash
curl -X POST http://<SERVER_IP>:8000/memory/query \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","query":"What does Alice like?","limit":5}'
```

**Response:**

```json
{
  "hits": [
    {
      "fact": "Alice likes robotics",
      "score": 0.95,
      "uuid": "edge-uuid-123",
      "created_at": "2025-12-01T12:00:00+00:00",
      "metadata": {
        "file_name": null
      }
    }
  ],
  "total": 1
}
```

### Query Memory (Grouped by Source)

Search user's memories and get results grouped by source (files vs conversation):

```bash
curl -X POST http://<SERVER_IP>:8000/memory/query/grouped \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","query":"What medical tests were done?","limit":10}'
```

**Response:**

```json
{
  "groups": [
    {
      "source_type": "file",
      "source_name": "mri_results.pdf",
      "facts": [
        {"fact": "MRI shows dystrophic changes...", "score": 0.95, ...}
      ]
    },
    {
      "source_type": "conversation",
      "source_name": null,
      "facts": [
        {"fact": "User mentioned headaches...", "score": 0.85, ...}
      ]
    }
  ],
  "total_facts": 5
}
```

This endpoint is useful for AI agents that need to understand where each fact came from.

### Generate Summary

Create a summary of user's memories:

```bash
curl -X POST http://<SERVER_IP>:8000/memory/summary \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123"}'
```

**Response (LLM available):**
```json
{"summary": "Alice is a robotics engineer living in Berlin..."}
```

**Response (fallback — LLM unavailable):**
```
Memory Summary for alice

Total episodes: 3
Sources: chat, n8n

Recent memories:
- My name is Alice. I like robotics....
- I live in Berlin and work as an engineer....
```

### Delete File (Bulk Cleanup)

Delete all episodes and orphaned entities associated with a specific file:

```bash
curl -X DELETE "http://<SERVER_IP>:8000/memory/files?user_id=user123&file_name=report_2024.pdf" \
  -H "X-API-KEY: adapter-secret-api-key"
```

This is useful for re-indexing documents or removing outdated knowledge.

### Get User Episodes

Retrieve user's recent episodes with optional limit:

```bash
curl -H "X-API-KEY: adapter-secret-api-key" \
  "http://<SERVER_IP>:8000/memory/users/user123/episodes?limit=10"
```

**Response:**

```json
{
  "episodes": [
    {
      "created_at": "2025-12-01T12:00:00+00:00",
      "source": "n8n (user)",
      "content": "My name is Alice. I like robotics."
    }
  ],
  "total": 1
}
```

### Admin Endpoints (JWT Authentication)

Admin endpoints require JWT token obtained by logging into the Admin UI at `http://<SERVER_IP>:3000`.

#### User Management

- `GET /admin/users` - List all users with episode counts
- `GET /admin/users/{user_id}/graph` - Get user's knowledge graph
- `GET /admin/users/{user_id}/episodes?limit=N` - Get user episodes (admin)
- `DELETE /admin/users/{user_id}` - Delete user and all data

#### File Management

- `GET /admin/users/{user_id}/files` - List user files and chunk counts
- `DELETE /admin/users/{user_id}/files?file_name=...` - Delete all chunks for a file
- `DELETE /admin/episodes/{episode_uuid}` - Delete specific episode

#### Backup & Restore

- `GET /admin/users/{user_id}/backup` - Create and download backup (`.tar.gz` with episodes, entities, edges)
- `POST /admin/users/restore` - Upload and restore backup file
  - Supports restoring to different user ID
  - **Safe MERGE mode** - never deletes existing data, only adds/updates
  - Handles UTF-8 properly for all languages

#### Reprocessing (Graph Rebuild)

- `POST /admin/reprocess/{user_id}` - Reprocess episodes to rebuild Entity nodes
- `POST /admin/reprocess-all` - Reprocess all users
  - **Safe mode** - does NOT delete episodes, only creates Entity nodes
  - Useful after Graphiti updates or to fix missing graph data
  - May create duplicate episodes (can be cleaned later if needed)

## OpenClaw MCP Integration

Graphiti ships with a ready-to-use MCP server for OpenClaw and Claude Desktop.

### Configuration

Add to your OpenClaw MCP config:

```json
{
  "mcpServers": {
    "graphiti-memory": {
      "command": "python3",
      "args": ["mcp_server/graphiti_mcp.py"],
      "env": {
        "GRAPHITI_API_BASE_URL": "http://localhost:8000",
        "GRAPHITI_API_KEY": "adapter-secret-api-key"
      }
    }
  }
}
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `graphiti_append_memory` | Store a fact in the user's knowledge graph |
| `graphiti_query_memory` | Semantic search across user memories |
| `graphiti_recall_context` | Retrieve relevant memories formatted as conversation context |
| `graphiti_get_episodes` | View episode history for a user |
| `graphiti_get_user_stats` | Get memory statistics for a user |
| `graphiti_delete_file` | Delete all facts from a source file |

### How It Works

1. **Before responding**: OpenClaw calls `graphiti_recall_context` with the user's query
2. **Memory injection**: Relevant facts are injected into the agent's context
3. **After responding**: OpenClaw saves important new facts via `graphiti_append_memory`
4. **Across sessions**: Facts persist in Neo4j and are retrieved via semantic search

See `mcp_server/system_prompt.md` for the full OpenClaw system prompt.

## Performance Optimization

### Dual-Model Strategy

The platform uses a **dual-model strategy** for optimal performance:

- **Main LLM** (`llm`): Used for high-quality fact extraction (20% of operations)
- **Fast LLM** (`llm_fast`): Used for simple operations like deduplication and validation (80% of operations)

This provides **5-10x speedup** without sacrificing accuracy.

#### Configuration

Configure both models in `config.yml`:

```yaml
llm:
  base_url: http://your-server:4000/v1
  api_key: your-key
  model: qwen2.5-32b-instruct  # Reasoning model for quality

llm_fast:
  base_url: http://your-server:4000/v1
  api_key: your-key
  model: qwen2.5:7b  # Fast non-reasoning model

# Optional: Reranker for improved search relevance
reranker:
  base_url: http://your-reranker:8080/v1
  api_key: your-key
  model: jina-reranker-v2
```

#### Concurrency Tuning

The platform supports up to 100 concurrent LLM operations (default: 10). This is configured via `SEMAPHORE_LIMIT` in `docker-compose.yml`.

For local LLM servers that support high concurrency, you can increase this limit:

```yaml
environment:
  - SEMAPHORE_LIMIT=100  # Increase for faster processing
```

**Recommendation**: Start with 50-100 for local servers, 10-20 for API providers with rate limits.

## Development

### Directory Structure

- `backend/adapter`: FastAPI application.
- `worker`: Background worker.
- `frontend`: React Admin UI.
- `mcp_server`: OpenClaw/Claude MCP integration.
- `infra`: Infrastructure config (Nginx).

### Running Tests

```bash
make test
```

## Security Notes

- **Secrets**: In production, use a secret manager (Vault, K8s Secrets) instead of `.env` files.
- **Auth**:
  - Adapter uses API Key (`X-API-KEY`).
  - Admin UI uses JWT (Login with credentials from `config.yml`).
- **Network**: Ensure Neo4j and Redis ports are not exposed to the public internet in production.

## Support the Project

If you find this project useful, consider supporting its development with a donation:

- **USDT (ERC20)**: `0xd91e775b3636f2be35d85252d8a17550c0f869a6`
- **Bitcoin**: `3Eaa654UHa7GZnKTpYr5Nt2UG5XoUcKXgx`
- **Ethereum (ERC20)**: `0x4dbf76b16b9de343ff17b88963d114f8155a2df0`
- **Tron (TRX)**: `TT9gPkor4QoR9c12x8HLbvCLeNcS9KDutc`

Your support helps maintain and improve this project. Thank you! 🙏

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=GoGoButters/Graphiti_Awesome_Memory&type=Date)](https://star-history.com/#GoGoButters/Graphiti_Awesome_Memory&Date)
