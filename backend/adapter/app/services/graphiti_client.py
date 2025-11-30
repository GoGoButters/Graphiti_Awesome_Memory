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

                    import asyncio
                    import time

                    # Retry configuration
                    TIMEOUT = 30
                    RETRY_INTERVAL = 5
                    start_time = time.time()

                    while True:
                        try:
                            response = await super().handle_async_request(request)
                            
                            # If successful, break loop
                            if response.status_code < 400:
                                break
                                
                            # If error, check timeout
                            elapsed = time.time() - start_time
                            if elapsed >= TIMEOUT:
                                logger.error(f"Request failed after {TIMEOUT}s retrying. Final status: {response.status_code}")
                                break
                                
                            logger.warning(f"Request failed with status {response.status_code}. Retrying in {RETRY_INTERVAL}s... (Elapsed: {int(elapsed)}s)")
                            await asyncio.sleep(RETRY_INTERVAL)
                            
                        except Exception as e:
                            # Handle network errors
                            elapsed = time.time() - start_time
                            if elapsed >= TIMEOUT:
                                logger.error(f"Request failed after {TIMEOUT}s retrying. Error: {e}")
                                raise e
                                
                            logger.warning(f"Request failed with error {e}. Retrying in {RETRY_INTERVAL}s... (Elapsed: {int(elapsed)}s)")
                            await asyncio.sleep(RETRY_INTERVAL)
                    
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
                                        modified = False
                                        
                                        if isinstance(parsed, list):
                                            logger.info("Fixing JSON: List found, wrapping in 'extracted_entities'")
                                            parsed = {"extracted_entities": parsed}
                                            modified = True
                                        elif isinstance(parsed, dict) and "entities" in parsed:
                                            logger.info("Fixing JSON: Renaming 'entities' to 'extracted_entities'")
                                            parsed["extracted_entities"] = parsed.pop("entities")
                                            modified = True
                                        
                                        # Fix entity_name -> name in extracted_entities
                                        if isinstance(parsed, dict) and "extracted_entities" in parsed:
                                            for entity in parsed["extracted_entities"]:
                                                if isinstance(entity, dict) and "entity_name" in entity:
                                                    entity["name"] = entity.pop("entity_name")
                                                    modified = True
                                            
                                            # Fix NodeResolutions: extracted_entities -> entity_resolutions
                                            # If the entities contain 'duplicates', it's a resolution result
                                            entities = parsed["extracted_entities"]
                                            if entities and isinstance(entities, list) and len(entities) > 0:
                                                if isinstance(entities[0], dict) and "duplicates" in entities[0]:
                                                    parsed["entity_resolutions"] = parsed.pop("extracted_entities")
                                                    logger.info("Fixing JSON: Renamed 'extracted_entities' to 'entity_resolutions' (detected resolution format)")
                                                    modified = True
                                        
                                        # Fix extracted_edges -> edges
                                        if isinstance(parsed, dict) and "extracted_edges" in parsed:
                                            parsed["edges"] = parsed.pop("extracted_edges")
                                            logger.info("Fixing JSON: Renamed 'extracted_edges' to 'edges'")
                                            modified = True
                                        
                                        if modified:
                                            content = json.dumps(parsed)
                                            
                                    except json.JSONDecodeError:
                                        # If JSON parsing fails, check if it's plain text that needs wrapping
                                        if content and not content.strip().startswith('{') and not content.strip().startswith('['):
                                            # Wrap plain text in {"summary": "..."} for EntitySummary
                                            logger.info("Fixing JSON: Wrapping plain text in summary object")
                                            content = json.dumps({"summary": content.strip()})
                                    
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
                            
                            # Handle non-standard format (e.g., LiteLLM with 'output' field)
                            elif isinstance(data, dict) and "output" in data and len(data["output"]) > 0:
                                # For reasoning models, output array contains:
                                # [{"type": "reasoning", ...}, {"type": "message", ...}]
                                # We need to extract ONLY the "message" type, skip "reasoning"
                                
                                content = None
                                output_index = 0  # Track which output we use for logging
                                
                                # Try to find message-type output (skip reasoning)
                                for idx, output_item in enumerate(data["output"]):
                                    if isinstance(output_item, dict):
                                        item_type = output_item.get("type", "unknown")
                                        
                                        # Skip reasoning output
                                        if item_type == "reasoning":
                                            logger.info(f"Skipping reasoning output at index {idx}")
                                            continue
                                        
                                        # Extract content from message-type output
                                        if "content" in output_item and len(output_item["content"]) > 0:
                                            if isinstance(output_item["content"][0], dict) and "text" in output_item["content"][0]:
                                                content = output_item["content"][0]["text"]
                                                output_index = idx
                                                logger.info(f"Using output[{idx}] (type: {item_type})")
                                                break
                                
                                # Fallback: if no message found, use first output (old behavior)
                                if content is None:
                                    try:
                                        content = data["output"][0]["content"][0]["text"]
                                        output_index = 0
                                        logger.warning("No message-type output found, using output[0] as fallback")
                                    except (KeyError, IndexError, TypeError) as e:
                                        logger.error(f"Failed to extract content from output: {e}")
                                        return response
                                
                                if content:
                                    logger.info(f"LLM Raw Response (HTTP, non-standard): {content}")
                                    original_content = content
                                    
                                    # Clean markdown
                                    if "```" in content:
                                        match = re.search(r"```(?:\w+)?\s*(.*?)```", content, re.DOTALL)
                                        if match:
                                            content = match.group(1).strip()
                                        else:
                                            content = content.replace("```json", "").replace("```", "").strip()
                                    
                                    # Extract JSON
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
                                    
                                    # Fix List vs Object
                                    try:
                                        parsed = json.loads(content)
                                        modified = False
                                        
                                        if isinstance(parsed, list):
                                            logger.info("Fixing JSON: List found, wrapping in 'extracted_entities'")
                                            parsed = {"extracted_entities": parsed}
                                            modified = True
                                        elif isinstance(parsed, dict) and "entities" in parsed:
                                            logger.info("Fixing JSON: Renaming 'entities' to 'extracted_entities'")
                                            parsed["extracted_entities"] = parsed.pop("entities")
                                            modified = True
                                        
                                        # Fix entity_name -> name in extracted_entities
                                        if isinstance(parsed, dict) and "extracted_entities" in parsed:
                                            for entity in parsed["extracted_entities"]:
                                                if isinstance(entity, dict) and "entity_name" in entity:
                                                    entity["name"] = entity.pop("entity_name")
                                                    modified = True
                                            
                                            # Fix NodeResolutions: extracted_entities -> entity_resolutions
                                            entities = parsed["extracted_entities"]
                                            if entities and isinstance(entities, list) and len(entities) > 0:
                                                if isinstance(entities[0], dict) and "duplicates" in entities[0]:
                                                    parsed["entity_resolutions"] = parsed.pop("extracted_entities")
                                                    logger.info("Fixing JSON: Renamed 'extracted_entities' to 'entity_resolutions' (detected resolution format)")
                                                    modified = True
                                        
                                        # Fix extracted_edges -> edges
                                        if isinstance(parsed, dict) and "extracted_edges" in parsed:
                                            parsed["edges"] = parsed.pop("extracted_edges")
                                            logger.info("Fixing JSON: Renamed 'extracted_edges' to 'edges'")
                                            modified = True
                                        
                                        if modified:
                                            content = json.dumps(parsed)
                                            
                                    except json.JSONDecodeError:
                                        # If JSON parsing fails, check if it's plain text that needs wrapping
                                        if content and not content.strip().startswith('{') and not content.strip().startswith('['):
                                            # Wrap plain text in {"summary": "..."} for EntitySummary
                                            logger.info("Fixing JSON: Wrapping plain text in summary object")
                                            content = json.dumps({"summary": content.strip()})
                                    
                                    if content != original_content:
                                        logger.info(f"LLM Cleaned Response (HTTP, non-standard): {content}")
                                        data["output"][output_index]["content"][0]["text"] = content
                                        
                                        # Re-encode response
                                        new_body = json.dumps(data).encode('utf-8')
                                        
                                        return httpx.Response(
                                            status_code=response.status_code,
                                            headers=response.headers,
                                            content=new_body,
                                            request=request,
                                            extensions=response.extensions
                                        )
                                except (KeyError, IndexError, TypeError) as e:
                                    logger.error(f"Error parsing non-standard response: {e}")
                        except Exception as e:
                            logger.error(f"Error in CleaningHTTPTransport: {e}")
                            
                    return response

            # Create AsyncOpenAI client for LLM using the custom http client
            llm_async_client = AsyncOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                http_client=httpx.AsyncClient(transport=CleaningHTTPTransport())
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
                http_client=httpx.AsyncClient(transport=CleaningHTTPTransport())
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
                http_client=httpx.AsyncClient(transport=CleaningHTTPTransport())
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
            
            # Add episode to Graphiti with group_id for user isolation
            await self.client.add_episode(
                name=episode_name,
                episode_body=text,
                source=EpisodeType.text,
                source_description=f"{source_description} ({role})",
                reference_time=datetime.now(timezone.utc),
                group_id=user_id  # Critical: isolate data by user
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
            
            # Get Neo4j driver from Graphiti client
            driver = self.client.driver
            
            # Query nodes and edges filtered by group_id
            query = """
            // Get all nodes for this user by group_id
            MATCH (n:EntityNode)
            WHERE n.group_id = $group_id
            
            // Get edges between these nodes
            OPTIONAL MATCH (n)-[r:RELATES_TO]-(m:EntityNode)
            WHERE m.group_id = $group_id
            
            RETURN 
                collect(DISTINCT n) as nodes,
                collect(DISTINCT r) as edges
            """
            
            result = await driver.execute_query(
                query,
                group_id=user_id,
                database_="neo4j"
            )
            
            # Convert to Cytoscape.js format
            nodes = []
            edges = []
            
            if result.records:
                record = result.records[0]
                
                # Process nodes
                for node in record["nodes"]:
                    nodes.append({
                        "data": {
                            "id": node.get("uuid", str(node.id)),
                            "label": node.get("name", "Unknown"),
                            "summary": (node.get("summary", "")[:200] if node.get("summary") else ""),
                            "created_at": str(node.get("created_at")) if node.get("created_at") else None,
                        }
                    })
                
                # Process edges
                for edge in record["edges"]:
                    if edge:  # Skip None edges from OPTIONAL MATCH
                        nodes_data = edge.nodes
                        if len(nodes_data) >= 2:
                            edges.append({
                                "data": {
                                    "id": edge.get("uuid", str(edge.id)),
                                    "source": nodes_data[0].get("uuid", str(nodes_data[0].id)),
                                    "target": nodes_data[1].get("uuid", str(nodes_data[1].id)),
                                    "label": (edge.get("fact", "")[:100] if edge.get("fact") else ""),
                                }
                            })
            
            logger.info(f"Retrieved {len(nodes)} nodes and {len(edges)} edges for user {user_id}")
            
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
    
    async def delete_user(self, user_id: str) -> bool:
        """
        Delete all data for a user from Neo4j
        
        Args:
            user_id: User identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Deleting all data for user: {user_id}")
            
            # Strategy:
            # 1. Find and delete all episodes for this user (by name pattern)
            # 2. Delete nodes that are only connected to these episodes
            # 3. Delete edges that reference deleted nodes
            
            # Get Neo4j driver from graphiti client
            driver = self.client.driver
            
            # Cypher query to delete episodes and their associated data
            query = """
            // Find all episodes for this user
            MATCH (e:Episodic)
            WHERE e.name STARTS WITH $user_prefix
            
            // Match connected nodes
            OPTIONAL MATCH (e)--(n)
            
            // Use DETACH DELETE to automatically remove all relationships
            DETACH DELETE e, n
            
            RETURN count(DISTINCT e) as episodes_deleted
            """
            
            # Execute deletion by episode connection
            result = await driver.execute_query(
                query,
                user_prefix=f"{user_id}_",
                database_="neo4j"
            )
            
            episodes_deleted = result.records[0]["episodes_deleted"] if result.records else 0
            
            # Fallback: Delete by group_id if it exists (handles orphaned nodes)
            # Graphiti often uses group_id for tenancy
            cleanup_query = """
            MATCH (n)
            WHERE n.group_id = $user_id
            DETACH DELETE n
            RETURN count(n) as nodes_deleted
            """
            
            cleanup_result = await driver.execute_query(
                cleanup_query,
                user_id=user_id,
                database_="neo4j"
            )
            
            nodes_deleted = cleanup_result.records[0]["nodes_deleted"] if cleanup_result.records else 0
            
            logger.info(f"Deleted {episodes_deleted} episodes and {nodes_deleted} orphaned nodes for user {user_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting user {user_id}: {e}")
            return False

    async def get_user_episodes(self, user_id: str) -> list:
        """
        Get list of episodes for a user
        
        Args:
            user_id: User identifier
            
        Returns:
            List of episode dictionaries
        """
        try:
            logger.info(f"Getting episodes for user: {user_id}")
            driver = self.client.driver
            
            query = """
            MATCH (e:Episodic)
            WHERE e.name STARTS WITH $user_prefix
            RETURN e.uuid as uuid, e.name as name, e.created_at as created_at, 
                   e.source_description as source, e.episode_body as body
            ORDER BY e.created_at DESC
            """
            
            result = await driver.execute_query(
                query,
                user_prefix=f"{user_id}_",
                database_="neo4j"
            )
            
            episodes = []
            if result.records:
                for record in result.records:
                    created_at = record["created_at"]
                    if hasattr(created_at, 'iso_format'):
                        created_at = created_at.iso_format()
                    elif hasattr(created_at, 'to_native'):
                        created_at = created_at.to_native()
                        
                    episodes.append({
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "created_at": str(created_at),
                        "source": record["source"],
                        "body": record["body"][:200] + "..." if record["body"] and len(record["body"]) > 200 else record["body"]
                    })
            
            return episodes
            
        except Exception as e:
            logger.error(f"Error getting episodes for user {user_id}: {e}")
            return []

    async def delete_episode(self, episode_uuid: str) -> bool:
        """
        Delete a specific episode and cleanup orphaned nodes
        
        Args:
            episode_uuid: Episode UUID
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Deleting episode: {episode_uuid}")
            driver = self.client.driver
            
            # Delete episode and cleanup orphaned nodes
            query = """
            MATCH (e:Episodic {uuid: $uuid})
            
            // Collect connected nodes before deleting episode
            OPTIONAL MATCH (e)--(n)
            WITH e, collect(DISTINCT n) as connected_nodes
            
            // Delete the episode
            DETACH DELETE e
            
            // Check connected nodes for orphans
            WITH connected_nodes
            UNWIND connected_nodes as n
            MATCH (n)
            WHERE NOT (n)--()
            DETACH DELETE n
            """
            
            await driver.execute_query(
                query,
                uuid=episode_uuid,
                database_="neo4j"
            )
            
            logger.info(f"Deleted episode {episode_uuid}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting episode {episode_uuid}: {e}")
            return False

    async def close(self):
        """Close the Graphiti client connection"""
        try:
            await self.client.close()
            logger.info("Graphiti client connection closed")
        except Exception as e:
            logger.error(f"Error closing Graphiti client: {e}")


# Global Graphiti client instance
graphiti_client = GraphitiWrapper()
