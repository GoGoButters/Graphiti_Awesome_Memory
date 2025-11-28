"""
Graphiti Client Wrapper - Real SDK Integration

This module provides a wrapper around the graphiti-core Python SDK for
building and querying temporal knowledge graphs.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF

from app.core.config import settings
from app.models.schemas import MemoryHit

logger = logging.getLogger(__name__)


class GraphitiWrapper:
    """
    Wrapper for Graphiti SDK that integrates with Neo4j.
    Handles episode creation, search, and graph retrieval.
    """
    
    def __init__(self):
        """Initialize Graphiti client with Neo4j connection"""
        try:
            self.client = Graphiti(
                settings.NEO4J_URI,
                settings.NEO4J_USER,
                settings.NEO4J_PASSWORD
            )
            logger.info(f"Graphiti client initialized with Neo4j at {settings.NEO4J_URI}")
        except Exception as e:
            logger.error(f"Failed to initialize Graphiti client: {e}")
            raise

    async def add_episode(
        self,
        user_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add an episode (memory) to the knowledge graph
        
        Args:
            user_id: Unique identifier for the user
            text: Text content of the episode
            metadata: Optional metadata (role, source, etc.)
            
        Returns:
            Episode ID/UUID
        """
        try:
            # Create unique episode name
            timestamp = datetime.now(timezone.utc).isoformat()
            episode_name = f"{user_id}_{timestamp}"
            
            # Extract source from metadata
            source_description = metadata.get("source", "api") if metadata else "api"
            role = metadata.get("role", "user") if metadata else "user"
            
            logger.info(f"Adding episode for user {user_id}: {text[:50]}...")
            
            # Add episode to Graphiti
            await self.client.add_episode(
                name=episode_name,
                episode_body=text,
                source=EpisodeType.text,
                source_description=f"{source_description} ({role})",
                reference_time=datetime.now(timezone.utc)
            )
            
            logger.info(f"Successfully added episode: {episode_name}")
            return episode_name
            
        except Exception as e:
            logger.error(f"Error adding episode: {e}")
            raise

    async def search(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        center_node_uuid: Optional[str] = None
    ) -> List[MemoryHit]:
        """
        Search for relevant memories (edges) in the knowledge graph
        
        Args:
            user_id: User identifier (for filtering if needed)
            query: Search query
            limit: Maximum number of results
            center_node_uuid: Optional UUID for graph-distance reranking
            
        Returns:
            List of MemoryHit objects
        """
        try:
            logger.info(f"Searching for user {user_id}: {query}")
            
            # Perform hybrid search (semantic + BM25)
            results = await self.client.search(
                query=query,
                center_node_uuid=center_node_uuid
            )
            
            # Convert to MemoryHit format
            hits = []
            for result in results[:limit]:
                hit = MemoryHit(
                    fact=result.fact,
                    score=getattr(result, 'score', 1.0),
                    uuid=result.uuid,
                    created_at=getattr(result, 'created_at', datetime.now(timezone.utc)),
                    metadata={
                        "source_node_uuid": getattr(result, 'source_node_uuid', None),
                        "target_node_uuid": getattr(result, 'target_node_uuid', None),
                        "valid_at": str(result.valid_at) if hasattr(result, 'valid_at') and result.valid_at else None,
                        "invalid_at": str(result.invalid_at) if hasattr(result, 'invalid_at') and result.invalid_at else None,
                    }
                )
                hits.append(hit)
            
            logger.info(f"Found {len(hits)} results for query: {query}")
            return hits
            
        except Exception as e:
            logger.error(f"Error searching: {e}")
            return []

    async def get_user_graph(self, user_id: str) -> Dict[str, Any]:
        """
        Get the knowledge graph for a specific user
        
        Args:
            user_id: User identifier
            
        Returns:
            Graph structure with nodes and edges
        """
        try:
            logger.info(f"Getting graph for user {user_id}")
            
            # Search for nodes related to this user
            node_search_config = NODE_HYBRID_SEARCH_RRF.model_copy(deep=True)
            node_search_config.limit = 100
            
            search_results = await self.client._search(
                query=user_id,
                config=node_search_config
            )
            
            # Convert to Cytoscape.js format
            nodes = []
            edges = []
            
            for node in search_results.nodes:
                nodes.append({
                    "data": {
                        "id": node.uuid,
                        "label": node.name,
                        "summary": node.summary[:200] if node.summary else "",
                        "created_at": str(node.created_at) if node.created_at else None,
                    }
                })
            
            for edge in search_results.edges:
                edges.append({
                    "data": {
                        "id": edge.uuid,
                        "source": edge.source_node_uuid,
                        "target": edge.target_node_uuid,
                        "label": edge.fact[:100] if edge.fact else "",
                    }
                })
            
            logger.info(f"Retrieved {len(nodes)} nodes and {len(edges)} edges")
            
            return {
                "nodes": nodes,
                "edges": edges
            }
            
        except Exception as e:
            logger.error(f"Error getting user graph: {e}")
            return {"nodes": [], "edges": []}

    async def get_summary(self, user_id: str) -> str:
        """
        Generate a summary of user's knowledge graph
        
        Args:
            user_id: User identifier
            
        Returns:
            Text summary
        """
        try:
            # Search for user-related facts
            results = await self.search(user_id, f"facts about {user_id}", limit=10)
            
            if not results:
                return f"No information found for user {user_id}"
            
            # Build summary from top facts
            summary_parts = [f"Knowledge summary for {user_id}:"]
            for i, hit in enumerate(results[:5], 1):
                summary_parts.append(f"{i}. {hit.fact}")
            
            return "\n".join(summary_parts)
            
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return f"Error generating summary: {str(e)}"
    
    async def close(self):
        """Close the Graphiti client connection"""
        try:
            await self.client.close()
            logger.info("Graphiti client connection closed")
        except Exception as e:
            logger.error(f"Error closing Graphiti client: {e}")


# Global Graphiti client instance
graphiti_client = GraphitiWrapper()
