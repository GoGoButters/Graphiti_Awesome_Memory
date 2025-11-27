#!/bin/bash
set -e

# Ensure we are in the project root
cd "$(dirname "$0")/.."

CONFIG_FILE="config.yml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: $CONFIG_FILE not found!"
    exit 1
fi

# Function to read a value from config.yml
# Usage: get_config_value "key.path"
get_config_value() {
    # Simple grep/sed based parser for this specific flat-ish yaml structure.
    # For robust parsing, yq is better, but we want to avoid dependencies.
    # This assumes "  key: value" format.
    local key=$1
    local parent=${key%.*}
    local child=${key##*.}
    
    # This is a very naive parser. For a real production setup, use python or yq.
    # Since we have python in the environment, let's use a tiny python script.
    python3 -c "
import yaml
import sys

try:
    with open('$CONFIG_FILE', 'r') as f:
        config = yaml.safe_load(f)
    
    keys = '$key'.split('.')
    val = config
    for k in keys:
        val = val[k]
    print(val)
except Exception as e:
    print('', file=sys.stderr)
"
}

echo "Generating .env files..."

# Read values
NEO4J_URI=$(get_config_value "neo4j.uri")
NEO4J_USER=$(get_config_value "neo4j.user")
NEO4J_PASSWORD=$(get_config_value "neo4j.password")
GRAPHITI_URL=$(get_config_value "graphiti.rest_base_url")
GRAPHITI_USE_SDK=$(get_config_value "graphiti.use_sdk")
REDIS_URL=$(get_config_value "redis.url")
OPENAI_BASE_URL=$(get_config_value "openai.base_url")
OPENAI_API_KEY=$(get_config_value "openai.api_key")
LLM_MODEL=$(get_config_value "openai.models.llm")
EMBEDDING_MODEL=$(get_config_value "openai.models.embedding")
ADAPTER_API_KEY=$(get_config_value "adapter.api_key")
JWT_SECRET=$(get_config_value "adapter.jwt_secret")
ADMIN_USERNAME=$(get_config_value "security.admin_username")
ADMIN_PASSWORD=$(get_config_value "security.admin_password")
ADMIN_FRONTEND_URL=$(get_config_value "app.admin_frontend_url")

# .env.adapter
cat > .env.adapter <<EOF
NEO4J_URI=$NEO4J_URI
NEO4J_USER=$NEO4J_USER
NEO4J_PASSWORD=$NEO4J_PASSWORD
GRAPHITI_URL=$GRAPHITI_URL
GRAPHITI_USE_SDK=$GRAPHITI_USE_SDK
REDIS_URL=$REDIS_URL
OPENAI_BASE_URL=$OPENAI_BASE_URL
OPENAI_API_KEY=$OPENAI_API_KEY
LLM_MODEL=$LLM_MODEL
EMBEDDING_MODEL=$EMBEDDING_MODEL
ADAPTER_API_KEY=$ADAPTER_API_KEY
JWT_SECRET=$JWT_SECRET
ADMIN_USERNAME=$ADMIN_USERNAME
ADMIN_PASSWORD=$ADMIN_PASSWORD
ALLOWED_ORIGINS=$ADMIN_FRONTEND_URL
EOF
echo "Created .env.adapter"

# .env.worker
cp .env.adapter .env.worker
echo "Created .env.worker"

# .env.graphiti (if needed)
cat > .env.graphiti <<EOF
NEO4J_URI=$NEO4J_URI
NEO4J_USER=$NEO4J_USER
NEO4J_PASSWORD=$NEO4J_PASSWORD
OPENAI_API_KEY=$OPENAI_API_KEY
OPENAI_BASE_URL=$OPENAI_BASE_URL
PORT=3000
EOF
echo "Created .env.graphiti"

# .env.frontend
# Note: Vite requires VITE_ prefix
ADAPTER_BASE_URL=$(get_config_value "app.base_url")
cat > frontend/.env <<EOF
VITE_API_BASE_URL=$ADAPTER_BASE_URL
EOF
echo "Created frontend/.env"

echo "Done."
