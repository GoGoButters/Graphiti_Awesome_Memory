# Full-stack Graphiti Memory Platform

A production-ready dev setup for a Graphiti memory platform, featuring a FastAPI adapter, React Admin UI, and background worker.

## Architecture

- **Graphiti**: Episodic/temporal knowledge graph service.
- **Neo4j**: Graph database backend.
- **Adapter**: FastAPI service providing `append`, `query`, and `summary` endpoints.
- **Worker**: Redis + RQ background worker for async tasks.
- **Frontend**: React Admin UI for visualization and management.
- **Redis**: Message broker and cache.

## Getting Started

### Prerequisites

- Docker and Docker Compose
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
curl -X POST http://localhost:8000/memory/append \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","text":"My name is Alice. I like robotics.","role":"user","metadata":{"source":"n8n"}}'
```

### Query Memory
```bash
curl -X POST http://localhost:8000/memory/query \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: adapter-secret-api-key" \
  -d '{"user_id":"user123","query":"What does Alice like?","limit":5}'
```

## Deployment on Ubuntu 24.04 LXC

These instructions assume you have a fresh Ubuntu 24.04 LXC container.

### 1. Install Dependencies & Docker

Run the following commands inside your LXC container:

```bash
# Update system
apt update && apt upgrade -y

# Install prerequisites
apt install -y curl git make

# Install Docker
curl -fsSL https://get.docker.com | sh

# Verify Docker is running
systemctl status docker
```

### 2. Clone & Configure

```bash
# Clone the repository
git clone https://github.com/GoGoButters/Graphiti_n8n_Agent.git
cd Graphiti_n8n_Agent

# Create configuration
# Copy the example config or create your own
cp config.yml.example config.yml # (If you have an example, otherwise just edit config.yml)
# EDIT config.yml with your actual keys!
nano config.yml
```

### 3. Start the Platform

```bash
# Generate environment files
bash scripts/generate_envs.sh

# Start services
docker compose up -d --build
```

### 4. Verification

Check if services are running:
```bash
docker compose ps
```

- **Adapter**: `http://<LXC_IP>:8000/docs`
- **Admin UI**: `http://<LXC_IP>:3000`

**Note**: If accessing from outside the LXC host, ensure you use the container's IP address instead of `localhost`.

## Development

### Directory Structure
- `backend/adapter`: FastAPI application.
- `worker`: Background worker.
- `frontend`: React Admin UI.
- `graphiti`: Graphiti configuration.
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
