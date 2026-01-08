"""
Service for reprocessing episodes to rebuild knowledge graph
"""

import logging
from typing import Dict, Any
from app.services.graphiti_client import graphiti_client

logger = logging.getLogger(__name__)

class ReprocessingService:
    """Service to reprocess existing episodes and rebuild knowledge graph"""
    
    async def reprocess_user(self, user_id: str) -> Dict[str, Any]:
        """
        Reprocess all episodes for a specific user
        
        Args:
            user_id: User identifier
            
        Returns:
            Statistics about reprocessing
        """
        try:
            driver = graphiti_client.client.driver
            
            # Get all episodes for this user
            query = """
            MATCH (e:Episodic)
            WHERE e.name STARTS WITH $user_prefix
            RETURN e.uuid as uuid, e.content as content, e.created_at as created_at, 
                   e.source as source, e.file_name as file_name
            ORDER BY e.created_at ASC
            """
            
            result = await driver.execute_query(
                query,
                user_prefix=f"{user_id}_",
                database_="neo4j"
            )
            
            episodes = result.records
            total = len(episodes)
            processed = 0
            errors = 0
            
            logger.info(f"Starting reprocessing {total} episodes for user {user_id}")
            
            # Delete all old episodes first (they will be recreated by add_episode)
            delete_query = """
            MATCH (e:Episodic)
            WHERE e.name STARTS WITH $user_prefix
            DELETE e
            """
            await driver.execute_query(
                delete_query,
                user_prefix=f"{user_id}_",
                database_="neo4j"
            )
            logger.info(f"Deleted {total} old episodes for user {user_id}")
            
            # Process each episode
            for i, episode in enumerate(episodes):
                try:
                    logger.info(f"Reprocessing episode {i+1}/{total} for user {user_id}")
                    
                    # Use the existing add_episode method which will:
                    # 1. Create new Episodic node
                    # 2. Extract entities with LLM
                    # 3. Create Entity nodes and relationships
                    metadata = {}
                    if episode.get('file_name'):
                        metadata['file_name'] = episode['file_name']
                    if episode.get('source'):
                        metadata['source'] = episode['source']
                    
                    await graphiti_client.add_episode(
                        user_id=user_id,
                        text=episode['content'],
                        metadata=metadata
                    )
                    
                    processed += 1
                    
                except Exception as e:
                    logger.error(f"Error reprocessing episode {episode['uuid']}: {e}")
                    errors += 1
                    # Continue with next episode
            
            logger.info(f"Reprocessing complete for user {user_id}: {processed} processed, {errors} errors")
            
            return {
                "user_id": user_id,
                "total_episodes": total,
                "processed": processed,
                "errors": errors
            }
            
        except Exception as e:
            logger.error(f"Error reprocessing user {user_id}: {e}", exc_info=True)
            raise
    
    async def reprocess_all_users(self) -> Dict[str, Any]:
        """
        Reprocess episodes for all users
        
        Returns:
            Overall statistics
        """
        try:
            driver = graphiti_client.client.driver
            
            # Get all unique user IDs from episodes
            query = """
            MATCH (e:Episodic)
            WHERE e.name IS NOT NULL
            WITH split(e.name, '_')[0] as user_id
            RETURN DISTINCT user_id
            ORDER BY user_id
            """
            
            result = await driver.execute_query(
                query,
                database_="neo4j"
            )
            
            user_ids = [r['user_id'] for r in result.records]
            total_users = len(user_ids)
            
            logger.info(f"Starting reprocessing for {total_users} users")
            
            results = []
            for i, user_id in enumerate(user_ids):
                logger.info(f"Processing user {i+1}/{total_users}: {user_id}")
                user_result = await self.reprocess_user(user_id)
                results.append(user_result)
            
            # Calculate totals
            total_episodes = sum(r['total_episodes'] for r in results)
            total_processed = sum(r['processed'] for r in results)
            total_errors = sum(r['errors'] for r in results)
            
            return {
                "total_users": total_users,
                "total_episodes": total_episodes,
                "processed": total_processed,
                "errors": total_errors,
                "users": results
            }
            
        except Exception as e:
            logger.error(f"Error reprocessing all users: {e}", exc_info=True)
            raise

reprocessing_service = ReprocessingService()
