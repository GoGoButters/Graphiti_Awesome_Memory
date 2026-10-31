from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from app.models.schemas import (
    MemoryAppendRequest, MemoryAppendResponse,
    MemoryBulkAppendRequest, MemoryBulkAppendResponse,
    MemoryQueryRequest, MemoryQueryResponse,
    MemorySummaryRequest, MemorySummaryResponse,
    SourceGroup, GroupedMemoryQueryResponse
)
from app.core.auth import get_api_key
from app.core.config import settings
from app.services.graphiti_client import graphiti_client
from datetime import datetime, timezone
import re
import uuid
import logging
import os

router = APIRouter()
logger = logging.getLogger(__name__)

# Acknowledgements that carry no facts: skipped before LLM extraction
_TRIVIAL_MESSAGES = {
    "ok", "okay", "ок", "окей", "да", "нет", "ага", "угу", "спасибо", "спс",
    "благодарю", "thanks", "thank you", "thx", "ty", "yes", "no", "+", "👍",
}


def is_trivial_message(text: str) -> bool:
    normalized = re.sub(r"[\s.!?,)]+$", "", (text or "").strip().lower())
    return len(normalized) < 4 or normalized in _TRIVIAL_MESSAGES


def _skip_trivial(text: str, metadata) -> bool:
    # File chunks are never skipped
    return (
        settings.SKIP_TRIVIAL_MESSAGES
        and not (metadata or {}).get("file_name")
        and is_trivial_message(text)
    )


@router.post("/append", response_model=MemoryAppendResponse)
async def append_memory(
    request: MemoryAppendRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key)
):
    try:
        created_ts = datetime.now(timezone.utc)

        if _skip_trivial(request.text, request.metadata):
            logger.info(f"Skipping trivial message for user {request.user_id}: {request.text!r}")
            return MemoryAppendResponse(ok=True, id="skipped", created_ts=created_ts)

        # 1. Save PendingEpisode immediately for instant UI feedback (durable retry queue)
        pending_uuid = await graphiti_client.save_pending_episode(
            request.user_id, request.text, request.metadata
        )
        episode_id = pending_uuid or str(uuid.uuid4())

        # 2. Execute heavy processing in background
        background_tasks.add_task(
            graphiti_client.add_episode,
            request.user_id,
            request.text,
            request.metadata,
            pending_uuid=pending_uuid,
        )

        return MemoryAppendResponse(
            ok=True,
            id=episode_id,
            created_ts=created_ts
        )
    except Exception as e:
        logger.error(f"Error in append_memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _run_bulk(user_id: str, items: list, pending_uuids: list):
    try:
        await graphiti_client.add_episodes_bulk(user_id, items, pending_uuids)
    except Exception as e:
        # PendingEpisodes stay queued; the retry loop processes them one by one
        logger.error(f"Bulk ingestion failed for user {user_id}: {e}")


@router.post("/append/bulk", response_model=MemoryBulkAppendResponse)
async def append_memory_bulk(
    request: MemoryBulkAppendRequest,
    background_tasks: BackgroundTasks,
    api_key: str = Depends(get_api_key)
):
    """
    Add many episodes at once (e.g. file chunks). Uses graphiti add_episode_bulk:
    shared extraction and deduplication passes, far fewer LLM calls.
    """
    try:
        items = []
        pending_uuids = []
        skipped = 0
        for item in request.items:
            metadata = item.metadata or {}
            if _skip_trivial(item.text, metadata):
                skipped += 1
                continue
            pending_uuids.append(
                await graphiti_client.save_pending_episode(request.user_id, item.text, metadata)
            )
            items.append({"text": item.text, "metadata": metadata})

        if items:
            background_tasks.add_task(_run_bulk, request.user_id, items, pending_uuids)

        return MemoryBulkAppendResponse(
            ok=True,
            accepted=len(items),
            skipped=skipped,
            created_ts=datetime.now(timezone.utc),
        )
    except Exception as e:
        logger.error(f"Error in append_memory_bulk: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _search(request: MemoryQueryRequest):
    return await graphiti_client.search(
        request.user_id,
        request.query,
        request.limit,
        center_node_uuid=request.center_node_uuid,
        include_invalid=request.include_invalid,
        search_mode=request.search_mode,
    )


@router.post("/query", response_model=MemoryQueryResponse)
async def query_memory(
    request: MemoryQueryRequest,
    api_key: str = Depends(get_api_key)
):
    try:
        hits = await _search(request)
        return MemoryQueryResponse(
            hits=hits,
            total=len(hits)
        )
    except Exception as e:
        logger.error(f"Error in query_memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query/grouped", response_model=GroupedMemoryQueryResponse)
async def query_memory_grouped(
    request: MemoryQueryRequest,
    api_key: str = Depends(get_api_key)
):
    """
    Search memory and return results grouped by source.
    Facts from files are grouped under their file name.
    Facts from conversation are grouped under 'conversation'.
    """
    try:
        hits = await _search(request)
        
        # Group hits by source
        groups_map = {}  # source_name -> list of hits
        for hit in hits:
            file_name = hit.metadata.get("file_name") if hit.metadata else None
            if file_name:
                key = f"file:{file_name}"
                if key not in groups_map:
                    groups_map[key] = {"type": "file", "name": file_name, "facts": []}
                groups_map[key]["facts"].append(hit)
            else:
                key = "conversation"
                if key not in groups_map:
                    groups_map[key] = {"type": "conversation", "name": None, "facts": []}
                groups_map[key]["facts"].append(hit)
        
        # Build response
        groups = [
            SourceGroup(
                source_type=g["type"],
                source_name=g["name"],
                facts=g["facts"]
            )
            for g in groups_map.values()
        ]
        
        return GroupedMemoryQueryResponse(
            groups=groups,
            total_facts=len(hits)
        )
    except Exception as e:
        logger.error(f"Error in query_memory_grouped: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/summary", response_model=MemorySummaryResponse)
async def summarize_memory(
    request: MemorySummaryRequest,
    api_key: str = Depends(get_api_key)
):
    """
    Generate a summary of a user's memory episodes.

    Attempts to use LLM for intelligent summarization.
    Falls back to structured text extraction if LLM is unavailable.
    """
    try:
        # 1. Get user episodes
        episodes = await graphiti_client.get_user_episodes(request.user_id, limit=request.limit)

        if not episodes:
            return MemorySummaryResponse(summary="No episodes found for this user.")

        # 2. Extract content
        contents = []
        for ep in episodes:
            content = ep.get("content", "")
            source = ep.get("source", "unknown")
            created = ep.get("created_at", "unknown")
            if content:
                contents.append(f"[{created}] ({source}): {content}")

        combined_text = "\n".join(contents)

        # 3. Try LLM summarization
        try:
            from openai import AsyncOpenAI

            llm_client = AsyncOpenAI(
                base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
                api_key=os.getenv("LLM_API_KEY", ""),
            )

            response = await llm_client.chat.completions.create(
                model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are a memory summarizer. Create a concise summary of the user's memory episodes. Focus on key facts, preferences, and important information."},
                    {"role": "user", "content": f"Summarize these memory episodes for user {request.user_id}:\n\n{combined_text}"}
                ],
                max_tokens=500,
                temperature=0.3,
            )
            summary = response.choices[0].message.content
            return MemorySummaryResponse(summary=summary)

        except Exception as llm_error:
            logger.warning(f"LLM summarization failed, using fallback: {llm_error}")

            # 4. Fallback: structured summary
            total = len(episodes)
            sources = set(ep.get("source", "unknown") for ep in episodes)
            # Extract first 200 chars from each episode
            excerpts = []
            for ep in episodes[:5]:
                content = ep.get("content", "")
                excerpts.append(f"- {content[:200]}...")

            fallback = f"""Memory Summary for {request.user_id}

Total episodes: {total}
Sources: {', '.join(sources)}

Recent memories:
{chr(10).join(excerpts)}

(LLM summarization unavailable — showing structured extraction)"""

            return MemorySummaryResponse(summary=fallback)

    except Exception as e:
        logger.error(f"Error in summarize_memory: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/profile", response_model=MemorySummaryResponse)
async def get_user_profile(
    user_id: str,
    api_key: str = Depends(get_api_key)
):
    """
    Graph-based profile without an LLM call: community summaries if they were
    built, otherwise summaries of the user's most connected entities.
    """
    try:
        return MemorySummaryResponse(summary=await graphiti_client.get_summary(user_id))
    except Exception as e:
        logger.error(f"Error building profile for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/episodes")
async def get_user_episodes(
    user_id: str,
    limit: int = None,
    api_key: str = Depends(get_api_key)
):
    """
    Get list of episodes for a user (public endpoint with API key)
    
    Args:
        user_id: User identifier
        limit: Optional limit on number of episodes to return (most recent first)
    """
    try:
        episodes = await graphiti_client.get_user_episodes(user_id, limit=limit)
        return {"episodes": episodes, "total": len(episodes)}
    except Exception as e:
        logger.error(f"Error getting episodes for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/files")
async def delete_file(
    user_id: str,
    file_name: str,
    api_key: str = Depends(get_api_key)
):
    """
    Delete all episodes and associated orphaned data for a specific file
    """
    try:
        success = await graphiti_client.delete_file_episodes(user_id, file_name)
        if success:
            return {"ok": True, "message": f"Successfully deleted all data related to file '{file_name}' for user {user_id}"}
        else:
            raise HTTPException(status_code=500, detail=f"Failed to delete data for file '{file_name}'")
    except Exception as e:
        logger.error(f"Error in delete_file: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/users/{user_id}/files")
async def get_user_files(
    user_id: str,
    api_key: str = Depends(get_api_key)
):
    """
    Get list of files and chunk counts for a user.
    """
    try:
        files = await graphiti_client.get_user_files(user_id)
        return {"files": files, "total": len(files)}
    except Exception as e:
        logger.error(f"Error getting files for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
