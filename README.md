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

### Append Memory
```bash
curl -X POST http://<VM_IP>:8000/memory/append \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","text":"My name is Alice. I like robotics.","role":"user","metadata":{"source":"n8n"}}'
```

### Query Memory
```bash
curl -X POST http://<VM_IP>:8000/memory/query \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","query":"What does Alice like?","limit":5}'
```

## Deployment on Ubuntu 24.04 VM

These instructions assume you have a fresh Ubuntu 24.04 Virtual Machine (e.g., on Proxmox, VirtualBox, VMware).

**Note:** Docker in VMs works much better than in LXC containers due to full kernel isolation. VMs avoid common issues with BuildKit, overlayfs, and sysctl.

### 1. Install Dependencies & Docker

Run the following commands inside your VM:

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
- **Adapter API**: `http://<VM_IP>:8000/docs`
- **Admin UI**: `http://<VM_IP>:3000`
- **Neo4j Browser**: `http://<VM_IP>:7474`

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
