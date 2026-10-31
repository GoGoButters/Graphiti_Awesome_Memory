"""
Graphiti Client Wrapper - Real SDK Integration

This module provides a wrapper around the graphiti-core Python SDK for
building and querying temporal knowledge graphs.

NOTE: JSON parsing workarounds (CleaningHTTPTransport, _patched_json_loads,
_parse_edge_duplicate_response, _fix_unquoted_json_values, _fix_array_as_object)
exist because graphiti-core's LLM calls don't use structured outputs
(response_format=json_schema). The LLM sometimes returns markdown-wrapped JSON,
YAML-like formats, or truncated responses. These workarounds intercept and fix
responses at the HTTP transport layer.

To remove these workarounds, graphiti-core itself would need to switch to
structured outputs in its prompt library. As of graphiti-core 0.29.x,
this is not supported upstream.
"""

import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from graphiti_core import Graphiti
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config_recipes import (
    NODE_HYBRID_SEARCH_RRF,
    COMBINED_HYBRID_SEARCH_CROSS_ENCODER,
    COMBINED_HYBRID_SEARCH_RRF,
    EDGE_HYBRID_SEARCH_NODE_DISTANCE,
)
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.utils.maintenance import community_operations as _community_ops

from app.core.config import settings
from app.models.schemas import MemoryHit

logger = logging.getLogger(__name__)

LABEL_PROPAGATION_MAX_ROUNDS = 100


def _bounded_label_propagation(projection) -> list[list[str]]:
    """
    Replacement for graphiti's label_propagation. The upstream version updates
    all nodes synchronously and loops `while True` until nothing changes: two
    entities linked by several edges swap labels forever, and since the loop is
    synchronous it blocks the whole event loop (adapter stops answering).
    Same rules, but nodes update in place (asynchronous LPA, converges in
    practice) and the number of rounds is capped.
    """
    from collections import defaultdict

    community_map = {uuid: i for i, uuid in enumerate(projection.keys())}

    for _ in range(LABEL_PROPAGATION_MAX_ROUNDS):
        changed = False
        for uuid, neighbors in projection.items():
            curr_community = community_map[uuid]
            candidates: dict[int, int] = defaultdict(int)
            for neighbor in neighbors:
                neighbor_community = community_map.get(neighbor.node_uuid)
                if neighbor_community is not None:
                    candidates[neighbor_community] += neighbor.edge_count
            ranked = sorted(
                ((count, community) for community, count in candidates.items()),
                reverse=True,
            )
            rank, candidate = ranked[0] if ranked else (0, -1)
            if candidate != -1 and rank > 1:
                new_community = candidate
            else:
                new_community = max(candidate, curr_community)
            if new_community != curr_community:
                community_map[uuid] = new_community
                changed = True
        if not changed:
            break
    else:
        logger.warning(
            f"Label propagation did not converge in {LABEL_PROPAGATION_MAX_ROUNDS} rounds, using current clusters"
        )

    clusters: dict[int, list[str]] = defaultdict(list)
    for uuid, community in community_map.items():
        clusters[community].append(uuid)
    return list(clusters.values())


# get_community_clusters() resolves label_propagation from the module globals
_community_ops.label_propagation = _bounded_label_propagation

import json
import re
import copy
import httpx

_original_json_loads = json.loads


def _parse_edge_duplicate_response(text: str) -> Optional[dict]:
    """
    Parse EdgeDuplicate-like responses from LLM that may be in YAML-like or text format.
    Returns a dict with duplicate_facts, fact_type, contradicted_facts if found, else None.

    Handles formats like:
    - duplicate_facts: []
      fact_type: DEFAULT
      contradicted_facts: [6]
    - []  (No duplicates found)
      Contradicted Facts: []
    - {"duplicate_facts": [], "fact_type": DEFAULT, "contradicted_facts": []}  (unquoted DEFAULT)
    - Duplicate Facts: [] / Contradicted Facts: [0] (space in names)
    """
    result = {"duplicate_facts": [], "fact_type": "DEFAULT", "contradicted_facts": []}

    found_any = False

    # Pattern 1a: YAML-like key: value format (underscore version)
    # Match duplicate_facts: [] or duplicate_facts: [1, 2]
    dup_match = re.search(r"duplicate_facts[:\s]+\[([^\]]*)\]", text, re.IGNORECASE)
    if dup_match:
        found_any = True
        vals = dup_match.group(1).strip()
        if vals:
            result["duplicate_facts"] = [
                int(x.strip()) for x in vals.split(",") if x.strip().isdigit()
            ]

    # Pattern 1b: Space version - "Duplicate Facts: []"
    if not dup_match:
        dup_match2 = re.search(
            r"duplicate\s+facts[:\s]+\[([^\]]*)\]", text, re.IGNORECASE
        )
        if dup_match2:
            found_any = True
            vals = dup_match2.group(1).strip()
            if vals:
                result["duplicate_facts"] = [
                    int(x.strip()) for x in vals.split(",") if x.strip().isdigit()
                ]

    # Match fact_type: DEFAULT or fact_type: "DEFAULT" or "fact_type": DEFAULT
    type_match = re.search(r'fact_type[:\s]+["\']?(\w+)["\']?', text, re.IGNORECASE)
    if type_match:
        found_any = True
        result["fact_type"] = type_match.group(1).upper()

    # Pattern 1b for type: "Fact Type: DEFAULT"
    if not type_match:
        type_match2 = re.search(
            r'fact\s+type[:\s]+["\']?(\w+)["\']?', text, re.IGNORECASE
        )
        if type_match2:
            found_any = True
            result["fact_type"] = type_match2.group(1).upper()

    # Pattern 2a: Match contradicted_facts: [] or contradicted_facts: [6, 7] (underscore)
    contra_match = re.search(
        r"contradicted_facts[:\s]+\[([^\]]*)\]", text, re.IGNORECASE
    )
    if contra_match:
        found_any = True
        vals = contra_match.group(1).strip()
        if vals:
            result["contradicted_facts"] = [
                int(x.strip()) for x in vals.split(",") if x.strip().isdigit()
            ]

    # Pattern 2b: Space version - "Contradicted Facts: [0]"
    if not contra_match:
        contra_match2 = re.search(
            r"contradicted\s+facts[:\s]+\[([^\]]*)\]", text, re.IGNORECASE
        )
        if contra_match2:
            found_any = True
            vals = contra_match2.group(1).strip()
            if vals:
                result["contradicted_facts"] = [
                    int(x.strip()) for x in vals.split(",") if x.strip().isdigit()
                ]

    # Pattern 3: Check for "No duplicates found" or similar text patterns
    if "no duplicates" in text.lower() or "no duplicate" in text.lower():
        found_any = True
        result["duplicate_facts"] = []

    if "no contradictions" in text.lower() or "no contradiction" in text.lower():
        found_any = True
        result["contradicted_facts"] = []

    # Pattern 4: Handle structured response sections like "1. DUPLICATE DETECTION:", etc.
    # This handles free-form responses that describe results in sections
    if "duplicate detection" in text.lower():
        found_any = True
        # Look for idx values or empty list mentions
        idx_match = re.search(r"idx\s*values?[:\s]+\[([^\]]*)\]", text, re.IGNORECASE)
        if idx_match:
            vals = idx_match.group(1).strip()
            if vals:
                result["duplicate_facts"] = [
                    int(x.strip()) for x in vals.split(",") if x.strip().isdigit()
                ]
            else:
                result["duplicate_facts"] = []

    if "contradiction detection" in text.lower():
        found_any = True
        # Look for "contradicts" or index mentions
        contra_idx_match = re.search(
            r"contradicts?\s+(?:the\s+)?(?:first\s+)?fact\s*\(?\s*idx\s*(\d+)",
            text,
            re.IGNORECASE,
        )
        if contra_idx_match:
            result["contradicted_facts"] = [int(contra_idx_match.group(1))]
        # Also try: "Contradicted facts: [0]"
        contra_idx_match2 = re.search(
            r"contradicted\s*facts[:\s]+\[([^\]]*)\]", text, re.IGNORECASE
        )
        if contra_idx_match2:
            vals = contra_idx_match2.group(1).strip()
            if vals:
                result["contradicted_facts"] = [
                    int(x.strip()) for x in vals.split(",") if x.strip().isdigit()
                ]

    return result if found_any else None


def _fix_array_as_object(s: str) -> str:
    """
    Fix malformed JSON where array brackets are used instead of object braces.
    E.g.: ["duplicate_facts": [], ...] -> {"duplicate_facts": [], ...}

    This happens when LLM returns EdgeDuplicate in invalid format.
    """
    s = s.strip()
    # Check if it looks like an array with key:value pairs
    if s.startswith("[") and s.endswith("]"):
        # Check if it contains key: value pattern (indicates object, not array)
        if re.search(r'"\w+":\s*[\[\{"\d]', s):
            # Replace outer brackets with braces
            return "{" + s[1:-1] + "}"
    return s


def _fix_unquoted_json_values(s: str) -> str:
    """
    Fix JSON with unquoted string values like DEFAULT, true, false, null.
    E.g.: {"fact_type": DEFAULT} -> {"fact_type": "DEFAULT"}
    """

    # Pattern: "key": WORD (where WORD is not a number, true, false, null, or already quoted)
    # This pattern looks for: "key": followed by an unquoted word that's not a JSON literal
    def replace_unquoted(match):
        key = match.group(1)
        value = match.group(2)
        # Check if value is a JSON literal or number
        if value.lower() in ("true", "false", "null") or re.match(
            r"^-?\d+\.?\d*$", value
        ):
            return f'"{key}": {value}'
        # It's an unquoted string, add quotes
        return f'"{key}": "{value}"'

    # Match "key": WORD patterns (WORD is alphanumeric, not followed by quote)
    pattern = r'"(\w+)":\s*([A-Za-z_][A-Za-z0-9_]*)\b(?!["\'])'
    return re.sub(pattern, replace_unquoted, s)


def _patched_json_loads(s, *args, **kwargs):
    """Patched json.loads that cleans markdown and extracts JSON before parsing.

    Also handles:
    - YAML-like EdgeDuplicate responses from LLM models
    - Unquoted string values in JSON (e.g., DEFAULT instead of "DEFAULT")
    - Plain text that needs to be extracted into structured format
    """
    if isinstance(s, str):
        original_s = s

        # 1. Strip markdown code blocks
        if "```" in s:
            match = re.search(r"```(?:\w+)?\s*(.*?)```", s, re.DOTALL)
            if match:
                s = match.group(1).strip()
            else:
                s = s.replace("```json", "").replace("```", "").strip()

        # 2. EARLY CHECK: If this looks like EdgeDuplicate response, parse it FIRST
        # This must happen BEFORE JSON extraction because YAML-like responses start with []
        edge_dup_keywords = [
            "duplicate_facts",
            "contradicted_facts",
            "fact_type",
            "duplicate facts",
            "contradicted facts",
            "fact type",
            "duplicate detection",
            "contradiction detection",
        ]
        if any(kw in s.lower() for kw in edge_dup_keywords):
            edge_dup_result = _parse_edge_duplicate_response(s)
            if edge_dup_result:
                logger.info(
                    "json.loads patch: converted EdgeDuplicate YAML-like response to JSON"
                )
                return edge_dup_result

        # 3. Try to extract JSON structure
        first_brace = s.find("{")
        first_bracket = s.find("[")

        start_idx = -1
        end_char = ""

        if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
            start_idx = first_brace
            end_char = "}"
        elif first_bracket != -1:
            start_idx = first_bracket
            end_char = "]"

        extracted_json = None
        if start_idx != -1:
            end_idx = s.rfind(end_char)
            if end_idx != -1 and end_idx > start_idx:
                extracted_json = s[start_idx : end_idx + 1]

        # 4. Try to parse extracted JSON
        if extracted_json:
            try:
                # First try direct parse
                return _original_json_loads(extracted_json, *args, **kwargs)
            except json.JSONDecodeError:
                # Try fixing unquoted values (e.g., DEFAULT instead of "DEFAULT")
                try:
                    fixed_json = _fix_unquoted_json_values(extracted_json)
                    result = _original_json_loads(fixed_json, *args, **kwargs)
                    logger.info("json.loads patch: fixed unquoted values in JSON")
                    return result
                except json.JSONDecodeError:
                    pass

        # 5. If we extracted JSON but couldn't parse it, try the original extraction logic
        if extracted_json:
            s = extracted_json

        if s != original_s:
            logger.info("json.loads patch: cleaned input")

    return _original_json_loads(s, *args, **kwargs)


json.loads = _patched_json_loads


class RemoteRerankerClient(CrossEncoderClient):
    """
    Custom CrossEncoder client for remote reranker servers (e.g. llama.cpp, Jina).
    Supports both llama.cpp (/rerank) and Jina/Cohere (/v1/rerank) endpoints.
    """

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        # Determine the correct endpoint based on base_url format
        # llama.cpp uses /rerank directly
        # Jina/Cohere use /v1/rerank
        if self.base_url.endswith("/rerank"):
            # llama.cpp style: base_url already contains the endpoint
            self.rerank_url = self.base_url
        elif self.base_url.endswith("/v1"):
            # /v1 suffix provided, append /rerank
            self.rerank_url = f"{self.base_url}/rerank"
        else:
            # Default: assume Jina/Cohere style, add /v1/rerank
            self.rerank_url = f"{self.base_url}/v1/rerank"

        self.api_key = api_key
        self.model = model
        self.client = httpx.AsyncClient(timeout=30.0)
        logger.info(
            f"RemoteRerankerClient initialized with endpoint: {self.rerank_url}"
        )

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        if not passages:
            return []

        # Configuration for avoiding 400 Bad Request due to context length
        MAX_DOC_LENGTH = 500  # Max characters per document
        MAX_BATCH_SIZE = 50  # Max documents per request

        # Truncate long documents to avoid exceeding model context
        truncated_passages = [
            p[:MAX_DOC_LENGTH] if len(p) > MAX_DOC_LENGTH else p for p in passages
        ]

        url = self.rerank_url
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            # Process in batches if too many documents
            if len(truncated_passages) <= MAX_BATCH_SIZE:
                # Single batch - simple case
                payload = {
                    "model": self.model,
                    "query": query,
                    "documents": truncated_passages,
                    "top_n": len(truncated_passages),
                }
                logger.info(f"Reranking {len(truncated_passages)} passages via {url}")
                response = await self.client.post(url, headers=headers, json=payload)
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                # Map results back to original passages (not truncated)
                ranked = []
                for res in results:
                    idx = res.get("index")
                    score = res.get("relevance_score")
                    if idx is not None and 0 <= idx < len(passages):
                        ranked.append((passages[idx], float(score)))

                logger.info(
                    f"Rerank success, top score: {ranked[0][1] if ranked else 'none'}"
                )
                return ranked
            else:
                # Multiple batches - aggregate results
                logger.info(
                    f"Reranking {len(truncated_passages)} passages in {(len(truncated_passages) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE} batches"
                )
                all_results = []

                for batch_start in range(0, len(truncated_passages), MAX_BATCH_SIZE):
                    batch_end = min(
                        batch_start + MAX_BATCH_SIZE, len(truncated_passages)
                    )
                    batch = truncated_passages[batch_start:batch_end]

                    payload = {
                        "model": self.model,
                        "query": query,
                        "documents": batch,
                        "top_n": len(batch),
                    }

                    logger.info(
                        f"Reranking batch {batch_start // MAX_BATCH_SIZE + 1}: {len(batch)} passages"
                    )
                    response = await self.client.post(
                        url, headers=headers, json=payload
                    )
                    response.raise_for_status()

                    data = response.json()
                    batch_results = data.get("results", [])

                    # Adjust indices to global position and use original passages
                    for res in batch_results:
                        local_idx = res.get("index")
                        score = res.get("relevance_score")
                        if local_idx is not None:
                            global_idx = batch_start + local_idx
                            if 0 <= global_idx < len(passages):
                                all_results.append((passages[global_idx], float(score)))

                # Sort all results by score descending
                all_results.sort(key=lambda x: x[1], reverse=True)

                logger.info(
                    f"Rerank success (batched), top score: {all_results[0][1] if all_results else 'none'}"
                )
                return all_results

        except Exception as e:
            logger.error(f"Remote reranking failed: {e}")
            # Log document stats for debugging
            doc_lengths = [len(p) for p in passages]
            logger.error(
                f"Rerank debug: query_len={len(query)}, num_docs={len(passages)}, "
                f"doc_lengths: min={min(doc_lengths)}, max={max(doc_lengths)}, avg={sum(doc_lengths) // len(doc_lengths)}"
            )
            raise e


class GraphitiWrapper:
    """
    Wrapper for Graphiti SDK that integrates with Neo4j.
    Handles episode creation, search, and graph retrieval.
    """

    def __init__(self):
        """Initialize Graphiti client with Neo4j connection and custom LLM/Embedder"""
        # PendingEpisode uuids queued or running in this process
        self._inflight: set = set()
        self._center_cache: Dict[str, Any] = {}  # user_id -> (center uuid, ts)
        self._community_jobs: Dict[str, Dict[str, Any]] = {}
        self._episode_semaphore = None
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

            logger.info(
                f"SEMAPHORE_LIMIT set to: {os.environ.get('SEMAPHORE_LIMIT', '10')}"
            )
            logger.info(
                f"MAX_REFLEXION_ITERATIONS set to: {os.environ.get('MAX_REFLEXION_ITERATIONS', '3')}"
            )

            from openai import AsyncOpenAI
            from graphiti_core.llm_client.openai_client import OpenAIClient
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.embedder.openai import (
                OpenAIEmbedder,
                OpenAIEmbedderConfig,
            )
            from graphiti_core.cross_encoder.openai_reranker_client import (
                OpenAIRerankerClient,
            )

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
                            if (
                                400 <= response.status_code < 500
                                and response.status_code != 429
                            ):
                                logger.error(
                                    f"Request failed with status {response.status_code} (Client Error). Not retrying."
                                )
                                # Try to read error body for debugging
                                try:
                                    await response.aread()
                                    error_body = response.content.decode(
                                        "utf-8", errors="ignore"
                                    )
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
                                error_body = response.content.decode(
                                    "utf-8", errors="ignore"
                                )
                            except:
                                pass

                            if elapsed >= TIMEOUT:
                                logger.error(
                                    f"Request failed after {TIMEOUT}s retrying. Final status: {response.status_code}. Error: {error_body}"
                                )
                                break

                            logger.warning(
                                f"Request failed with status {response.status_code}. Error: {error_body}. Retrying in {RETRY_INTERVAL}s... (Elapsed: {int(elapsed)}s)"
                            )
                            await asyncio.sleep(RETRY_INTERVAL)

                        except Exception as e:
                            # Handle network errors
                            elapsed = time.time() - start_time
                            if elapsed >= TIMEOUT:
                                logger.error(
                                    f"Request failed after {TIMEOUT}s retrying. Error: {e}"
                                )
                                raise e

                            logger.warning(
                                f"Request failed with error {e}. Retrying in {RETRY_INTERVAL}s... (Elapsed: {int(elapsed)}s)"
                            )
                            await asyncio.sleep(RETRY_INTERVAL)

                    # Intercept response
                    if response.status_code == 200:
                        try:
                            # Read the response body
                            await response.aread()

                            # Log first 500 chars of response for debugging
                            logger.info(
                                f"Response body preview: {response.content[:500]}"
                            )

                            try:
                                data = json.loads(response.content)
                            except json.JSONDecodeError:
                                logger.warning("Response is not valid JSON")
                                return response

                            if (
                                isinstance(data, dict)
                                and "choices" in data
                                and len(data["choices"]) > 0
                            ):
                                content = data["choices"][0]["message"]["content"]
                                if content:
                                    logger.info(f"LLM Raw Response (HTTP): {content}")
                                    original_content = content

                                    # 1. Clean Markdown/XML
                                    if "```" in content:
                                        match = re.search(
                                            r"```(?:\w+)?\s*(.*?)```",
                                            content,
                                            re.DOTALL,
                                        )
                                        if match:
                                            content = match.group(1).strip()
                                        else:
                                            content = (
                                                content.replace("```json", "")
                                                .replace("```", "")
                                                .strip()
                                            )

                                    # EARLY CHECK: If this looks like EdgeDuplicate response, parse it FIRST
                                    # This must happen BEFORE JSON extraction because YAML-like responses
                                    # contain [] which would be extracted incorrectly
                                    edge_dup_keywords_early = [
                                        "duplicate_facts",
                                        "contradicted_facts",
                                        "fact_type",
                                        "duplicate facts",
                                        "contradicted facts",
                                        "fact type",
                                        "duplicate detection",
                                        "contradiction detection",
                                        "duplicated_facts",
                                    ]
                                    if any(
                                        kw in content.lower()
                                        for kw in edge_dup_keywords_early
                                    ):
                                        # First, try to parse as YAML-like format
                                        edge_dup_result = (
                                            _parse_edge_duplicate_response(content)
                                        )
                                        if edge_dup_result:
                                            logger.info(
                                                "Fixing JSON: Early EdgeDuplicate detection (standard path) - converting YAML to JSON"
                                            )
                                            content = json.dumps(edge_dup_result)
                                            # Skip JSON extraction, go directly to response modification
                                            data["choices"][0]["message"]["content"] = (
                                                content
                                            )
                                            new_body = json.dumps(data).encode("utf-8")
                                            return httpx.Response(
                                                status_code=response.status_code,
                                                headers=response.headers,
                                                content=new_body,
                                                request=request,
                                                extensions=response.extensions,
                                            )

                                        # If not YAML-like, try to fix malformed JSON
                                        # Handle: ["key": value] -> {"key": value}
                                        fixed_content = _fix_array_as_object(content)
                                        # Handle: {"fact_type": DEFAULT} -> {"fact_type": "DEFAULT"}
                                        fixed_content = _fix_unquoted_json_values(
                                            fixed_content
                                        )

                                        if fixed_content != content:
                                            try:
                                                # Verify it's valid JSON now
                                                json.loads(fixed_content)
                                                logger.info(
                                                    "Fixing JSON: Early EdgeDuplicate detection (standard path) - fixed malformed JSON"
                                                )
                                                data["choices"][0]["message"][
                                                    "content"
                                                ] = fixed_content
                                                new_body = json.dumps(data).encode(
                                                    "utf-8"
                                                )
                                                return httpx.Response(
                                                    status_code=response.status_code,
                                                    headers=response.headers,
                                                    content=new_body,
                                                    request=request,
                                                    extensions=response.extensions,
                                                )
                                            except json.JSONDecodeError:
                                                # Still not valid, continue with normal processing
                                                pass

                                    # 2. Extract JSON structure (find first { or [ and last } or ])
                                    start_brace = content.find("{")
                                    start_bracket = content.find("[")

                                    start_idx = -1
                                    end_char = ""

                                    if start_brace != -1 and (
                                        start_bracket == -1
                                        or start_brace < start_bracket
                                    ):
                                        start_idx = start_brace
                                        end_char = "}"
                                    elif start_bracket != -1:
                                        start_idx = start_bracket
                                        end_char = "]"
                                    if start_idx != -1:
                                        end_idx = content.rfind(end_char)
                                        if end_idx != -1 and end_idx > start_idx:
                                            content = content[start_idx : end_idx + 1]

                                    # 3. Fix List vs Object
                                    try:
                                        # Try to parse to check structure
                                        parsed = json.loads(content)
                                        modified = False

                                        # If parsed is just a string, it's likely a summary that needs wrapping
                                        if isinstance(parsed, str):
                                            logger.info(
                                                "Fixing JSON: Parsed content is a string, wrapping in 'summary' with empty entities"
                                            )
                                            parsed = {
                                                "summary": parsed,
                                                "extracted_entities": [],
                                            }
                                            modified = True

                                        elif isinstance(parsed, list):
                                            # Check if original content contains EdgeDuplicate keywords
                                            # This handles cases like: "[]  (No duplicates found)\n\nContradicted Facts: []"
                                            edge_dup_keywords = [
                                                "duplicate_facts",
                                                "contradicted_facts",
                                                "fact_type",
                                                "duplicate facts",
                                                "contradicted facts",
                                                "fact type",
                                                "duplicate detection",
                                                "contradiction detection",
                                            ]
                                            if any(
                                                kw in original_content.lower()
                                                for kw in edge_dup_keywords
                                            ):
                                                edge_dup_result = (
                                                    _parse_edge_duplicate_response(
                                                        original_content
                                                    )
                                                )
                                                if edge_dup_result:
                                                    logger.info(
                                                        "Fixing JSON: Detected EdgeDuplicate format in original content (standard path)"
                                                    )
                                                    content = json.dumps(
                                                        edge_dup_result
                                                    )
                                                    modified = True
                                                    parsed = edge_dup_result  # Already a dict now
                                            elif (
                                                len(parsed) > 0
                                                and isinstance(parsed[0], dict)
                                                and (
                                                    "source_entity_id" in parsed[0]
                                                    or "relation_type" in parsed[0]
                                                )
                                            ):
                                                # Detect if this is a list of edges
                                                logger.info(
                                                    "Fixing JSON: List found (edges detected), wrapping in 'edges'"
                                                )
                                                parsed = {
                                                    "edges": parsed,
                                                    "extracted_entities": [],
                                                }
                                                modified = True
                                            else:
                                                # Default: wrap as entities
                                                logger.info(
                                                    "Fixing JSON: List found (entities detected), wrapping in 'extracted_entities'"
                                                )
                                                parsed = {
                                                    "extracted_entities": parsed,
                                                    "edges": [],
                                                }
                                                modified = True
                                        elif (
                                            isinstance(parsed, dict)
                                            and "entities" in parsed
                                        ):
                                            logger.info(
                                                "Fixing JSON: Renaming 'entities' to 'extracted_entities'"
                                            )
                                            parsed["extracted_entities"] = parsed.pop(
                                                "entities"
                                            )
                                            modified = True

                                        # Fix facts -> edges
                                        if (
                                            isinstance(parsed, dict)
                                            and "facts" in parsed
                                        ):
                                            logger.info(
                                                "Fixing JSON: Renaming 'facts' to 'edges'"
                                            )
                                            parsed["edges"] = parsed.pop("facts")
                                            modified = True

                                        # Fix entity_name -> name and entity -> name in extracted_entities
                                        if (
                                            isinstance(parsed, dict)
                                            and "extracted_entities" in parsed
                                        ):
                                            for entity in parsed["extracted_entities"]:
                                                if isinstance(entity, dict):
                                                    if "entity_name" in entity:
                                                        entity["name"] = entity.pop(
                                                            "entity_name"
                                                        )
                                                        modified = True
                                                    elif "entity" in entity:
                                                        entity["name"] = entity.pop(
                                                            "entity"
                                                        )
                                                        modified = True

                                            # Fix NodeResolutions: extracted_entities -> entity_resolutions
                                            # If the entities contain 'duplicates', it's a resolution result
                                            entities = parsed["extracted_entities"]
                                            if (
                                                entities
                                                and isinstance(entities, list)
                                                and len(entities) > 0
                                            ):
                                                if (
                                                    isinstance(entities[0], dict)
                                                    and "duplicates" in entities[0]
                                                ):
                                                    parsed["entity_resolutions"] = (
                                                        parsed.pop("extracted_entities")
                                                    )
                                                    logger.info(
                                                        "Fixing JSON: Renamed 'extracted_entities' to 'entity_resolutions' (detected resolution format)"
                                                    )
                                                    modified = True

                                            # Fix extracted_edges -> edges
                                            if (
                                                isinstance(parsed, dict)
                                                and "extracted_edges" in parsed
                                            ):
                                                parsed["edges"] = parsed.pop(
                                                    "extracted_edges"
                                                )
                                                logger.info(
                                                    "Fixing JSON: Renamed 'extracted_edges' to 'edges'"
                                                )
                                                modified = True

                                            if modified:
                                                content = json.dumps(parsed)

                                    except json.JSONDecodeError:
                                        # Attempt to repair truncated JSON
                                        # LLMs often cut off at max tokens, leaving unclosed lists/objects
                                        if content.strip().startswith(
                                            "{"
                                        ) or content.strip().startswith("["):
                                            repaired = False
                                            # Common suffixes to try
                                            suffixes = [
                                                "}",
                                                "]",
                                                "}}",
                                                "]}",
                                                "}]",
                                                "}}}",
                                                "}}]",
                                                "}]}",
                                                "]}}",
                                                "]}]",
                                                "]]}",
                                                "]]]",
                                                '"}',
                                                '"]',
                                                '"]}',
                                                '"]}]',
                                                '"]}\n]}',
                                                "}\n]}",
                                            ]
                                            for suffix in suffixes:
                                                try:
                                                    temp_content = content + suffix
                                                    json.loads(temp_content)
                                                    content = temp_content
                                                    logger.info(
                                                        f"Fixing JSON: Repaired truncated JSON with suffix '{suffix}'"
                                                    )
                                                    repaired = True
                                                    break
                                                except json.JSONDecodeError:
                                                    continue

                                    # If JSON parsing fails (and repair failed), check if it's plain text that needs wrapping
                                    if (
                                        content
                                        and not content.strip().startswith("{")
                                        and not content.strip().startswith("[")
                                    ):
                                        # Check if this looks like EdgeDuplicate response (YAML-like format)
                                        edge_dup_keywords = [
                                            "duplicate_facts",
                                            "contradicted_facts",
                                            "fact_type",
                                        ]
                                        if any(
                                            kw in content.lower()
                                            for kw in edge_dup_keywords
                                        ):
                                            edge_dup_result = (
                                                _parse_edge_duplicate_response(content)
                                            )
                                            if edge_dup_result:
                                                logger.info(
                                                    "Fixing JSON: Converted EdgeDuplicate YAML-like response to JSON"
                                                )
                                                content = json.dumps(edge_dup_result)
                                        else:
                                            # Wrap plain text - include both extracted_entities and edges for compatibility
                                            logger.info(
                                                "Fixing JSON: Wrapping plain text in summary object with empty entities/edges"
                                            )
                                            content = json.dumps(
                                                {
                                                    "summary": content.strip(),
                                                    "extracted_entities": [],
                                                    "edges": [],
                                                }
                                            )

                                    if content != original_content:
                                        logger.info(
                                            f"LLM Cleaned Response (HTTP): {content}"
                                        )
                                        data["choices"][0]["message"]["content"] = (
                                            content
                                        )

                                        # Re-encode response
                                        new_body = json.dumps(data).encode("utf-8")

                                        return httpx.Response(
                                            status_code=response.status_code,
                                            headers=response.headers,
                                            content=new_body,
                                            request=request,
                                            extensions=response.extensions,
                                        )

                            # Handle non-standard format (e.g., LiteLLM with 'output' field)
                            elif (
                                isinstance(data, dict)
                                and "output" in data
                                and len(data["output"]) > 0
                            ):
                                # For reasoning models, output array contains:
                                # [{"type": "reasoning", ...}, {"type": "message", ...}]
                                # We need to extract ONLY the "message" type, skip "reasoning"

                                content = None
                                output_index = (
                                    0  # Track which output we use for logging
                                )

                                # Try to find message-type output (skip reasoning)
                                for idx, output_item in enumerate(data["output"]):
                                    if isinstance(output_item, dict):
                                        item_type = output_item.get("type", "unknown")

                                        # Skip reasoning output
                                        if item_type == "reasoning":
                                            logger.info(
                                                f"Skipping reasoning output at index {idx}"
                                            )
                                            continue

                                        # Extract content from message-type output
                                        if (
                                            "content" in output_item
                                            and len(output_item["content"]) > 0
                                        ):
                                            if (
                                                isinstance(
                                                    output_item["content"][0], dict
                                                )
                                                and "text" in output_item["content"][0]
                                            ):
                                                content = output_item["content"][0][
                                                    "text"
                                                ]
                                                output_index = idx
                                                logger.info(
                                                    f"Using output[{idx}] (type: {item_type})"
                                                )
                                                break

                                # Fallback: if no message found, use first output (old behavior)
                                if content is None:
                                    try:
                                        content = data["output"][0]["content"][0][
                                            "text"
                                        ]
                                        output_index = 0
                                        logger.warning(
                                            "No message-type output found, using output[0] as fallback"
                                        )
                                    except (KeyError, IndexError, TypeError) as e:
                                        logger.error(
                                            f"Failed to extract content from output: {e}"
                                        )
                                        return response

                                try:
                                    if content:
                                        logger.info(
                                            f"LLM Raw Response (HTTP, non-standard): {content}"
                                        )
                                        original_content = content

                                        # Clean markdown
                                        if "```" in content:
                                            match = re.search(
                                                r"```(?:\w+)?\s*(.*?)```",
                                                content,
                                                re.DOTALL,
                                            )
                                            if match:
                                                content = match.group(1).strip()
                                            else:
                                                content = (
                                                    content.replace("```json", "")
                                                    .replace("```", "")
                                                    .strip()
                                                )

                                        # EARLY CHECK: If this looks like EdgeDuplicate response, parse it FIRST
                                        # This must happen BEFORE JSON extraction because YAML-like responses
                                        # contain [] which would be extracted incorrectly
                                        edge_dup_keywords_early = [
                                            "duplicate_facts",
                                            "contradicted_facts",
                                            "fact_type",
                                            "duplicate facts",
                                            "contradicted facts",
                                            "fact type",
                                            "duplicate detection",
                                            "contradiction detection",
                                            "duplicated_facts",
                                        ]
                                        if any(
                                            kw in content.lower()
                                            for kw in edge_dup_keywords_early
                                        ):
                                            # First, try to parse as YAML-like format
                                            edge_dup_result = (
                                                _parse_edge_duplicate_response(content)
                                            )
                                            if edge_dup_result:
                                                logger.info(
                                                    "Fixing JSON: Early EdgeDuplicate detection (non-standard path) - converting YAML to JSON"
                                                )
                                                content = json.dumps(edge_dup_result)
                                                # Skip JSON extraction, go directly to response modification
                                                data["output"][output_index]["content"][
                                                    0
                                                ]["text"] = content
                                                new_body = json.dumps(data).encode(
                                                    "utf-8"
                                                )
                                                return httpx.Response(
                                                    status_code=response.status_code,
                                                    headers=response.headers,
                                                    content=new_body,
                                                    request=request,
                                                    extensions=response.extensions,
                                                )

                                            # If not YAML-like, try to fix malformed JSON
                                            # Handle: ["key": value] -> {"key": value}
                                            fixed_content = _fix_array_as_object(
                                                content
                                            )
                                            # Handle: {"fact_type": DEFAULT} -> {"fact_type": "DEFAULT"}
                                            fixed_content = _fix_unquoted_json_values(
                                                fixed_content
                                            )

                                            if fixed_content != content:
                                                try:
                                                    # Verify it's valid JSON now
                                                    json.loads(fixed_content)
                                                    logger.info(
                                                        "Fixing JSON: Early EdgeDuplicate detection (non-standard path) - fixed malformed JSON"
                                                    )
                                                    data["output"][output_index][
                                                        "content"
                                                    ][0]["text"] = fixed_content
                                                    new_body = json.dumps(data).encode(
                                                        "utf-8"
                                                    )
                                                    return httpx.Response(
                                                        status_code=response.status_code,
                                                        headers=response.headers,
                                                        content=new_body,
                                                        request=request,
                                                        extensions=response.extensions,
                                                    )
                                                except json.JSONDecodeError:
                                                    # Still not valid, continue with normal processing
                                                    pass

                                        # Extract JSON
                                        start_brace = content.find("{")
                                        start_bracket = content.find("[")

                                        start_idx = -1
                                        end_char = ""

                                        if start_brace != -1 and (
                                            start_bracket == -1
                                            or start_brace < start_bracket
                                        ):
                                            start_idx = start_brace
                                            end_char = "}"
                                        elif start_bracket != -1:
                                            start_idx = start_bracket
                                            end_char = "]"

                                        if start_idx != -1:
                                            end_idx = content.rfind(end_char)
                                            if end_idx != -1 and end_idx > start_idx:
                                                content = content[
                                                    start_idx : end_idx + 1
                                                ]

                                        # Fix List vs Object
                                        try:
                                            parsed = json.loads(content)
                                            modified = False

                                            if isinstance(parsed, list):
                                                # Check if original content (before extraction) contains EdgeDuplicate keywords
                                                # This handles cases like: "[]  (No duplicates found)\n\nContradicted Facts: []"
                                                edge_dup_keywords = [
                                                    "duplicate_facts",
                                                    "contradicted_facts",
                                                    "fact_type",
                                                    "duplicate facts",
                                                    "contradicted facts",
                                                    "fact type",
                                                    "duplicate detection",
                                                    "contradiction detection",
                                                ]
                                                if any(
                                                    kw in original_content.lower()
                                                    for kw in edge_dup_keywords
                                                ):
                                                    edge_dup_result = (
                                                        _parse_edge_duplicate_response(
                                                            original_content
                                                        )
                                                    )
                                                    if edge_dup_result:
                                                        logger.info(
                                                            "Fixing JSON: Detected EdgeDuplicate format in original content (LiteLLM path)"
                                                        )
                                                        content = json.dumps(
                                                            edge_dup_result
                                                        )
                                                        modified = True
                                                        parsed = edge_dup_result  # Already a dict now
                                                elif (
                                                    len(parsed) > 0
                                                    and isinstance(parsed[0], dict)
                                                    and (
                                                        "source_entity_id" in parsed[0]
                                                        or "relation_type" in parsed[0]
                                                    )
                                                ):
                                                    # Detect if this is a list of edges
                                                    logger.info(
                                                        "Fixing JSON: List found (edges detected), wrapping in 'edges'"
                                                    )
                                                    parsed = {
                                                        "edges": parsed,
                                                        "extracted_entities": [],
                                                    }
                                                    modified = True
                                                else:
                                                    # Default: wrap as entities
                                                    logger.info(
                                                        "Fixing JSON: List found (entities detected), wrapping in 'extracted_entities'"
                                                    )
                                                    parsed = {
                                                        "extracted_entities": parsed,
                                                        "edges": [],
                                                    }
                                                    modified = True
                                            elif (
                                                isinstance(parsed, dict)
                                                and "entities" in parsed
                                            ):
                                                logger.info(
                                                    "Fixing JSON: Renaming 'entities' to 'extracted_entities'"
                                                )
                                                parsed["extracted_entities"] = (
                                                    parsed.pop("entities")
                                                )
                                                modified = True

                                            # Fix facts -> edges
                                            if (
                                                isinstance(parsed, dict)
                                                and "facts" in parsed
                                            ):
                                                logger.info(
                                                    "Fixing JSON: Renaming 'facts' to 'edges'"
                                                )
                                                parsed["edges"] = parsed.pop("facts")
                                                modified = True

                                            # Fix entity_name -> name and entity -> name in extracted_entities
                                            if (
                                                isinstance(parsed, dict)
                                                and "extracted_entities" in parsed
                                            ):
                                                for entity in parsed[
                                                    "extracted_entities"
                                                ]:
                                                    if isinstance(entity, dict):
                                                        if "entity_name" in entity:
                                                            entity["name"] = entity.pop(
                                                                "entity_name"
                                                            )
                                                            modified = True
                                                        elif "entity" in entity:
                                                            entity["name"] = entity.pop(
                                                                "entity"
                                                            )
                                                            modified = True

                                                # Fix NodeResolutions: extracted_entities -> entity_resolutions
                                                entities = parsed["extracted_entities"]
                                                if (
                                                    entities
                                                    and isinstance(entities, list)
                                                    and len(entities) > 0
                                                ):
                                                    if (
                                                        isinstance(entities[0], dict)
                                                        and "duplicates" in entities[0]
                                                    ):
                                                        parsed["entity_resolutions"] = (
                                                            parsed.pop(
                                                                "extracted_entities"
                                                            )
                                                        )
                                                        logger.info(
                                                            "Fixing JSON: Renamed 'extracted_entities' to 'entity_resolutions' (detected resolution format)"
                                                        )
                                                        modified = True

                                            # Fix extracted_edges -> edges
                                            if (
                                                isinstance(parsed, dict)
                                                and "extracted_edges" in parsed
                                            ):
                                                parsed["edges"] = parsed.pop(
                                                    "extracted_edges"
                                                )
                                                logger.info(
                                                    "Fixing JSON: Renamed 'extracted_edges' to 'edges'"
                                                )
                                                modified = True

                                            if modified:
                                                content = json.dumps(parsed)

                                        except json.JSONDecodeError:
                                            # Attempt to repair truncated JSON
                                            if content.strip().startswith(
                                                "{"
                                            ) or content.strip().startswith("["):
                                                repaired = False
                                                suffixes = [
                                                    "}",
                                                    "]",
                                                    "}}",
                                                    "]}",
                                                    "}]",
                                                    "}}}",
                                                    "}}]",
                                                    "}]}",
                                                    "]}}",
                                                    "]}]",
                                                    "]]}",
                                                    "]]]",
                                                    '"}',
                                                    '"]',
                                                    '"]}',
                                                    '"]}]',
                                                    '"]}\n]}',
                                                    "}\n]}",
                                                ]
                                                for suffix in suffixes:
                                                    try:
                                                        temp_content = content + suffix
                                                        json.loads(temp_content)
                                                        content = temp_content
                                                        logger.info(
                                                            f"Fixing JSON: Repaired truncated JSON with suffix '{suffix}'"
                                                        )
                                                        repaired = True
                                                        break
                                                    except json.JSONDecodeError:
                                                        continue

                                        # If JSON parsing fails (and repair failed), check if it's plain text that needs wrapping
                                        if (
                                            content
                                            and not content.strip().startswith("{")
                                            and not content.strip().startswith("[")
                                        ):
                                            # Check if this looks like EdgeDuplicate response (YAML-like format)
                                            edge_dup_keywords = [
                                                "duplicate_facts",
                                                "contradicted_facts",
                                                "fact_type",
                                            ]
                                            if any(
                                                kw in content.lower()
                                                for kw in edge_dup_keywords
                                            ):
                                                edge_dup_result = (
                                                    _parse_edge_duplicate_response(
                                                        content
                                                    )
                                                )
                                                if edge_dup_result:
                                                    logger.info(
                                                        "Fixing JSON: Converted EdgeDuplicate YAML-like response to JSON (non-standard)"
                                                    )
                                                    content = json.dumps(
                                                        edge_dup_result
                                                    )
                                            else:
                                                # Wrap plain text - include both extracted_entities and edges for compatibility
                                                logger.info(
                                                    "Fixing JSON: Wrapping plain text in summary object with empty entities/edges"
                                                )
                                                content = json.dumps(
                                                    {
                                                        "summary": content.strip(),
                                                        "extracted_entities": [],
                                                        "edges": [],
                                                    }
                                                )

                                        if content != original_content:
                                            logger.info(
                                                f"LLM Cleaned Response (HTTP, non-standard): {content}"
                                            )
                                            data["output"][output_index]["content"][0][
                                                "text"
                                            ] = content

                                            # Re-encode response
                                            new_body = json.dumps(data).encode("utf-8")

                                            return httpx.Response(
                                                status_code=response.status_code,
                                                headers=response.headers,
                                                content=new_body,
                                                request=request,
                                                extensions=response.extensions,
                                            )
                                except (KeyError, IndexError, TypeError) as e:
                                    logger.error(
                                        f"Error parsing non-standard response: {e}"
                                    )
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

                def __init__(
                    self,
                    main_base_url,
                    main_api_key,
                    fast_base_url,
                    fast_api_key,
                    fast_model,
                ):
                    super().__init__()
                    self.main_base_url = main_base_url
                    self.main_api_key = main_api_key
                    self.fast_base_url = fast_base_url
                    self.fast_api_key = fast_api_key
                    self.fast_model = fast_model

                    # Parse URLs for modification
                    self.main_parsed = urlparse(main_base_url)
                    self.fast_parsed = urlparse(fast_base_url)

                def _inject_reasoning_effort(self, request, data, model):
                    """
                    Graphiti sends `reasoning` only for gpt-5/o-series models, so other
                    reasoning models (deepseek via litellm) run at the provider default
                    effort and exhaust max_output_tokens. Inject the configured effort
                    for the main model on the Responses API. Returns the new request or None.
                    """
                    effort = settings.LLM_REASONING_EFFORT
                    if (
                        not effort
                        or request.method != "POST"
                        or model == self.fast_model
                        or not request.url.path.endswith("/responses")
                        or "reasoning" in data
                    ):
                        return None
                    data["reasoning"] = {"effort": effort}
                    headers_dict = {
                        k: v
                        for k, v in request.headers.items()
                        if k.lower() != "content-length"
                    }
                    return httpx.Request(
                        method=request.method,
                        url=request.url,
                        headers=headers_dict,
                        content=json.dumps(data).encode("utf-8"),
                    )

                async def handle_async_request(self, request):
                    # Determine which endpoint to use based on model in request
                    original_url = str(request.url)
                    original_auth = request.headers.get("authorization", "not set")
                    request_without_effort = None

                    try:
                        body = (
                            request.content.decode("utf-8") if request.content else "{}"
                        )
                        try:
                            # Use original json.loads to avoid our global patch affecting request parsing
                            data = _original_json_loads(body)
                            # Handle case where body is not a valid JSON (e.g. empty string)
                            if not isinstance(data, dict):
                                data = {}
                        except json.JSONDecodeError:
                            # Only log if body is not empty but failed to parse
                            if body.strip():
                                logger.warning(
                                    f"Failed to parse request body JSON: {body[:100]}..."
                                )
                            data = {}

                        model = data.get("model", "")

                        injected = self._inject_reasoning_effort(request, data, model)
                        if injected is not None:
                            request_without_effort = request
                            request = injected

                        logger.info(
                            f"🔍 Routing request: model={model}, url={original_url}"
                        )
                        logger.info(f"   Fast model configured: {self.fast_model}")
                        logger.info(f"   Auth header: {original_auth[:20]}...")

                        # Route to fast endpoint if request is for fast model
                        if model == self.fast_model:
                            logger.info(f"✓ Model matches fast_model!")

                            if self.fast_base_url != self.main_base_url:
                                # Modify request URL to point to fast endpoint
                                req_parsed = urlparse(str(request.url))
                                new_url = urlunparse(
                                    (
                                        self.fast_parsed.scheme,
                                        self.fast_parsed.netloc,
                                        req_parsed.path,
                                        req_parsed.params,
                                        req_parsed.query,
                                        req_parsed.fragment,
                                    )
                                )

                                # Create new request with modified URL
                                headers_dict = dict(request.headers)
                                request = httpx.Request(
                                    method=request.method,
                                    url=new_url,
                                    headers=headers_dict,
                                    content=request.content,
                                )
                                logger.info(f"→ Routed to fast endpoint: {new_url}")
                            else:
                                logger.info(
                                    f"→ Same endpoint for both models, no URL change needed"
                                )

                            # Always update Authorization header to ensure correct key is used for fast model
                            # This avoids issues where keys might look identical or checks fail
                            headers_dict = dict(request.headers)
                            headers_dict["authorization"] = (
                                f"Bearer {self.fast_api_key}"
                            )

                            request = httpx.Request(
                                method=request.method,
                                url=request.url,
                                headers=headers_dict,
                                content=request.content,
                            )
                            masked_key = (
                                self.fast_api_key[:10] + "..."
                                if self.fast_api_key
                                else "None"
                            )
                            logger.info(f"→ Switched to fast API key: {masked_key}")
                        else:
                            logger.info(
                                f"→ Using main LLM endpoint (model != fast_model)"
                            )

                    except Exception as e:
                        logger.error(f"❌ Error in routing logic: {e}", exc_info=True)

                    # Continue with cleaning and retry logic from parent class
                    logger.info(f"⏳ Calling parent handler (CleaningHTTPTransport)...")
                    response = await super().handle_async_request(request)
                    if request_without_effort is not None and response.status_code == 400:
                        # Provider rejected the reasoning parameter: resend unchanged
                        logger.warning(
                            "LLM rejected injected reasoning effort (400), retrying without it"
                        )
                        await response.aclose()
                        response = await super().handle_async_request(
                            request_without_effort
                        )
                    logger.info(
                        f"✓ Parent handler returned: status={response.status_code}"
                    )
                    return response

            # Create dual-model routing transport
            routing_transport = DualModelRoutingTransport(
                main_base_url=settings.LLM_BASE_URL,
                main_api_key=settings.LLM_API_KEY,
                fast_base_url=settings.LLM_FAST_BASE_URL,
                fast_api_key=settings.LLM_FAST_API_KEY,
                fast_model=settings.LLM_FAST_MODEL,
            )

            # Log configuration
            logger.info(f"Dual-model routing configured:")
            logger.info(f"  Main LLM: {settings.LLM_MODEL} at {settings.LLM_BASE_URL}")
            logger.info(
                f"  Fast LLM: {settings.LLM_FAST_MODEL} at {settings.LLM_FAST_BASE_URL}"
            )
            if settings.LLM_FAST_BASE_URL != settings.LLM_BASE_URL:
                logger.info(f"  ✓ Using separate endpoints for main and fast models")
            if settings.LLM_FAST_API_KEY != settings.LLM_API_KEY:
                logger.info(f"  ✓ Using separate API keys for main and fast models")

            llm_async_client = AsyncOpenAI(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                http_client=httpx.AsyncClient(transport=routing_transport),
            )

            # Create LLM client with DUAL-MODEL strategy
            llm_client = OpenAIClient(
                client=llm_async_client,
                config=LLMConfig(
                    model=settings.LLM_MODEL, small_model=settings.LLM_FAST_MODEL
                ),
                max_tokens=settings.LLM_MAX_TOKENS,
            )

            # Create AsyncOpenAI client for embeddings
            embedder_async_client = AsyncOpenAI(
                base_url=settings.EMBEDDING_BASE_URL,
                api_key=settings.EMBEDDING_API_KEY,
                http_client=httpx.AsyncClient(transport=CleaningHTTPTransport()),
            )

            # Create embedder client with config
            embedder = OpenAIEmbedder(
                client=embedder_async_client,
                config=OpenAIEmbedderConfig(
                    embedding_model=settings.EMBEDDING_MODEL,
                    api_key=settings.EMBEDDING_API_KEY,
                    base_url=settings.EMBEDDING_BASE_URL,
                ),
            )

            # Create reranker client
            reranker = RemoteRerankerClient(
                base_url=settings.RERANKER_BASE_URL,
                api_key=settings.RERANKER_API_KEY,
                model=settings.RERANKER_MODEL,
            )

            # Initialize Graphiti with custom clients
            self.client = Graphiti(
                settings.NEO4J_URI,
                settings.NEO4J_USER,
                settings.NEO4J_PASSWORD,
                llm_client=llm_client,
                embedder=embedder,
                cross_encoder=reranker,
            )

            logger.info(
                f"Graphiti client initialized with Neo4j at {settings.NEO4J_URI}"
            )
            logger.info(f"Using LLM: {settings.LLM_MODEL} at {settings.LLM_BASE_URL}")
            logger.info(
                f"Using Embedder: {settings.EMBEDDING_MODEL} at {settings.EMBEDDING_BASE_URL}"
            )
            logger.info(
                f"Using Reranker: {settings.RERANKER_MODEL} at {settings.RERANKER_BASE_URL}"
            )

        except Exception as e:
            logger.error(f"Failed to initialize Graphiti client: {e}")
            raise

    async def save_pending_episode(
        self, user_id: str, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
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
                updated_at: $created_at,
                source: $source,
                file_name: $file_name,
                status: 'pending',
                attempts: 0,
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
                database_="neo4j",
            )

            logger.info(
                f"Saved PendingEpisode for user {user_id}: {uuid_str} (file: {file_name})"
            )
            return uuid_str
        except Exception as e:
            logger.error(f"Error saving pending episode: {e}")
            return None

    async def delete_pending_episode(
        self, user_id: str, text: str, pending_uuid: Optional[str] = None
    ):
        """
        Delete a PendingEpisode node after successful processing.
        Matches by uuid; falls back to content only for callers without a uuid,
        and then removes a single node so identical messages stay queued.
        """
        try:
            driver = self.client.driver
            if pending_uuid:
                query = """
                MATCH (p:PendingEpisode {uuid: $uuid})
                DETACH DELETE p
                """
                await driver.execute_query(query, uuid=pending_uuid, database_="neo4j")
            else:
                query = """
                MATCH (p:PendingEpisode)
                WHERE p.user_id = $user_id AND p.content = $text
                WITH p ORDER BY p.created_at LIMIT 1
                DETACH DELETE p
                """
                await driver.execute_query(
                    query, user_id=user_id, text=text, database_="neo4j"
                )
            logger.info(f"Cleaned up PendingEpisode for user {user_id}")
        except Exception as e:
            logger.error(f"Error deleting pending episode: {e}")

    async def _mark_pending(
        self, pending_uuid: str, status: str, error: Optional[str] = None
    ) -> int:
        """
        Update PendingEpisode status. 'processing' increments attempts.
        Returns the attempts counter after the update (0 if the node is gone).
        """
        try:
            query = """
            MATCH (p:PendingEpisode {uuid: $uuid})
            SET p.status = $status,
                p.updated_at = $now,
                p.attempts = coalesce(p.attempts, 0) + CASE WHEN $status = 'processing' THEN 1 ELSE 0 END,
                p.last_error = CASE WHEN $error IS NULL THEN p.last_error ELSE $error END
            RETURN p.attempts AS attempts
            """
            result = await self.client.driver.execute_query(
                query,
                uuid=pending_uuid,
                status=status,
                error=error[:500] if error else None,
                now=datetime.now(timezone.utc).isoformat(),
                database_="neo4j",
            )
            return result.records[0]["attempts"] if result.records else 0
        except Exception as e:
            logger.error(f"Error updating PendingEpisode {pending_uuid}: {e}")
            return 0

    async def get_stuck_pending_episodes(self, minutes: int = 30) -> list:
        """
        Get PendingEpisodes that are waiting (or stuck in processing) for more
        than X minutes and still have retry attempts left.
        Legacy nodes without status/attempts are treated as pending/0.
        """
        try:
            driver = self.client.driver
            # Calculate cutoff time as ISO string
            cutoff = (
                datetime.now(timezone.utc) - timedelta(minutes=minutes)
            ).isoformat()

            query = """
            MATCH (p:PendingEpisode)
            WHERE coalesce(p.status, 'pending') IN ['pending', 'processing']
              AND coalesce(p.attempts, 0) < $max_attempts
              AND coalesce(p.updated_at, p.created_at) < $cutoff
            RETURN p.user_id as user_id, p.content as content, p.source as source,
                   p.file_name as file_name, p.uuid as uuid
            """

            result = await driver.execute_query(
                query,
                cutoff=cutoff,
                max_attempts=settings.EPISODE_MAX_ATTEMPTS,
                database_="neo4j",
            )

            stuck = []
            if result.records:
                for record in result.records:
                    if record["uuid"] in self._inflight:
                        continue
                    stuck.append(
                        {
                            "user_id": record["user_id"],
                            "content": record["content"],
                            "source": record["source"],
                            "file_name": record["file_name"],
                            "uuid": record["uuid"],
                        }
                    )
            return stuck
        except Exception as e:
            logger.error(f"Error getting stuck episodes: {e}")
            return []

    async def add_episode(
        self,
        user_id: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
        pending_uuid: Optional[str] = None,
    ) -> str:
        """
        Add an episode (memory) to the knowledge graph.
        Called as background task after save_pending_episode.
        Concurrency is bounded by EPISODE_CONCURRENCY; the PendingEpisode
        (if pending_uuid is given) tracks status/attempts for the retry loop.
        """
        import asyncio

        if getattr(self, "_episode_semaphore", None) is None:
            self._episode_semaphore = asyncio.Semaphore(settings.EPISODE_CONCURRENCY)

        # In-flight set: queued/running episodes are never picked by the retry loop
        if pending_uuid:
            if pending_uuid in self._inflight:
                logger.info(f"PendingEpisode {pending_uuid} already in flight, skipping")
                return ""
            self._inflight.add(pending_uuid)
        try:
            async with self._episode_semaphore:
                if pending_uuid:
                    await self._mark_pending(pending_uuid, "processing")
                try:
                    episode_name = await self._add_episode(user_id, text, metadata)
                except Exception as e:
                    if pending_uuid:
                        attempts = await self._mark_pending(pending_uuid, "pending", str(e))
                        if attempts >= settings.EPISODE_MAX_ATTEMPTS:
                            await self._mark_pending(pending_uuid, "failed")
                            logger.error(
                                f"PendingEpisode {pending_uuid} failed {attempts} times, marked as failed"
                            )
                    raise
                await self.delete_pending_episode(user_id, text, pending_uuid)
                return episode_name
        finally:
            if pending_uuid:
                self._inflight.discard(pending_uuid)

    async def _add_episode(
        self, user_id: str, text: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
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

        logger.info(
            f"[EXTRACT_START] user={user_id}, text_len={len(text)}, file={file_name}"
        )

        try:
            # 2. Prepare custom extraction instructions (Task 1)
            custom_instructions = settings.CUSTOM_EXTRACTION_INSTRUCTIONS or None

            # 3. Add to Graphiti
            await self.client.add_episode(
                name=episode_name,
                episode_body=text,
                source=EpisodeType.text,
                source_description=final_source,
                reference_time=datetime.now(timezone.utc),
                group_id=user_id,  # Critical: isolate data by user
                custom_extraction_instructions=custom_instructions,
            )

            # 4. Tag with file_name if provided (Post-processing check)
            if file_name:
                driver = self.client.driver
                tag_query = """
                MATCH (e:Episodic {name: $name})
                SET e.file_name = $file_name
                RETURN e
                """
                await driver.execute_query(
                    tag_query, name=episode_name, file_name=file_name, database_="neo4j"
                )
                logger.debug(
                    f"Tagged episode {episode_name} with file_name: {file_name}"
                )

            # 5. Log extraction results (Task 8)
            entities_count = await self._count_episode_entities(episode_name, user_id)
            edges_count = await self._count_episode_edges(episode_name, user_id)
            logger.info(
                f"[EXTRACT_DONE] user={user_id}, episode={episode_name}, "
                f"entities={entities_count}, edges={edges_count}"
            )

            # 6. Fallback: create synthetic edge if nothing was extracted (Task 2)
            if edges_count == 0 and entities_count == 0:
                logger.warning(
                    f"Episode {episode_name} produced 0 entities and 0 edges. "
                    f"Creating fallback CONTENT_RAW edge."
                )
                await self._create_fallback_edge(user_id, episode_name, text)

            return episode_name

        except Exception as e:
            logger.error(f"Error adding episode {episode_name}: {e}")
            # We DO NOT delete the pending episode on error, so retry logic can pick it up
            raise e

    async def _count_episode_entities(self, episode_name: str, user_id: str) -> int:
        """Count entities linked to an episode via MENTIONS relationship."""
        try:
            driver = self.client.driver
            query = """
            MATCH (e:Episodic {name: $name})-[:MENTIONS]->(n:Entity)
            WHERE n.group_id = $user_id
            RETURN count(DISTINCT n) as entity_count
            """
            result = await driver.execute_query(
                query, name=episode_name, user_id=user_id, database_="neo4j"
            )
            return result.records[0]["entity_count"] if result.records else 0
        except Exception as e:
            logger.error(f"Error counting entities for {episode_name}: {e}")
            return 0

    async def _count_episode_edges(self, episode_name: str, user_id: str) -> int:
        """Count RELATES_TO edges linked to an episode's entities."""
        try:
            driver = self.client.driver
            query = """
            MATCH (e:Episodic {name: $name})-[:MENTIONS]->(n:Entity)
            WHERE n.group_id = $user_id
            OPTIONAL MATCH (n)-[r:RELATES_TO]-(m:Entity)
            RETURN count(DISTINCT r) as edge_count
            """
            result = await driver.execute_query(
                query, name=episode_name, user_id=user_id, database_="neo4j"
            )
            return result.records[0]["edge_count"] if result.records else 0
        except Exception as e:
            logger.error(f"Error counting edges for {episode_name}: {e}")
            return 0

    async def _create_fallback_edge(
        self, user_id: str, episode_name: str, text: str
    ):
        """
        Create a synthetic CONTENT_RAW edge for episodes with no extracted facts.

        This ensures that episodes which produced zero entities/edges during
        LLM extraction are still discoverable via fulltext/semantic search.
        The raw episode text is stored as the edge's 'fact' field.
        """
        try:
            driver = self.client.driver
            fact_text = text[:2000]  # Cap length for storage
            edge_uuid = str(uuid.uuid4())
            node_uuid = str(uuid.uuid4())

            query = """
            MATCH (e:Episodic {name: $episode_name})
            MERGE (raw:Entity {name: $raw_name, group_id: $user_id})
            ON CREATE SET raw.uuid = $node_uuid,
                          raw.created_at = datetime(),
                          raw.summary = 'Container for raw unextracted episode content'
            MERGE (user_node:Entity {name: $user_name, group_id: $user_id})
            ON CREATE SET user_node.uuid = randomUUID(),
                          user_node.created_at = datetime(),
                          user_node.summary = 'User entity'
            CREATE (user_node)-[r:RELATES_TO {
                uuid: $edge_uuid,
                fact: $fact_text,
                name: 'CONTENT_RAW',
                group_id: $user_id,
                created_at: datetime(),
                valid_at: datetime(),
                invalid_at: null,
                episodes: [$episode_name]
            }]->(raw)
            MERGE (e)-[:MENTIONS]->(raw)
            MERGE (e)-[:MENTIONS]->(user_node)
            RETURN r.uuid as uuid
            """
            await driver.execute_query(
                query,
                episode_name=episode_name,
                raw_name=f"RawContent_{user_id}",
                user_id=user_id,
                user_name=user_id,
                node_uuid=node_uuid,
                edge_uuid=edge_uuid,
                fact_text=fact_text,
                database_="neo4j",
            )
            logger.info(
                f"Created fallback CONTENT_RAW edge {edge_uuid} for episode {episode_name}"
            )
        except Exception as e:
            logger.error(f"Error creating fallback edge for {episode_name}: {e}")

    async def _get_center_node_uuid(self, user_id: str) -> Optional[str]:
        """Most connected Entity of the group, cached for 10 minutes (node_distance center)."""
        import time

        cache = getattr(self, "_center_cache", None)
        if cache is None:
            cache = self._center_cache = {}
        cached = cache.get(user_id)
        if cached and time.time() - cached[1] < 600:
            return cached[0]
        query = """
        MATCH (n:Entity {group_id: $g})
        WITH n, COUNT{(n)-[:RELATES_TO]-(:Entity)} AS degree
        ORDER BY degree DESC
        LIMIT 1
        RETURN n.uuid AS uuid
        """
        result = await self.client.driver.execute_query(
            query, g=user_id, database_="neo4j"
        )
        center = result.records[0]["uuid"] if result.records else None
        cache[user_id] = (center, time.time())
        return center

    @staticmethod
    def _is_invalid_fact(edge, now: datetime) -> bool:
        """A fact is stale if it was superseded (expired_at) or its validity ended."""
        expired_at = getattr(edge, "expired_at", None)
        if expired_at is not None and expired_at.year < 9999:
            return True
        invalid_at = getattr(edge, "invalid_at", None)
        if invalid_at is not None:
            if invalid_at.tzinfo is None:
                invalid_at = invalid_at.replace(tzinfo=timezone.utc)
            return invalid_at <= now
        return False

    @staticmethod
    def _recency_factor(edge, now: datetime) -> float:
        """0.5 ** (age / half_life) based on valid_at (fallback created_at)."""
        ts = getattr(edge, "valid_at", None) or getattr(edge, "created_at", None)
        if ts is None:
            return 0.0
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_days = max((now - ts).total_seconds() / 86400.0, 0.0)
        half_life = max(settings.SEARCH_RECENCY_HALF_LIFE_DAYS, 1e-6)
        return 0.5 ** (age_days / half_life)

    async def search(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        center_node_uuid: Optional[str] = None,
        include_invalid: Optional[bool] = None,
        search_mode: str = "hybrid",
    ) -> List[MemoryHit]:
        """
        Search for relevant memories (edges) in the knowledge graph.

        Uses COMBINED_HYBRID_SEARCH_CROSS_ENCODER when USE_RERANKER=true,
        falls back to COMBINED_HYBRID_SEARCH_RRF otherwise or on reranker failure.
        search_mode="node_distance" ranks facts by graph distance to a center node
        (given, or the user's most connected entity) — HippoRAG-style locality.
        Stale facts (invalidated/expired) are dropped unless include_invalid,
        results are re-ordered with a recency blend (SEARCH_RECENCY_WEIGHT)
        and filtered by SEARCH_MIN_SCORE.
        """
        try:
            import asyncio

            now = datetime.now(timezone.utc)
            exclude_invalid = (
                settings.SEARCH_EXCLUDE_INVALID
                if include_invalid is None
                else not include_invalid
            )
            # Over-fetch so that filtering stale facts still leaves `limit` results
            fetch_limit = limit * 2 if exclude_invalid else limit
            use_reranker = settings.USE_RERANKER
            logger.info(
                f"Searching for user {user_id}: {query} "
                f"(limit={limit}, mode={search_mode}, reranker={'ON' if use_reranker else 'OFF'})"
            )

            results = []
            reranker_scores = []

            if search_mode == "node_distance":
                if not center_node_uuid:
                    center_node_uuid = await self._get_center_node_uuid(user_id)
                if center_node_uuid:
                    search_config = copy.deepcopy(EDGE_HYBRID_SEARCH_NODE_DISTANCE)
                    search_config.limit = fetch_limit
                    search_results = await self.client.search_(
                        query=query,
                        center_node_uuid=center_node_uuid,
                        config=search_config,
                        group_ids=[user_id],
                    )
                    results = search_results.edges
                    use_reranker = None  # handled, skip other strategies
                    logger.info(
                        f"✓ Node-distance search got {len(results)} results (center={center_node_uuid})"
                    )
                else:
                    logger.info("No center node for node_distance search, using hybrid")

            if use_reranker:
                # Attempt cross-encoder reranker search
                search_config = copy.deepcopy(COMBINED_HYBRID_SEARCH_CROSS_ENCODER)
                search_config.limit = fetch_limit
                try:
                    search_results = await asyncio.wait_for(
                        self.client.search_(
                            query=query,
                            center_node_uuid=center_node_uuid,
                            config=search_config,
                            group_ids=[user_id],
                        ),
                        timeout=settings.RERANKER_TIMEOUT
                    )
                    results = search_results.edges
                    reranker_scores = getattr(search_results, "edge_reranker_scores", []) or []
                    logger.debug(f"edges={len(results)}, scores={len(reranker_scores)}")
                    log_scores = [round(s, 2) for s in reranker_scores[:10]]
                    logger.info(
                        f"✓ Reranker search successful, got {len(results)} results, scores={log_scores}"
                    )
                except Exception as e:
                    logger.warning(
                        f"⚠️ Reranker search failed ({type(e).__name__}: {e}), falling back to RRF"
                    )
                    use_reranker = False  # Fall through to RRF below

            if use_reranker is False:
                # RRF search (no cross-encoder, uses reciprocal rank fusion)
                search_config = copy.deepcopy(COMBINED_HYBRID_SEARCH_RRF)
                search_config.limit = fetch_limit
                search_results = await self.client.search_(
                    query=query,
                    center_node_uuid=center_node_uuid,
                    config=search_config,
                    group_ids=[user_id],
                )
                results = search_results.edges
                logger.info(f"✓ RRF search got {len(results)} results")

            # Pair each edge with its score before any filtering so they stay aligned.
            # Without reranker scores, keep the engine's ranking as a rank-based score.
            total = len(results)
            scored = []
            for i, result in enumerate(results):
                if i < len(reranker_scores):
                    score = reranker_scores[i]
                    base = score
                else:
                    score = getattr(result, "score", 1.0)
                    base = 1.0 - (i / total) if total else 1.0
                scored.append((result, score, base))

            if exclude_invalid:
                before = len(scored)
                scored = [s for s in scored if not self._is_invalid_fact(s[0], now)]
                if before != len(scored):
                    logger.info(f"Temporal filter: {before} -> {len(scored)} facts")

            weight = settings.SEARCH_RECENCY_WEIGHT
            if weight > 0 and scored:
                scored.sort(
                    key=lambda s: (1 - weight) * s[2]
                    + weight * self._recency_factor(s[0], now),
                    reverse=True,
                )

            scored = scored[:limit]

            # Collect episode UUIDs from results to fetch file_name metadata
            episode_uuids = set()
            for result, _, _ in scored:
                ep_list = getattr(result, "episodes", [])
                if ep_list and len(ep_list) > 0:
                    episode_uuids.add(ep_list[0])

            # Fetch file_name for episodes in batch
            episode_file_map = {}
            if episode_uuids:
                driver = self.client.driver
                file_query = """
                MATCH (e:Episodic)
                WHERE e.uuid IN $uuids
                RETURN e.uuid AS uuid, e.file_name AS file_name
                """
                result_records = await driver.execute_query(
                    file_query, uuids=list(episode_uuids), database_="neo4j"
                )
                for record in result_records.records:
                    episode_file_map[record["uuid"]] = record.get("file_name")

            # Convert to MemoryHit format with file_name in metadata
            hits = []
            for result, score, _ in scored:
                ep_list = getattr(result, "episodes", [])
                ep_uuid = ep_list[0] if ep_list and len(ep_list) > 0 else None
                file_name = episode_file_map.get(ep_uuid) if ep_uuid else None

                hit = MemoryHit(
                    fact=result.fact,
                    score=score,
                    uuid=result.uuid,
                    created_at=getattr(
                        result, "created_at", datetime.now(timezone.utc)
                    ),
                    metadata={
                        "source_node_uuid": getattr(result, "source_node_uuid", None),
                        "target_node_uuid": getattr(result, "target_node_uuid", None),
                        "valid_at": str(result.valid_at)
                        if hasattr(result, "valid_at") and result.valid_at
                        else None,
                        "invalid_at": str(result.invalid_at)
                        if hasattr(result, "invalid_at") and result.invalid_at
                        else None,
                        "file_name": file_name,
                        "episode_uuid": ep_uuid,
                    },
                )
                hits.append(hit)

            # Apply min_score filter (Task 4)
            min_score = settings.SEARCH_MIN_SCORE
            if min_score > 0:
                before_filter = len(hits)
                if before_filter > 0:
                    hits_filtered = [h for h in hits if h.score >= min_score]
                    if len(hits_filtered) == 0:
                        scores_list = [h.score for h in hits]
                        logger.warning(
                            f"all {before_filter} results filtered out by min_score={min_score}, "
                            f"scores range=[{min(scores_list):.4f}..{max(scores_list):.4f}]"
                        )
                    elif before_filter != len(hits_filtered):
                        logger.info(
                            f"Score filter: {before_filter} -> {len(hits_filtered)} hits "
                            f"(min_score={min_score})"
                        )
                    hits = hits_filtered

            logger.info(f"Found {len(hits)} results for query: {query}")
            return hits

        except Exception as e:
            logger.error(f"Error searching: {e}")
            return []

    async def get_user_graph(self, user_id: str, limit: int = 300) -> Dict[str, Any]:
        """
        Get the knowledge graph for a specific user (top nodes by degree).

        Args:
            user_id: User identifier
            limit: Maximum number of nodes to return (top-N by degree)

        Returns:
            Graph structure with nodes, edges and totals
        """
        try:
            logger.info(f"Getting graph for user {user_id}, limit={limit}")

            driver = self.client.driver
            group_id = user_id

            # Totals for this group only
            totals_query = """
            RETURN COUNT { (n:Entity {group_id: $g}) } AS total_nodes,
                   COUNT { ()-[r:RELATES_TO {group_id: $g}]->() } AS total_edges
            """
            totals_result = await driver.execute_query(
                totals_query, g=group_id, database_="neo4j"
            )
            total_nodes = int(totals_result.records[0]["total_nodes"]) if totals_result.records else 0
            total_edges = int(totals_result.records[0]["total_edges"]) if totals_result.records else 0

            # Top-N entities by degree (number of RELATES_TO neighbors)
            top_query = """
            MATCH (n:Entity {group_id: $g})
            WITH n, COUNT{(n)-[:RELATES_TO]-(:Entity)} AS degree
            ORDER BY degree DESC, n.uuid
            LIMIT $limit
            RETURN n.uuid AS uuid, n.name AS name, left(n.summary, 200) AS summary,
                   toString(n.created_at) AS created_at, degree
            """
            top_result = await driver.execute_query(
                top_query, g=group_id, limit=limit, database_="neo4j"
            )

            nodes = []
            node_uuids = []
            for record in top_result.records:
                node_uuids.append(record["uuid"])
                nodes.append(
                    {
                        "data": {
                            "id": record["uuid"],
                            "label": record["name"] or "Unknown",
                            "summary": record["summary"] or "",
                            "created_at": record["created_at"],
                            "degree": int(record["degree"]),
                        }
                    }
                )

            # Edges only between the selected nodes, excluding self-loops
            edge_limit = limit * settings.GRAPH_MAX_EDGES_FACTOR
            edges = []
            if node_uuids:
                edges_query = """
                MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
                WHERE a.uuid IN $ids AND b.uuid IN $ids AND a.uuid <> b.uuid AND r.group_id = $g
                RETURN a.uuid AS source, b.uuid AS target, r.uuid AS uuid,
                       left(r.fact, 100) AS fact, r.name AS name,
                       (r.invalid_at IS NOT NULL OR (r.expired_at IS NOT NULL AND r.expired_at.year < 9999)) AS invalid
                LIMIT $edge_limit
                """
                edges_result = await driver.execute_query(
                    edges_query,
                    ids=node_uuids,
                    g=group_id,
                    edge_limit=edge_limit,
                    database_="neo4j",
                )
                for record in edges_result.records:
                    edges.append(
                        {
                            "data": {
                                "id": record["uuid"],
                                "source": record["source"],
                                "target": record["target"],
                                "label": record["fact"] or "",
                                "name": record["name"],
                                "invalid": bool(record["invalid"]),
                            }
                        }
                    )

            truncated = total_nodes > limit

            logger.info(
                f"Retrieved {len(nodes)} nodes and {len(edges)} edges for user {user_id} "
                f"(total_nodes={total_nodes}, total_edges={total_edges}, truncated={truncated})"
            )

            return {
                "nodes": nodes,
                "edges": edges,
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "truncated": truncated,
                "limit": limit,
            }

        except Exception as e:
            logger.error(f"Error getting user graph: {e}", exc_info=True)
            raise

    async def get_summary(self, user_id: str) -> str:
        """
        Generate a summary of user's knowledge graph

        Args:
            user_id: User identifier

        Returns:
            Text summary
        """
        try:
            # Prefer community summaries (GraphRAG-style global view), else the
            # summaries of the most connected entities. No LLM call needed.
            communities = await self.get_communities(user_id, limit=10)
            if communities:
                summary_parts = [f"Knowledge summary for {user_id} (by topic):"]
                for i, c in enumerate(communities, 1):
                    text = (c["summary"] or "").strip().replace("\n", " ")
                    summary_parts.append(
                        f"{i}. {c['name']} ({c['members']} entities): {text[:400]}"
                    )
                return "\n".join(summary_parts)

            query = """
            MATCH (n:Entity {group_id: $g})
            WHERE n.summary IS NOT NULL AND n.summary <> ''
            WITH n, COUNT{(n)-[:RELATES_TO]-(:Entity)} AS degree
            ORDER BY degree DESC
            LIMIT 10
            RETURN n.name AS name, n.summary AS summary, degree
            """
            result = await self.client.driver.execute_query(
                query, g=user_id, database_="neo4j"
            )
            if not result.records:
                return f"No information found for user {user_id}"

            summary_parts = [f"Knowledge summary for {user_id}:"]
            for i, record in enumerate(result.records, 1):
                text = (record["summary"] or "").strip().replace("\n", " ")
                summary_parts.append(f"{i}. {record['name']}: {text[:300]}")

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

            # Tenancy is the exact group_id: episodes, entities and communities all
            # carry it. Name prefixes are NOT used ("ETH" must not touch "ETH_USDT",
            # "35145416" must not touch "35145416-code").
            driver = self.client.driver

            query = """
            MATCH (n)
            WHERE (n:Episodic OR n:Entity OR n:Community) AND n.group_id = $user_id
            DETACH DELETE n
            RETURN count(n) as nodes_deleted
            """
            result = await driver.execute_query(
                query, user_id=user_id, database_="neo4j"
            )
            nodes_deleted = result.records[0]["nodes_deleted"] if result.records else 0

            pending_query = """
            MATCH (p:PendingEpisode {user_id: $user_id})
            DETACH DELETE p
            RETURN count(p) as pending_deleted
            """
            pending_result = await driver.execute_query(
                pending_query, user_id=user_id, database_="neo4j"
            )
            pending_deleted = (
                pending_result.records[0]["pending_deleted"]
                if pending_result.records
                else 0
            )

            await driver.execute_query(
                "MATCH (u:User {id: $user_id}) DETACH DELETE u",
                user_id=user_id,
                database_="neo4j",
            )

            logger.info(
                f"Deleted {nodes_deleted} nodes and {pending_deleted} pending episodes for user {user_id}"
            )

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
            CALL () {
                MATCH (e:Episodic {group_id: $user_id})
                WHERE e.file_name IS NOT NULL
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
                "user_id": user_id,
            }

            result = await driver.execute_query(query, **params)

            files = []
            if result.records:
                for record in result.records:
                    files.append(
                        {
                            "file_name": record["file_name"],
                            "chunk_count": record["total_chunks"],
                            "created_at": record["created_at"],
                        }
                    )

            return files
        except Exception as e:
            logger.error(f"Error getting files for user {user_id}: {e}")
            raise e

    async def get_user_episodes(self, user_id: str, limit: int = None) -> list:
        """
        Get list of episodes for a user, including pending ones.
        """
        try:
            logger.info(
                f"Getting episodes for user: {user_id} limit={limit} type={type(limit)}"
            )
            driver = self.client.driver

            # Use CALL subquery to properly wrap UNION and apply LIMIT to the final result
            query = """
            CALL () {
                // 1. Get processed episodes
                MATCH (e:Episodic {group_id: $user_id})
                WHERE e.file_name IS NULL
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
                       CASE WHEN p.status = 'failed' THEN 'failed' ELSE 'pending' END as status
            }
            RETURN uuid, name, created_at, source, content, status
            ORDER BY created_at DESC
            """

            params = {
                "user_id": user_id,
                "database_": "neo4j",
            }

            if limit is not None and limit > 0:
                query += "\nLIMIT $limit"
                params["limit"] = limit

            result = await driver.execute_query(query, **params)

            episodes = []
            pending_count = 0
            processed_count = 0

            if result.records:
                for record in result.records:
                    if record["status"] == "pending":
                        pending_count += 1
                    else:
                        processed_count += 1

                    episodes.append(
                        {
                            "uuid": record["uuid"],
                            "created_at": record["created_at"],
                            "source": record["source"],
                            "content": record["content"],
                            "status": record["status"],
                        }
                    )

            logger.info(
                f"Found {len(episodes)} episodes ({processed_count} processed, {pending_count} pending)"
            )
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
            logger.info(
                f"Deleting all episodes for user {user_id} with file_name: {file_name}"
            )
            driver = self.client.driver

            # Step 1: Find episodes and identify orphaned entities
            query1 = """
            // Find all episodes matching file_name and user_id
            MATCH (e:Episodic)
            WHERE e.file_name = $file_name AND e.group_id = $user_id
            
            // Collect uuid for logging
            WITH e, e.uuid as uuid
            
            // Find all entities mentioned by these episodes
            OPTIONAL MATCH (e)-[:MENTIONS]->(entity:Entity)
            WITH collect(DISTINCT e) as target_episodes, collect(DISTINCT entity) as file_entities
            
            // Delete the episodes first
            FOREACH (ep IN target_episodes | DETACH DELETE ep)
            
            // Check which entities became orphaned (no other episodes mention them)
            WITH file_entities, size(file_entities) as total_entities
            UNWIND file_entities as entity
            OPTIONAL MATCH (entity)<-[:MENTIONS]-(other_episode:Episodic)
            WITH entity, total_entities, count(other_episode) as other_refs
            WHERE other_refs = 0
            
            // Delete orphaned entities
            WITH collect(entity) as orphaned_entities, total_entities
            FOREACH (orphan IN orphaned_entities | DETACH DELETE orphan)
            
            RETURN size(orphaned_entities) as deleted_entities, total_entities as sampled_entities
            """

            result1 = await driver.execute_query(
                query1,
                user_id=user_id,
                file_name=file_name,
                database_="neo4j",
            )

            deleted_entities = (
                result1.records[0]["deleted_entities"] if result1.records else 0
            )

            # Step 2: Cleanup any orphaned RELATES_TO relationships
            query2 = """
            MATCH ()-[r:RELATES_TO {group_id: $user_id}]->()
            WITH r, startNode(r) as start_entity, endNode(r) as end_entity
            OPTIONAL MATCH (start_entity)<-[:MENTIONS]-(e1:Episodic)
            OPTIONAL MATCH (end_entity)<-[:MENTIONS]-(e2:Episodic)
            WITH r, count(e1) as start_refs, count(e2) as end_refs
            WHERE start_refs = 0 OR end_refs = 0
            DELETE r
            RETURN count(r) as deleted_edges
            """

            result2 = await driver.execute_query(
                query2, user_id=user_id, database_="neo4j"
            )

            deleted_edges = (
                result2.records[0]["deleted_edges"] if result2.records else 0
            )

            # Step 3: Cleanup PendingEpisodes
            query3 = """
            MATCH (p:PendingEpisode {user_id: $user_id, file_name: $file_name})
            DETACH DELETE p
            RETURN count(p) as pending_deleted
            """
            await driver.execute_query(
                query3, user_id=user_id, file_name=file_name, database_="neo4j"
            )

            logger.info(
                f"Bulk deleted for file '{file_name}': {deleted_entities} entities, {deleted_edges} orphaned edges"
            )
            return True

        except Exception as e:
            logger.error(f"Error in bulk deletion for file {file_name}: {e}")
            raise e

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
                query1, uuid=episode_uuid, database_="neo4j"
            )

            deleted_entities = (
                result1.records[0]["deleted_entities"] if result1.records else 0
            )

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

            result2 = await driver.execute_query(query2, database_="neo4j")

            deleted_edges = (
                result2.records[0]["deleted_edges"] if result2.records else 0
            )

            logger.info(
                f"Deleted episode {episode_uuid}: {deleted_entities} entities, {deleted_edges} orphaned edges"
            )
            return True

        except Exception as e:
            logger.error(f"Error deleting episode {episode_uuid}: {e}")
            return False

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def run_startup_maintenance(self):
        """
        Idempotent startup tasks: create missing graphiti indices (IF NOT EXISTS,
        never drops) and repair legacy fallback edges. Never raises.
        """
        try:
            await self.client.build_indices_and_constraints()
            logger.info("Graphiti indices and constraints ensured")
        except Exception as e:
            logger.error(f"Failed to build indices: {e}")
        await self.fix_sentinel_expired_at()

    async def fix_sentinel_expired_at(self) -> int:
        """
        Older fallback CONTENT_RAW edges were written with expired_at=9999-12-31.
        In graphiti a non-null expired_at means "superseded", so clear it.
        """
        try:
            query = """
            MATCH ()-[r:RELATES_TO]->()
            WHERE r.expired_at IS NOT NULL AND r.expired_at.year = 9999
            SET r.expired_at = null
            RETURN count(r) AS fixed
            """
            result = await self.client.driver.execute_query(query, database_="neo4j")
            fixed = result.records[0]["fixed"] if result.records else 0
            if fixed:
                logger.info(f"Cleared sentinel expired_at on {fixed} fallback edges")
            return fixed
        except Exception as e:
            logger.error(f"Failed to fix sentinel expired_at: {e}")
            return 0

    async def cleanup_orphan_entities(self, delete: bool = False) -> int:
        """Entities no episode mentions. Reports by default; deletes only if asked."""
        count_query = """
        MATCH (n:Entity)
        WHERE NOT EXISTS { (:Episodic)-[:MENTIONS]->(n) }
        RETURN count(n) AS orphans
        """
        result = await self.client.driver.execute_query(count_query, database_="neo4j")
        orphans = result.records[0]["orphans"] if result.records else 0
        if orphans and delete:
            delete_query = """
            MATCH (n:Entity)
            WHERE NOT EXISTS { (:Episodic)-[:MENTIONS]->(n) }
            DETACH DELETE n
            """
            await self.client.driver.execute_query(delete_query, database_="neo4j")
            logger.info(f"Deleted {orphans} orphan entities")
        elif orphans:
            logger.info(f"Found {orphans} orphan entities (not deleted)")
        return orphans

    async def groups_needing_communities(self) -> List[str]:
        """Groups with episodes newer than their latest community build."""
        query = """
        MATCH (e:Episodic)
        WHERE e.group_id IS NOT NULL
        WITH e.group_id AS g, max(e.created_at) AS last_episode
        OPTIONAL MATCH (c:Community {group_id: g})
        WITH g, last_episode, max(c.created_at) AS last_build
        WHERE last_build IS NULL OR last_episode > last_build
        RETURN g
        """
        result = await self.client.driver.execute_query(query, database_="neo4j")
        return [r["g"] for r in result.records]

    async def consolidate(self) -> Dict[str, Any]:
        """Nightly "sleep-time" consolidation. Non-destructive unless configured."""
        report: Dict[str, Any] = {}
        report["sentinel_fixed"] = await self.fix_sentinel_expired_at()
        try:
            report["orphan_entities"] = await self.cleanup_orphan_entities(
                delete=settings.CONSOLIDATION_DELETE_ORPHANS
            )
        except Exception as e:
            logger.error(f"Orphan check failed: {e}")
        if settings.CONSOLIDATION_BUILD_COMMUNITIES:
            rebuilt = []
            for group_id in await self.groups_needing_communities():
                job = await self.build_communities_for_user(group_id)
                if job.get("status") == "done":
                    rebuilt.append(group_id)
            report["communities_rebuilt"] = rebuilt
        logger.info(f"Consolidation report: {report}")
        return report

    # ------------------------------------------------------------------
    # Communities (GraphRAG-style topic clusters with summaries)
    # ------------------------------------------------------------------

    def get_community_job(self, user_id: str) -> Dict[str, Any]:
        jobs = getattr(self, "_community_jobs", {})
        return jobs.get(user_id, {"status": "idle"})

    async def get_community_status(self, user_id: str) -> Dict[str, Any]:
        """In-process build job merged with what is stored in Neo4j (survives restarts)."""
        status = dict(self.get_community_job(user_id))
        result = await self.client.driver.execute_query(
            """
            MATCH (c:Community {group_id: $g})
            RETURN count(c) AS built, toString(max(c.created_at)) AS last_built_at
            """,
            g=user_id,
            database_="neo4j",
        )
        record = result.records[0] if result.records else None
        status["built"] = int(record["built"]) if record else 0
        status["last_built_at"] = record["last_built_at"] if record else None
        return status

    async def build_communities_for_user(self, user_id: str) -> Dict[str, Any]:
        """
        Rebuild communities for one group (graphiti removes only this group's
        Community nodes). LLM-heavy: one summary per merge step.
        """
        if getattr(self, "_community_jobs", None) is None:
            self._community_jobs = {}
        job = self._community_jobs.get(user_id)
        if job and job.get("status") == "running":
            return job
        job = {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
            "communities": None,
        }
        self._community_jobs[user_id] = job
        try:
            nodes, _ = await self.client.build_communities(group_ids=[user_id])
            job.update(status="done", communities=len(nodes))
            logger.info(f"Built {len(nodes)} communities for {user_id}")
        except Exception as e:
            job.update(status="error", error=str(e)[:500])
            logger.error(f"Community build failed for {user_id}: {e}", exc_info=True)
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        return job

    async def get_communities(
        self, user_id: str, limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        query = """
        MATCH (c:Community {group_id: $g})
        WITH c, COUNT { (c)-[:HAS_MEMBER]->(:Entity) } AS members
        RETURN c.uuid AS uuid, c.name AS name, c.summary AS summary, members,
               toString(c.created_at) AS created_at
        ORDER BY members DESC, c.uuid
        """
        params: Dict[str, Any] = {"g": user_id}
        if limit:
            query += "\nLIMIT $limit"
            params["limit"] = limit
        result = await self.client.driver.execute_query(
            query, **params, database_="neo4j"
        )
        return [
            {
                "uuid": r["uuid"],
                "name": r["name"] or "",
                "summary": r["summary"] or "",
                "members": int(r["members"]),
                "created_at": r["created_at"],
            }
            for r in result.records
        ]

    async def get_community_members_graph(
        self, user_id: str, community_uuid: str, limit: int = 300
    ) -> Dict[str, Any]:
        """Members of one community in the same format as get_user_graph."""
        driver = self.client.driver
        totals = await driver.execute_query(
            """
            MATCH (c:Community {uuid: $c, group_id: $g})
            RETURN COUNT { (c)-[:HAS_MEMBER]->(:Entity) } AS total_nodes
            """,
            c=community_uuid,
            g=user_id,
            database_="neo4j",
        )
        total_nodes = int(totals.records[0]["total_nodes"]) if totals.records else 0

        top = await driver.execute_query(
            """
            MATCH (c:Community {uuid: $c, group_id: $g})-[:HAS_MEMBER]->(n:Entity)
            WITH n, COUNT{(n)-[:RELATES_TO]-(:Entity)} AS degree
            ORDER BY degree DESC, n.uuid
            LIMIT $limit
            RETURN n.uuid AS uuid, n.name AS name, left(n.summary, 200) AS summary,
                   toString(n.created_at) AS created_at, degree
            """,
            c=community_uuid,
            g=user_id,
            limit=limit,
            database_="neo4j",
        )
        nodes = []
        ids = []
        for r in top.records:
            ids.append(r["uuid"])
            nodes.append(
                {
                    "data": {
                        "id": r["uuid"],
                        "label": r["name"] or "Unknown",
                        "summary": r["summary"] or "",
                        "created_at": r["created_at"],
                        "degree": int(r["degree"]),
                    }
                }
            )

        edges = []
        if ids:
            rel = await driver.execute_query(
                """
                MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
                WHERE a.uuid IN $ids AND b.uuid IN $ids AND a.uuid <> b.uuid AND r.group_id = $g
                RETURN a.uuid AS source, b.uuid AS target, r.uuid AS uuid,
                       left(r.fact, 100) AS fact, r.name AS name,
                       (r.invalid_at IS NOT NULL OR (r.expired_at IS NOT NULL AND r.expired_at.year < 9999)) AS invalid
                LIMIT $edge_limit
                """,
                ids=ids,
                g=user_id,
                edge_limit=limit * settings.GRAPH_MAX_EDGES_FACTOR,
                database_="neo4j",
            )
            for r in rel.records:
                edges.append(
                    {
                        "data": {
                            "id": r["uuid"],
                            "source": r["source"],
                            "target": r["target"],
                            "label": r["fact"] or "",
                            "name": r["name"],
                            "invalid": bool(r["invalid"]),
                        }
                    }
                )

        return {
            "nodes": nodes,
            "edges": edges,
            "total_nodes": total_nodes,
            "total_edges": len(edges),
            "truncated": total_nodes > limit,
            "limit": limit,
        }

    # ------------------------------------------------------------------
    # Bulk ingestion (files / imports)
    # ------------------------------------------------------------------

    async def add_episodes_bulk(
        self, user_id: str, items: List[Dict[str, Any]], pending_uuids: List[str]
    ) -> List[str]:
        """
        Ingest many episodes in one graphiti add_episode_bulk call (shared
        extraction/dedup passes — far fewer LLM calls than one-by-one).
        On failure the PendingEpisodes stay queued and the retry loop
        processes them individually.
        """
        import asyncio
        from graphiti_core.utils.bulk_utils import RawEpisode

        if getattr(self, "_episode_semaphore", None) is None:
            self._episode_semaphore = asyncio.Semaphore(settings.EPISODE_CONCURRENCY)

        now = datetime.now(timezone.utc)
        raws = []
        file_rows = []
        for i, item in enumerate(items):
            metadata = item.get("metadata") or {}
            name = f"{user_id}_{(now + timedelta(microseconds=i)).isoformat()}"
            source = metadata.get("source", "User Input")
            file_name = metadata.get("file_name")
            role = metadata.get("role", "user")
            description = (
                f"{source} (file: {file_name})" if file_name else f"{source} ({role})"
            )
            raws.append(
                RawEpisode(
                    name=name,
                    content=item["text"],
                    source_description=description,
                    source=EpisodeType.text,
                    reference_time=now,
                )
            )
            if file_name:
                file_rows.append({"name": name, "file_name": file_name})

        tracked = [u for u in pending_uuids if u]
        self._inflight.update(tracked)
        try:
            async with self._episode_semaphore:
                logger.info(f"[BULK_START] user={user_id}, episodes={len(raws)}")
                await self.client.add_episode_bulk(
                    raws,
                    group_id=user_id,
                    custom_extraction_instructions=settings.CUSTOM_EXTRACTION_INSTRUCTIONS
                    or None,
                )
        finally:
            self._inflight.difference_update(tracked)

        if file_rows:
            await self.client.driver.execute_query(
                """
                UNWIND $rows AS row
                MATCH (e:Episodic {name: row.name, group_id: $g})
                SET e.file_name = row.file_name
                """,
                rows=file_rows,
                g=user_id,
                database_="neo4j",
            )
        for pending_uuid in pending_uuids:
            if pending_uuid:
                await self.delete_pending_episode(user_id, "", pending_uuid)
        logger.info(f"[BULK_DONE] user={user_id}, episodes={len(raws)}")
        return [r.name for r in raws]

    async def close(self):
        """Close the Graphiti client connection"""
        try:
            await self.client.close()
            logger.info("Graphiti client connection closed")
        except Exception as e:
            logger.error(f"Error closing Graphiti client: {e}")


# Global Graphiti client instance
graphiti_client = GraphitiWrapper()
