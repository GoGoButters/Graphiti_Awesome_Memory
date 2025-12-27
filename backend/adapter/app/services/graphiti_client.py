"""
Graphiti Client Wrapper - Real SDK Integration

This module provides a wrapper around the graphiti-core Python SDK for
building and querying temporal knowledge graphs.
"""

import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import NODE_HYBRID_SEARCH_RRF, COMBINED_HYBRID_SEARCH_CROSS_ENCODER
from graphiti_core.cross_encoder.client import CrossEncoderClient

from app.core.config import settings
from app.models.schemas import MemoryHit

logger = logging.getLogger(__name__)

import json
import re
import copy
import httpx

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



json.loads = _patched_json_loads

class RemoteRerankerClient(CrossEncoderClient):
    """
    Custom CrossEncoder client for remote reranker servers (e.g. llama.cpp, Jina).
    Sends POST requests to /v1/rerank compatible endpoints.
    """
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip('/')
        if self.base_url.endswith('/v1'):
            self.base_url = self.base_url[:-3]
            
        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=30.0)

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []

        url = f"{self.base_url}/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "query": query,
            "documents": passages,
            "top_n": len(passages)  # Return all, sorted
        }

        try:
            logger.info(f"Reranking {len(passages)} passages via {url}")
            response = await self.client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            data = response.json()
            # Expecting Jina/Cohere format: {"results": [{"index": i, "relevance_score": s}, ...]}
            results = data.get("results", [])
            
            # Map results back to passages
            ranked = []
            for res in results:
                idx = res.get("index")
                score = res.get("relevance_score")
                if idx is not None and 0 <= idx < len(passages):
                    ranked.append((passages[idx], float(score)))
            
            logger.info(f"Rerank success, top score: {ranked[0][1] if ranked else 'none'}")
            return ranked
            
        except Exception as e:
            logger.error(f"Remote reranking failed: {e}")
            raise e


class GraphitiWrapper:
    """
    Wrapper for Graphiti SDK that integrates with Neo4j.
    Handles episode creation, search, and graph retrieval.
    """
    
    def __init__(self):
        """Initialize Graphiti client with Neo4j connection and custom LLM/Embedder"""
        try:
            import os
            
            # Set SEMAPHORE_LIMIT for Graphiti's internal concurrency control
            # This allows parallel LLM operations instead of sequential processing
            # Default is 10, we increase to 20 for faster processing without hitting rate limits
            if "SEMAPHORE_LIMIT" not in os.environ:
                os.environ["SEMAPHORE_LIMIT"] = "20"
            
            # Reduce reflexion iterations to minimize LLM calls
            # Default is 3, reducing to 2 trades minimal quality (~3%) for 33% fewer calls
            if "MAX_REFLEXION_ITERATIONS" not in os.environ:
                os.environ["MAX_REFLEXION_ITERATIONS"] = "2"
            
            logger.info(f"SEMAPHORE_LIMIT set to: {os.environ.get('SEMAPHORE_LIMIT', '10')}")
            logger.info(f"MAX_REFLEXION_ITERATIONS set to: {os.environ.get('MAX_REFLEXION_ITERATIONS', '3')}")
            
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
                            
                            # Don't retry on client errors (4xx) except 429 (Too Many Requests)
                            if 400 <= response.status_code < 500 and response.status_code != 429:
                                logger.error(f"Request failed with status {response.status_code} (Client Error). Not retrying.")
                                # Try to read error body for debugging
                                try:
                                    await response.aread()
                                    error_body = response.content.decode('utf-8', errors='ignore')
                                    logger.error(f"Error body: {error_body}")
                                except:
                                    pass
                                break

                            # If error (5xx or 429), check timeout
                            elapsed = time.time() - start_time
                            
                            # Try to read error body for debugging
                            error_body = ""
                            try:
                                await response.aread()
                                error_body = response.content.decode('utf-8', errors='ignore')
                            except:
                                pass

                            if elapsed >= TIMEOUT:
                                logger.error(f"Request failed after {TIMEOUT}s retrying. Final status: {response.status_code}. Error: {error_body}")
                                break
                                
                            logger.warning(f"Request failed with status {response.status_code}. Error: {error_body}. Retrying in {RETRY_INTERVAL}s... (Elapsed: {int(elapsed)}s)")
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
                                        
                                        # If parsed is just a string, it's likely a summary that needs wrapping
                                        if isinstance(parsed, str):
                                            logger.info("Fixing JSON: Parsed content is a string, wrapping in 'summary' with empty entities")
                                            parsed = {
                                                "summary": parsed,
                                                "extracted_entities": []
                                            }
                                            modified = True
                                        
                                        elif isinstance(parsed, list):
                                            # Detect if this is a list of edges or entities
                                            # Edges have source_entity_id and target_entity_id
                                            # Entities have name or entity_name
                                            if len(parsed) > 0 and isinstance(parsed[0], dict) and ("source_entity_id" in parsed[0] or "relation_type" in parsed[0]):
                                                logger.info("Fixing JSON: List found (edges detected), wrapping in 'edges'")
                                                parsed = {
                                                    "edges": parsed,
                                                    "extracted_entities": []
                                                }
                                            else:
                                                logger.info("Fixing JSON: List found (entities detected), wrapping in 'extracted_entities'")
                                                parsed = {
                                                    "extracted_entities": parsed,
                                                    "edges": []
                                                }
                                            modified = True
                                        elif isinstance(parsed, dict) and "entities" in parsed:
                                            logger.info("Fixing JSON: Renaming 'entities' to 'extracted_entities'")
                                            parsed["extracted_entities"] = parsed.pop("entities")
                                            modified = True
                                        
                                        # Fix facts -> edges
                                        if isinstance(parsed, dict) and "facts" in parsed:
                                            logger.info("Fixing JSON: Renaming 'facts' to 'edges'")
                                            parsed["edges"] = parsed.pop("facts")
                                            modified = True
                                        
                                        # Fix entity_name -> name and entity -> name in extracted_entities
                                        if isinstance(parsed, dict) and "extracted_entities" in parsed:
                                            for entity in parsed["extracted_entities"]:
                                                if isinstance(entity, dict):
                                                    if "entity_name" in entity:
                                                        entity["name"] = entity.pop("entity_name")
                                                        modified = True
                                                    elif "entity" in entity:
                                                        entity["name"] = entity.pop("entity")
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
                                            # Attempt to repair truncated JSON
                                            # LLMs often cut off at max tokens, leaving unclosed lists/objects
                                            if content.strip().startswith('{') or content.strip().startswith('['):
                                                repaired = False
                                                # Common suffixes to try
                                                suffixes = ["}", "]", "}}", "]}", "}]", "}}}", "}}]", "}]}", "]}}", "]}]", "]]}", "]]]", '"}', '"]', '"]}', '"]}]', '"]}\n]}', '}\n]}']
                                                for suffix in suffixes:
                                                    try:
                                                        temp_content = content + suffix
                                                        json.loads(temp_content)
                                                        content = temp_content
                                                        logger.info(f"Fixing JSON: Repaired truncated JSON with suffix '{suffix}'")
                                                        repaired = True
                                                        break
                                                    except json.JSONDecodeError:
                                                        continue
                                        
                                    # If JSON parsing fails (and repair failed), check if it's plain text that needs wrapping
                                    if content and not content.strip().startswith('{') and not content.strip().startswith('['):
                                        # Wrap plain text - include both extracted_entities and edges for compatibility
                                        logger.info("Fixing JSON: Wrapping plain text in summary object with empty entities/edges")
                                        content = json.dumps({
                                            "summary": content.strip(),
                                            "extracted_entities": [],
                                            "edges": []
                                        })
                                    
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
                                
                                try:
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
                                                # Detect if this is a list of edges or entities (LiteLLM path)
                                                if len(parsed) > 0 and isinstance(parsed[0], dict) and ("source_entity_id" in parsed[0] or "relation_type" in parsed[0]):
                                                    logger.info("Fixing JSON: List found (edges detected), wrapping in 'edges'")
                                                    parsed = {
                                                        "edges": parsed,
                                                        "extracted_entities": []
                                                    }
                                                else:
                                                    logger.info("Fixing JSON: List found (entities detected), wrapping in 'extracted_entities'")
                                                    parsed = {
                                                        "extracted_entities": parsed,
                                                        "edges": []
                                                    }
                                                modified = True
                                            elif isinstance(parsed, dict) and "entities" in parsed:
                                                logger.info("Fixing JSON: Renaming 'entities' to 'extracted_entities'")
                                                parsed["extracted_entities"] = parsed.pop("entities")
                                                modified = True
                                            
                                            # Fix facts -> edges
                                            if isinstance(parsed, dict) and "facts" in parsed:
                                                logger.info("Fixing JSON: Renaming 'facts' to 'edges'")
                                                parsed["edges"] = parsed.pop("facts")
                                                modified = True
                                            
                                            # Fix entity_name -> name and entity -> name in extracted_entities
                                            if isinstance(parsed, dict) and "extracted_entities" in parsed:
                                                for entity in parsed["extracted_entities"]:
                                                    if isinstance(entity, dict):
                                                        if "entity_name" in entity:
                                                            entity["name"] = entity.pop("entity_name")
                                                            modified = True
                                                        elif "entity" in entity:
                                                            entity["name"] = entity.pop("entity")
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
                                            # Attempt to repair truncated JSON
                                            if content.strip().startswith('{') or content.strip().startswith('['):
                                                repaired = False
                                                suffixes = ["}", "]", "}}", "]}", "}]", "}}}", "}}]", "}]}", "]}}", "]}]", "]]}", "]]]", '"}', '"]', '"]}', '"]}]', '"]}\n]}', '}\n]}']
                                                for suffix in suffixes:
                                                    try:
                                                        temp_content = content + suffix
                                                        json.loads(temp_content)
                                                        content = temp_content
                                                        logger.info(f"Fixing JSON: Repaired truncated JSON with suffix '{suffix}'")
                                                        repaired = True
                                                        break
                                                    except json.JSONDecodeError:
                                                        continue

                                        # If JSON parsing fails (and repair failed), check if it's plain text that needs wrapping
                                        if content and not content.strip().startswith('{') and not content.strip().startswith('['):
                                            # Wrap plain text - include both extracted_entities and edges for compatibility
                                            logger.info("Fixing JSON: Wrapping plain text in summary object with empty entities/edges")
                                            content = json.dumps({
                                                "summary": content.strip(),
                                                "extracted_entities": [],
                                                "edges": []
                                            })
                                        
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

            # Create custom HTTP transport for dual-model routing
            # This allows llm and llm_fast to use different base_url and api_key
            import httpx
            import json
            import re
            from urllib.parse import urlparse, urlunparse
            
            class DualModelRoutingTransport(CleaningHTTPTransport):
                """
                Extended HTTP transport that routes requests to appropriate endpoint
                based on model name in the request body, while preserving cleaning
                and retry functionality from CleaningHTTPTransport.
                """
                def __init__(self, main_base_url, main_api_key, fast_base_url, fast_api_key, fast_model):
                    super().__init__()
                    self.main_base_url = main_base_url
                    self.main_api_key = main_api_key
                    self.fast_base_url = fast_base_url
                    self.fast_api_key = fast_api_key
                    self.fast_model = fast_model
                    
                    # Parse URLs for modification
                    self.main_parsed = urlparse(main_base_url)
                    self.fast_parsed = urlparse(fast_base_url)
                
                async def handle_async_request(self, request):
                    # Determine which endpoint to use based on model in request
                    original_url = str(request.url)
                    original_auth = request.headers.get('authorization', 'not set')
                    
                    try:
                        body = request.content.decode('utf-8') if request.content else "{}"
                        try:                                                                                                                                                                                             
                            # Use original json.loads to avoid our global patch affecting request parsing                                                                                                
                            data = _original_json_loads(body)                                                                                                                                            
                            # Handle case where body is not a valid JSON (e.g. empty string)                                                                                                             
                            if not isinstance(data, dict):                                                                                                                                               
                                data = {}                                                                                                                                                                
                        except json.JSONDecodeError:                                                                                                                                                     
                            # Only log if body is not empty but failed to parse                                                                                                                          
                            if body.strip():                                                                                                                                                             
                                logger.warning(f"Failed to parse request body JSON: {body[:100]}...")                                                                                                    
                            data = {}
                            
                        model = data.get("model", "")
                        
                        logger.info(f"🔍 Routing request: model={model}, url={original_url}")
                        logger.info(f"   Fast model configured: {self.fast_model}")
                        logger.info(f"   Auth header: {original_auth[:20]}...")
                        
                        # Route to fast endpoint if request is for fast model
                        if model == self.fast_model:
                            logger.info(f"✓ Model matches fast_model!")
                            
                            if self.fast_base_url != self.main_base_url:
                                # Modify request URL to point to fast endpoint
                                req_parsed = urlparse(str(request.url))
                                new_url = urlunparse((
                                    self.fast_parsed.scheme,
                                    self.fast_parsed.netloc,
                                    req_parsed.path,
                                    req_parsed.params,
                                    req_parsed.query,
                                    req_parsed.fragment
                                ))
                                
                                # Create new request with modified URL
                                headers_dict = dict(request.headers)
                                request = httpx.Request(
                                    method=request.method,
                                    url=new_url,
                                    headers=headers_dict,
                                    content=request.content
                                )
                                logger.info(f"→ Routed to fast endpoint: {new_url}")
                            else:
                                logger.info(f"→ Same endpoint for both models, no URL change needed")
                            
                            # Always update Authorization header to ensure correct key is used for fast model
                            # This avoids issues where keys might look identical or checks fail
                            headers_dict = dict(request.headers)
                            headers_dict['authorization'] = f'Bearer {self.fast_api_key}'
                            
                            request = httpx.Request(
                                method=request.method,
                                url=request.url,
                                headers=headers_dict,
                                content=request.content
                            )
                            masked_key = self.fast_api_key[:10] + "..." if self.fast_api_key else "None"
                            logger.info(f"→ Switched to fast API key: {masked_key}")
                        else:
                            logger.info(f"→ Using main LLM endpoint (model != fast_model)")
                    
                    except Exception as e:
                        logger.error(f"❌ Error in routing logic: {e}", exc_info=True)
                    
                    # Continue with cleaning and retry logic from parent class
                    logger.info(f"⏳ Calling parent handler (CleaningHTTPTransport)...")
                    response = await super().handle_async_request(request)
                    logger.info(f"✓ Parent handler returned: status={response.status_code}")
                    return response
            
            # Create dual-model routing transport
            routing_transport = DualModelRoutingTransport(
                main_base_url=settings.LLM_BASE_URL,
                main_api_key=settings.LLM_API_KEY,
                fast_base_url=settings.LLM_FAST_BASE_URL,
                fast_api_key=settings.LLM_FAST_API_KEY,
                fast_model=settings.LLM_FAST_MODEL
            )
            
            # Log configuration
            logger.info(f"Dual-model routing configured:")
            logger.info(f"  Main LLM: {settings.LLM_MODEL} at {settings.LLM_BASE_URL}")
            logger.info(f"  Fast LLM: {settings.LLM_FAST_MODEL} at {settings.LLM_FAST_BASE_URL}")
            if settings.LLM_FAST_BASE_URL != settings.LLM_BASE_URL:
                logger.info(f"  ✓ Using separate endpoints for main and fast models")
            if settings.LLM_FAST_API_KEY != settings.LLM_API_KEY:
                logger.info(f"  ✓ Using separate API keys for main and fast models")
            
            llm_async_client = AsyncOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                http_client=httpx.AsyncClient(transport=routing_transport)
            )
            
            # Create LLM client with DUAL-MODEL strategy
            llm_client = OpenAIClient(
                client=llm_async_client,
                config=LLMConfig(
                    model=settings.LLM_MODEL,
                    small_model=settings.LLM_FAST_MODEL
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
            
            # Create reranker client
            reranker = RemoteRerankerClient(
                base_url=settings.RERANKER_BASE_URL,
                api_key=settings.RERANKER_API_KEY,
                model=settings.RERANKER_MODEL
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

    async def save_pending_episode(self, user_id: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Save a temporary PendingEpisode node to make the message immediately available
        before heavy processing completes.
        """
        try:
            driver = self.client.driver
            uuid_str = str(uuid.uuid4())
            # Use ISO format string for consistency with Graphiti
            created_at = datetime.now(timezone.utc).isoformat()
            
            source = "User"
            file_name = None
            if metadata:
                source = metadata.get("source", source)
                file_name = metadata.get("file_name")
            
            query = """
            MERGE (u:User {id: $user_id})
            CREATE (p:PendingEpisode {
                uuid: $uuid,
                content: $text,
                created_at: $created_at,
                source: $source,
                file_name: $file_name,
                status: 'pending',
                user_id: $user_id
            })
            MERGE (u)-[:HAS_PENDING]->(p)
            RETURN p.uuid as uuid
            """
            
            await driver.execute_query(
                query,
                user_id=user_id,
                uuid=uuid_str,
                text=text,
                created_at=created_at,
                source=source,
                file_name=file_name,
                database_="neo4j"
            )
            
            logger.info(f"Saved PendingEpisode for user {user_id}: {uuid_str} (file: {file_name})")
            return uuid_str
        except Exception as e:
            logger.error(f"Error saving pending episode: {e}")
            return None

    async def delete_pending_episode(self, user_id: str, text: str):
        """
        Delete a PendingEpisode node after successful processing.
        Matches by content and user_id since UUID might differ.
        """
        try:
            driver = self.client.driver
            query = """
            MATCH (p:PendingEpisode)
            WHERE p.user_id = $user_id AND p.content = $text
            DETACH DELETE p
            """
            await driver.execute_query(
                query,
                user_id=user_id,
                text=text,
                database_="neo4j"
            )
            logger.info(f"Cleaned up PendingEpisode for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting pending episode: {e}")

    async def get_stuck_pending_episodes(self, minutes: int = 30) -> list:
        """
        Get PendingEpisodes older than X minutes that might be stuck.
        """
        try:
            driver = self.client.driver
            # Calculate cutoff time as ISO string
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
            
            query = """
            MATCH (p:PendingEpisode)
            WHERE p.created_at < $cutoff
            RETURN p.user_id as user_id, p.content as content, p.source as source, p.uuid as uuid
            """
            
            result = await driver.execute_query(
                query,
                cutoff=cutoff,
                database_="neo4j"
            )
            
            stuck = []
            if result.records:
                for record in result.records:
                    stuck.append({
                        "user_id": record["user_id"],
                        "content": record["content"],
                        "source": record["source"],
                        "uuid": record["uuid"]
                    })
            return stuck
        except Exception as e:
            logger.error(f"Error getting stuck episodes: {e}")
            return []

    async def add_episode(
        self,
        user_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add an episode (memory) to the knowledge graph.
        Called as background task after save_pending_episode.
        """
        # 1. Create episode name
        timestamp = datetime.now(timezone.utc).isoformat()
        episode_name = f"{user_id}_{timestamp}"
        
        source_description = "User Input"
        role = "user"
        file_name = None
        if metadata:
            source_description = metadata.get("source", source_description)
            role = metadata.get("role", role)
            file_name = metadata.get("file_name")
        
        # Append file name to source description for context
        final_source = f"{source_description} ({role})"
        if file_name:
            final_source = f"{source_description} (file: {file_name})"

        logger.info(f"Adding episode for user {user_id} (len: {len(text)}) (file: {file_name})")
    
        try:
            # 2. Add to Graphiti
            await self.client.add_episode(
                name=episode_name,
                episode_body=text,
                source=EpisodeType.text,
                source_description=final_source,
                reference_time=datetime.now(timezone.utc),
                group_id=user_id  # Critical: isolate data by user
            )
            
            # 3. Tag with file_name if provided (Post-processing check)
            if file_name:
                driver = self.client.driver
                tag_query = """
                MATCH (e:Episodic {name: $name})
                SET e.file_name = $file_name
                RETURN e
                """
                await driver.execute_query(tag_query, name=episode_name, file_name=file_name, database_="neo4j")
                logger.debug(f"Tagged episode {episode_name} with file_name: {file_name}")

            logger.info(f"Successfully added episode: {episode_name}")
            
            # 4. Cleanup PendingEpisode after successful processing
            await self.delete_pending_episode(user_id, text)
            
            return episode_name
            
        except Exception as e:
            logger.error(f"Error adding episode {episode_name}: {e}")
            # We DO NOT delete the pending episode on error, so retry logic can pick it up
            raise e

    async def search(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        center_node_uuid: Optional[str] = None
    ) -> List[MemoryHit]:
        """
        Search for relevant memories (edges) in the knowledge graph
        """
        try:
            logger.info(f"Searching for user {user_id}: {query}")
            
            # Perform hybrid search with RERANKER (using search_)
            # We must copy the config to set the limit safely
            search_config = copy.deepcopy(COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
            search_config.limit = limit
            
            try:
                # search_ returns SearchResults object containing nodes and edges
                search_results = await self.client.search_(
                    query=query,
                    center_node_uuid=center_node_uuid,
                    config=search_config,
                    group_ids=[user_id]
                )
                # Extract edges from results
                results = search_results.edges
                logger.info(f"✓ Reranker search successful, got {len(results)} results")
                
            except Exception as e:
                logger.warning(f"⚠️ Reranker search failed ({e}), falling back to basic search")
                # Fallback to basic search (no reranker)
                results = await self.client.search(
                    query=query,
                    center_node_uuid=center_node_uuid,
                    num_results=limit,
                    group_ids=[user_id]
                )
            
            # Collect episode UUIDs from results to fetch file_name metadata
            episode_uuids = set()
            for i, result in enumerate(results[:limit]):
                if i == 0:
                    logger.info(f"DEBUG: First search result type: {type(result)}")
                    logger.info(f"DEBUG: First search result dir: {dir(result)}")
                    logger.info(f"DEBUG: First search result content: {result}")
                
                # Check for episode_uuid or similar properties
                ep_uuid = getattr(result, 'episode_uuid', None)
                if not ep_uuid:
                    # Try alternate names common in Graphiti
                    ep_uuid = getattr(result, 'source_node_uuid', None)
                    # If the edge is MENTIONS, source is episode.
                    # But we need to be sure. 
                    # For now just log what we have.
                
                if ep_uuid:
                    episode_uuids.add(ep_uuid)
            
            # Fetch file_name for episodes in batch
            episode_file_map = {}
            if episode_uuids:
                driver = self.client.driver
                query = """
                MATCH (e:Episodic)
                WHERE e.uuid IN $uuids
                RETURN e.uuid AS uuid, e.file_name AS file_name
                """
                result_records = await driver.execute_query(
                    query,
                    uuids=list(episode_uuids),
                    database_="neo4j"
                )
                for record in result_records.records:
                    episode_file_map[record["uuid"]] = record.get("file_name")
            
            # Convert to MemoryHit format with file_name in metadata
            hits = []
            for result in results[:limit]:
                ep_uuid = getattr(result, 'episode_uuid', None)
                file_name = episode_file_map.get(ep_uuid) if ep_uuid else None
                
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
                        "file_name": file_name,
                        "episode_uuid": ep_uuid,
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
            
            # Query nodes and edges by traversing from user's episodes
            # This is more robust than relying on group_id on Entity nodes
            query = """
            MATCH (e:Episodic)
            WHERE e.group_id = $group_id OR e.name STARTS WITH $user_prefix
            MATCH (e)-[:MENTIONS]->(n:Entity)
            OPTIONAL MATCH (n)-[r]-(m:Entity)
            
            WITH n, r, m
            UNWIND [n, m] as node
            WITH node, r
            WHERE node IS NOT NULL
            
            RETURN 
                collect(DISTINCT node) as nodes,
                collect(DISTINCT {
                    uuid: r.uuid,
                    source: startNode(r).uuid,
                    target: endNode(r).uuid,
                    fact: r.fact
                }) as edges
            """
            
            result = await driver.execute_query(
                query,
                group_id=user_id,
                user_prefix=f"{user_id}_",
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
                            "id": node["uuid"] if "uuid" in node else str(node.id),
                            "label": node["name"] if "name" in node else "Unknown",
                            "summary": (node["summary"][:200] if "summary" in node and node["summary"] else ""),
                            "created_at": str(node["created_at"]) if "created_at" in node and node["created_at"] else None,
                        }
                    })
                
                # Process edges
                for edge in record["edges"]:
                    if edge and edge.get("source") and edge.get("target"):  # Ensure source/target exist
                        edges.append({
                            "data": {
                                "id": edge["uuid"] if edge.get("uuid") else f"{edge['source']}_{edge['target']}",
                                "source": edge["source"],
                                "target": edge["target"],
                                "label": (edge["fact"][:100] if edge.get("fact") else ""),
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

    async def get_user_files(self, user_id: str) -> list:
        """
        Get list of files and chunk counts.
        """
        try:
            logger.info(f"Getting files for user: {user_id}")
            driver = self.client.driver
            
            query = """
            CALL {
                MATCH (e:Episodic)
                WHERE e.name STARTS WITH $user_prefix AND e.file_name IS NOT NULL
                RETURN e.file_name as file_name, count(e) as chunk_count, max(e.created_at) as last_modified
                
                UNION ALL
                
                MATCH (p:PendingEpisode)
                WHERE p.user_id = $user_id AND p.file_name IS NOT NULL
                RETURN p.file_name as file_name, count(p) as chunk_count, max(p.created_at) as last_modified
            }
            WITH file_name, sum(chunk_count) as total_chunks, max(last_modified) as last_modified
            RETURN file_name, total_chunks, toString(last_modified) as created_at
            ORDER BY last_modified DESC
            """
            
            params = {
                "user_prefix": f"{user_id}_",
                "user_id": user_id,
            }
            
            result = await driver.execute_query(query, **params)
            
            files = []
            if result.records:
                for record in result.records:
                    files.append({
                        "file_name": record["file_name"],
                        "chunk_count": record["total_chunks"],
                        "created_at": record["created_at"]
                    })
            
            return files
        except Exception as e:
            logger.error(f"Error getting files for user {user_id}: {e}")
            raise e

    async def get_user_episodes(self, user_id: str, limit: int = None) -> list:
        """
        Get list of episodes for a user, including pending ones.
        """
        try:
            logger.info(f"Getting episodes for user: {user_id} limit={limit} type={type(limit)}")
            driver = self.client.driver
            
            # Use CALL subquery to properly wrap UNION and apply LIMIT to the final result
            query = """
            CALL {
                // 1. Get processed episodes
                MATCH (e:Episodic)
                WHERE e.name STARTS WITH $user_prefix AND e.file_name IS NULL
                RETURN e.uuid as uuid, e.name as name, toString(e.created_at) as created_at, 
                       e.source_description as source, 
                       coalesce(e.content, e.episode_body, "") as content,
                       'processed' as status
                
                UNION ALL
                
                // 2. Get pending episodes
                MATCH (p:PendingEpisode)
                WHERE p.user_id = $user_id AND p.file_name IS NULL
                RETURN p.uuid as uuid, "pending_" + p.uuid as name, toString(p.created_at) as created_at,
                       p.source as source,
                       p.content as content,
                       'pending' as status
            }
            RETURN uuid, name, created_at, source, content, status
            ORDER BY created_at DESC
            """
            
            params = {
                "user_prefix": f"{user_id}_",
                "user_id": user_id,
                "database_": "neo4j"
            }
            
            if limit is not None and limit > 0:
                query += "\nLIMIT $limit"
                params["limit"] = limit
            
            result = await driver.execute_query(
                query,
                **params
            )
            
            episodes = []
            pending_count = 0
            processed_count = 0
            
            if result.records:
                for record in result.records:
                    if record["status"] == "pending":
                        pending_count += 1
                    else:
                        processed_count += 1
                        
                    episodes.append({
                        "uuid": record["uuid"],
                        "created_at": record["created_at"],
                        "source": record["source"],
                        "content": record["content"],
                        "status": record["status"]
                    })
            
            logger.info(f"Found {len(episodes)} episodes ({processed_count} processed, {pending_count} pending)")
            return episodes
            
        except Exception as e:
            logger.error(f"Error getting episodes for user {user_id}: {e}")
            raise e

    async def delete_file_episodes(self, user_id: str, file_name: str) -> bool:
        """
        Delete all episodes for a specific user and file_name, 
        and cleanup orphaned nodes and edges.
        """
        try:
            logger.info(f"Deleting all episodes for user {user_id} with file_name: {file_name}")
            driver = self.client.driver
            
            # Step 1: Find episodes and identify orphaned entities
            query1 = """
            // Find all episodes matching file_name and user_id
            MATCH (e:Episodic)
            WHERE e.file_name = $file_name AND (e.name STARTS WITH $user_prefix OR e.group_id = $user_id)
            
            // Collect uuid for logging
            WITH e, e.uuid as uuid
            
            // Find all entities mentioned by these episodes
            OPTIONAL MATCH (e)-[:MENTIONS]->(entity:Entity)
            WITH collect(DISTINCT e) as target_episodes, collect(DISTINCT entity) as file_entities
            
            // Delete the episodes first
            FOREACH (ep IN target_episodes | DETACH DELETE ep)
            
            // Check which entities became orphaned (no other episodes mention them)
            WITH file_entities
            UNWIND file_entities as entity
            OPTIONAL MATCH (entity)<-[:MENTIONS]-(other_episode:Episodic)
            WITH entity, count(other_episode) as other_refs
            WHERE other_refs = 0
            
            // Delete orphaned entities
            WITH collect(entity) as orphaned_entities
            FOREACH (orphan IN orphaned_entities | DETACH DELETE orphan)
            
            RETURN size(orphaned_entities) as deleted_entities, size(file_entities) as sampled_entities
            """
            
            result1 = await driver.execute_query(
                query1,
                user_id=user_id,
                user_prefix=f"{user_id}_",
                file_name=file_name,
                database_="neo4j"
            )
            
            deleted_entities = result1.records[0]["deleted_entities"] if result1.records else 0
            
            # Step 2: Cleanup any orphaned RELATES_TO relationships
            query2 = """
            MATCH ()-[r:RELATES_TO]->()
            WITH r, startNode(r) as start_entity, endNode(r) as end_entity
            OPTIONAL MATCH (start_entity)<-[:MENTIONS]-(e1:Episodic)
            OPTIONAL MATCH (end_entity)<-[:MENTIONS]-(e2:Episodic)
            WITH r, count(e1) as start_refs, count(e2) as end_refs
            WHERE start_refs = 0 OR end_refs = 0
            DELETE r
            RETURN count(r) as deleted_edges
            """
            
            result2 = await driver.execute_query(
                query2,
                database_="neo4j"
            )
            
            deleted_edges = result2.records[0]["deleted_edges"] if result2.records else 0
            
            # Step 3: Cleanup PendingEpisodes
            query3 = """
            MATCH (p:PendingEpisode {user_id: $user_id, file_name: $file_name})
            DETACH DELETE p
            RETURN count(p) as pending_deleted
            """
            await driver.execute_query(
                query3,
                user_id=user_id,
                file_name=file_name,
                database_="neo4j"
            )
            
            logger.info(f"Bulk deleted for file '{file_name}': {deleted_entities} entities, {deleted_edges} orphaned edges")
            return True
            
        except Exception as e:
            logger.error(f"Error in bulk deletion for file {file_name}: {e}")
            return False

    async def delete_episode(self, episode_uuid: str) -> bool:
        """
        Delete a specific episode and cleanup orphaned nodes and edges
        
        Args:
            episode_uuid: Episode UUID
            
        Returns:
            True if successful
        """
        try:
            logger.info(f"Deleting episode: {episode_uuid}")
            driver = self.client.driver
            
            # Step 1: Delete episode and orphaned entities
            query1 = """
            // Find the episode to delete
            MATCH (e:Episodic {uuid: $uuid})
            
            // Find all entities mentioned by this episode
            OPTIONAL MATCH (e)-[:MENTIONS]->(entity:Entity)
            WITH e, collect(DISTINCT entity) as episode_entities
            
            // Delete the episode first
            DETACH DELETE e
            
            // Check which entities became orphaned (no other episodes mention them)
            WITH episode_entities
            UNWIND episode_entities as entity
            OPTIONAL MATCH (entity)<-[:MENTIONS]-(other_episode:Episodic)
            WITH entity, count(other_episode) as other_refs
            WHERE other_refs = 0
            
            // Delete orphaned entities (DETACH DELETE removes their RELATES_TO edges too)
            WITH collect(entity) as orphaned_entities
            FOREACH (orphan IN orphaned_entities | DETACH DELETE orphan)
            
            RETURN size(orphaned_entities) as deleted_entities
            """
            
            result1 = await driver.execute_query(
                query1,
                uuid=episode_uuid,
                database_="neo4j"
            )
            
            deleted_entities = result1.records[0]["deleted_entities"] if result1.records else 0
            
            # Step 2: Cleanup any orphaned RELATES_TO relationships
            # (edges that point to non-existent entities or are not connected to any episodes)
            query2 = """
            // Find all RELATES_TO relationships
            MATCH ()-[r:RELATES_TO]->()
            
            // Check if both nodes exist and are mentioned by at least one episode
            WITH r, startNode(r) as start_entity, endNode(r) as end_entity
            OPTIONAL MATCH (start_entity)<-[:MENTIONS]-(e1:Episodic)
            OPTIONAL MATCH (end_entity)<-[:MENTIONS]-(e2:Episodic)
            WITH r, count(e1) as start_refs, count(e2) as end_refs
            
            // Delete relationship if either node is not mentioned by any episode
            WHERE start_refs = 0 OR end_refs = 0
            DELETE r
            
            RETURN count(r) as deleted_edges
            """
            
            result2 = await driver.execute_query(
                query2,
                database_="neo4j"
            )
            
            deleted_edges = result2.records[0]["deleted_edges"] if result2.records else 0
            
            logger.info(f"Deleted episode {episode_uuid}: {deleted_entities} entities, {deleted_edges} orphaned edges")
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
