import logging
from app.services.embeddings import embedding_service
from app.services.graphiti_client import graphiti_client
# In a real worker, we might need to re-initialize these if they rely on event loops or specific context
# For RQ, simple function imports work if they are self-contained.

logger = logging.getLogger(__name__)

async def process_episode(user_id: str, text: str, metadata: dict):
    """
    Background task to process a new episode:
    1. Generate embeddings (if not handled by Graphiti internally)
    2. Extract entities (LLM call)
    3. Update Graphiti
    """
    logger.info(f"Processing episode for user {user_id}")
    
    # Example logic:
    # 1. Get embedding
    # embedding = await embedding_service.get_embedding(text)
    
    # 2. Add to Graphiti (if not already done synchronously)
    # Since the prompt says "Adapter returns ok synchronously... then asynchronously launches tasks",
    # we might move the actual Graphiti add here, OR just the enrichment.
    # For now, let's assume we do enrichment here.
    
    pass

async def reindex_user(user_id: str):
    logger.info(f"Reindexing user {user_id}")
    pass
