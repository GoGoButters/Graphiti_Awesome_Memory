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

# Global monkey patch for json.loads to clean LLM responses
import json
import re

_original_json_loads = json.loads

def _patched_json_loads(s, *args, **kwargs):
    """Patched json.loads that cleans markdown and extracts JSON before parsing"""
    if isinstance(s, str):
        original_s = s
        
        # 1. Strip markdown code blocks
        if "```" in s:
            match = re.search(r"```(?:\w+)?\s*(.*?)```", s, re.DOTALL)
            if match:
                s = match.group(1).strip()
            else:
                s = s.replace("```json", "").replace("```", "").strip()
        
        # 2. Extract JSON structure
        first_brace = s.find('{')
        first_bracket = s.find('[')
        
        start_idx = -1
        end_char = ''
        
        if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
            start_idx = first_brace
            end_char = '}'
        elif first_bracket != -1:
            start_idx = first_bracket
            end_char = ']'
            
        if start_idx != -1:
            end_idx = s.rfind(end_char)
            if end_idx != -1 and end_idx > start_idx:
                s = s[start_idx:end_idx+1]
        
        if s != original_s:
            logger.info(f"json.loads patch: cleaned input")
    
    return _original_json_loads(s, *args, **kwargs)

json.loads = _patched_json_loads



class GraphitiWrapper:
    """
    Wrapper for Graphiti SDK that integrates with Neo4j.
    Handles episode creation, search, and graph retrieval.
    """
    
    def __init__(self):
        """Initialize Graphiti client with Neo4j connection and custom LLM/Embedder"""
        try:
            from openai import AsyncOpenAI
            from graphiti_core.llm_client.openai_client import OpenAIClient
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
            
            # Custom HTTP Transport to intercept and clean responses at the network layer
            import httpx
            import json
            import re
            
            class CleaningHTTPTransport(httpx.AsyncHTTPTransport):
                async def handle_async_request(self, request):
                    # Inject JSON instruction into request
                    # We assume any POST request going through this client is an LLM request
                    if request.method == "POST":
                        logger.info(f"Intercepted POST request to: {request.url}")
                        try:
                            # We can't easily modify the request body here without reading it,
                            # which consumes the stream. So we rely on the system prompt
                            # being set in the client config or the response cleaning.
                            pass
                        except Exception:
                            pass

                    response = await super().handle_async_request(request)
                    
                    # Intercept response
                    if response.status_code == 200:
                        try:
                            # Read the response body
                            await response.aread()
                            
                            # Log first 500 chars of response for debugging
                            logger.info(f"Response body preview: {response.content[:500]}")
                            
                            try:
                                data = json.loads(response.content)
                            except json.JSONDecodeError:
                                logger.warning("Response is not valid JSON")
                                return response
                            
                            if isinstance(data, dict) and "choices" in data and len(data["choices"]) > 0:
                                content = data["choices"][0]["message"]["content"]
                                if content:
                                    logger.info(f"LLM Raw Response (HTTP): {content}")
                                    original_content = content
                                    
                                    # 1. Clean Markdown/XML
                                    if "```" in content:
                                        match = re.search(r"```(?:\w+)?\s*(.*?)```", content, re.DOTALL)
                                        if match:
                                            content = match.group(1).strip()
                                        else:
                                            content = content.replace("```json", "").replace("```", "").strip()
                                    
                                    # 2. Extract JSON structure (find first { or [ and last } or ])
                                    start_brace = content.find('{')
                                    start_bracket = content.find('[')
                                    
                                    start_idx = -1
                                    end_char = ''
                                    
                                    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
                                        start_idx = start_brace
                                        end_char = '}'
                                    elif start_bracket != -1:
                                        start_idx = start_bracket
                                        end_char = ']'
                                        
                                    if start_idx != -1:
                                        end_idx = content.rfind(end_char)
                                        if end_idx != -1 and end_idx > start_idx:
                                            content = content[start_idx:end_idx+1]

                                    # 3. Fix List vs Object
                                    try:
                                        # Try to parse to check structure
                                        parsed = json.loads(content)
                                        if isinstance(parsed, list):
                                            logger.info("Fixing JSON: List found, wrapping in 'entities'")
                                            # Wrap list in object with 'entities' key (common default)
                                            content = json.dumps({"entities": parsed})
                                    except json.JSONDecodeError:
                                        pass
                                    
                                    if content != original_content:
                                        logger.info(f"LLM Cleaned Response (HTTP): {content}")
                                        data["choices"][0]["message"]["content"] = content
                                        
                                        # Re-encode response
                                        new_body = json.dumps(data).encode('utf-8')
                                        
                                        return httpx.Response(
                                            status_code=response.status_code,
                                            headers=response.headers,
                                            content=new_body,
                                            request=request,
                                            extensions=response.extensions
                                        )
                        except Exception as e:
                            logger.error(f"Error in CleaningHTTPTransport: {e}")
                            
                    return response

            # Create custom http client
            http_client = httpx.AsyncClient(transport=CleaningHTTPTransport())

            # Create AsyncOpenAI client for LLM using the custom http client
            llm_async_client = AsyncOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                http_client=http_client
            )
            
            # Create LLM client
            llm_client = OpenAIClient(
                client=llm_async_client,
                config=LLMConfig(
                    model=settings.LLM_MODEL,
                    small_model=settings.LLM_MODEL  # Use same model for now
                )
            )
            
            # Create AsyncOpenAI client for embeddings
            embedder_async_client = AsyncOpenAI(
                base_url=settings.EMBEDDING_BASE_URL,
                api_key=settings.EMBEDDING_API_KEY,
            )
            
            # Create embedder client with config
            embedder = OpenAIEmbedder(
                client=embedder_async_client,
                config=OpenAIEmbedderConfig(
                    embedding_model=settings.EMBEDDING_MODEL,
                    api_key=settings.EMBEDDING_API_KEY,
                    base_url=settings.EMBEDDING_BASE_URL
                )
            )
            
            # Create AsyncOpenAI client for reranker
            reranker_async_client = AsyncOpenAI(
                base_url=settings.RERANKER_BASE_URL,
                api_key=settings.RERANKER_API_KEY,
            )
            
            # Create reranker client
            reranker = OpenAIRerankerClient(
                client=reranker_async_client,
                config=LLMConfig(
                    model=settings.RERANKER_MODEL,
                    api_key=settings.RERANKER_API_KEY,
                    base_url=settings.RERANKER_BASE_URL
                )
            )
            
            # Initialize Graphiti with custom clients
            self.client = Graphiti(
                settings.NEO4J_URI,
                settings.NEO4J_USER,
                settings.NEO4J_PASSWORD,
                llm_client=llm_client,
                embedder=embedder,
                cross_encoder=reranker
            )
            
            logger.info(f"Graphiti client initialized with Neo4j at {settings.NEO4J_URI}")
            logger.info(f"Using LLM: {settings.LLM_MODEL} at {settings.LLM_BASE_URL}")
            logger.info(f"Using Embedder: {settings.EMBEDDING_MODEL} at {settings.EMBEDDING_BASE_URL}")
            logger.info(f"Using Reranker: {settings.RERANKER_MODEL} at {settings.RERANKER_BASE_URL}")
            
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
