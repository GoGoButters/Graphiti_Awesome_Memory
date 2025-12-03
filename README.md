# Full-stack Graphiti Memory Platform

A production-ready dev setup for a Graphiti memory platform, featuring a FastAPI adapter, React Admin UI, and background worker.

## Architecture

- **Graphiti**: Python library for episodic/temporal knowledge graphs (integrated in Adapter and Worker).
- **Neo4j**: Graph database backend.
- **Adapter**: FastAPI service providing `append`, `query`, and `summary` endpoints.
- **Worker**: Redis + RQ background worker for async tasks.
- **Frontend**: React Admin UI for visualization and management.
- **Redis**: Message broker and cache.

## Features

- **Episodic Memory**: Store and retrieve user memories with temporal context.
- **Graph Visualization**: Interactive 3D knowledge graph with degree-based node coloring (Red=Top1, Yellow=Top2, Green=Top3, Blue=Others).
- **Admin Dashboard**: View user statistics, manage memories, and monitor system health.
- **Background Processing**: Async task queue for heavy operations.
- **Secure**: API Key authentication for API, JWT for Admin UI.

## Getting Started

### Prerequisites

- Docker and Docker Compose
- Python 3 with PyYAML (`pip3 install pyyaml` or `apt install python3-yaml`)
- OpenAI API Key (or compatible)

### Setup

1.  **Clone the repository** (if applicable).
2.  **Configure Environment**:
    The project uses a single `config.yml` as the source of truth.
    
    Edit `config.yml` and set your secrets:
    ```yaml
    # LLM Configuration
    llm:
      base_url: https://api.openai.com/v1
      api_key: sk-YOUR_LLM_KEY_HERE
      model: gpt-4o-mini
    
    # Embeddings Configuration
    embeddings:
      base_url: https://api.openai.com/v1
      api_key: sk-YOUR_EMBEDDING_KEY_HERE
      model: text-embedding-3-small
    
    # Reranker Configuration
    reranker:
      base_url: https://api.openai.com/v1
      api_key: sk-YOUR_RERANKER_KEY_HERE
      model: reranker-001
    
    # You can use the same API key for all three or different keys/providers
    # Each component (LLM, Embeddings, Reranker) has its own:
    # - base_url: API endpoint
    # - api_key: Authentication key
    # - model: Model name to use
    ```
    
3.  **Generate Environment Files**:
    ```bash
    make envs
    # OR
    bash scripts/generate_envs.sh
    ```

4.  **Start Services**:
    ```bash
    make up
    # OR
    docker-compose up -d --build
    ```

5.  **Access Services**:
    - **Adapter API**: http://localhost:8000/docs
    - **Admin UI**: http://localhost:3000
    - **Neo4j Browser**: http://localhost:7474 (User: neo4j, Password: from config)

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
  "episode_id": "user123_2025-12-01T12:00:00.000000+00:00",
  "status": "success"
}
```

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
  "results": [
    {
      "fact": "Alice likes robotics",
      "score": 0.95,
      "uuid": "edge-uuid-123",
      "created_at": "2025-12-01T12:00:00+00:00"
    }
  ],
  "total": 1
}
```

### Generate Summary
Create a summary of user's memories:
```bash
curl -X POST http://<SERVER_IP>:8000/memory/summary \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123"}'
```

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

- `GET /admin/users` - List all users with episode counts
- `GET /admin/users/{user_id}/graph` - Get user's knowledge graph
- `GET /admin/users/{user_id}/episodes?limit=N` - Get user episodes (admin)
- `DELETE /admin/users/{user_id}` - Delete user and all data
- `DELETE /admin/episodes/{episode_uuid}` - Delete specific episode

## Deployment on Ubuntu 24.04

These instructions assume you have a fresh Ubuntu 24.04 server.

### 1. Install Dependencies & Docker

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install prerequisites
sudo apt install -y curl git make python3-yaml

# Install Docker
curl -fsSL https://get.docker.com | sh

# Add your user to docker group (optional, to avoid sudo)
sudo usermod -aG docker $USER
newgrp docker

# Verify Docker is running
systemctl status docker
```

### 2. Clone & Configure

```bash
# Clone the repository
git clone https://github.com/GoGoButters/Graphiti_Awesome_Memory.git
cd Graphiti_Awesome_Memory

# Edit configuration with your actual API keys and passwords
nano config.yml
```

**Important:** Update the following in `config.yml`:
- `app.base_url` - Set to `http://<SERVER_IP>:8000` (e.g., `http://192.168.1.100:8000`)
- `app.admin_frontend_url` - Set to `http://<SERVER_IP>:3000`
- `llm.api_key` - Your LLM API key
- `embeddings.api_key` - Your embeddings API key
- `reranker.api_key` - Your reranker API key
- `neo4j.password` - Choose a secure password for Neo4j
- `adapter.api_key` - Choose a secure API key for the adapter
- `adapter.jwt_secret` - Choose a strong JWT secret
- `security.admin_password` - Choose a secure admin password

### 3. Start the Platform

```bash
# Generate environment files from config.yml
bash scripts/generate_envs.sh

# Start all services
docker compose up -d --build
```

### 4. Verification

Check if services are running:
```bash
docker compose ps
```

All services should show as "Up" or "healthy":
- **neo4j** - Graph database (healthy)
- **redis** - Message broker (Up)
- **adapter** - FastAPI backend (Up)
- **worker** - Background worker (Up)
- **frontend** - React UI (Up)

Access the services:
- **Adapter API**: `http://<SERVER_IP>:8000/docs`
- **Admin UI**: `http://<SERVER_IP>:3000`
- **Neo4j Browser**: `http://<SERVER_IP>:7474`

### Troubleshooting

**View logs:**
```bash
docker compose logs -f adapter
docker compose logs -f worker
docker compose logs -f frontend
```

**Restart services:**
```bash
docker compose restart
```

**Rebuild from scratch:**
```bash
docker compose down -v
docker compose up -d --build
```

## Development

### Directory Structure
- `backend/adapter`: FastAPI application.
- `worker`: Background worker.
- `frontend`: React Admin UI.
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
