from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, File, UploadFile, Query
from app.models.schemas import AdminUsersResponse, UserStats
from app.core.auth import verify_jwt
from app.core.config import settings
from app.services.graphiti_client import graphiti_client
from app.services.reprocessing_service import reprocessing_service
from typing import Dict, Any

router = APIRouter()


@router.get("/users", response_model=AdminUsersResponse)
async def get_users(username: str = Depends(verify_jwt)):
    """Get list of all users with their episode counts"""
    try:
        # Users are graphiti group_ids (exact tenancy key). Episode names
        # "{user_id}_{timestamp}" are not parsed: ids may contain "_" or "-".
        query = """
        MATCH (e:Episodic)
        WHERE e.group_id IS NOT NULL AND e.group_id <> ''
        WITH e.group_id AS user_id, count(*) AS episodes_count, max(e.created_at) AS last_updated
        RETURN user_id, episodes_count, last_updated
        ORDER BY episodes_count DESC
        """

        async with graphiti_client.client.driver.session() as session:
            result = await session.run(query)
            records = await result.data()

        users = []
        for record in records:
            last_updated = record["last_updated"]
            # Convert Neo4j DateTime to python datetime if needed
            if hasattr(last_updated, "to_native"):
                last_updated = last_updated.to_native()
            elif hasattr(last_updated, "iso_format"):
                last_updated = last_updated.iso_format()

            users.append(
                UserStats(
                    user_id=record["user_id"],
                    episodes_count=record["episodes_count"],
                    last_updated=last_updated,
                )
            )

        return AdminUsersResponse(users=users, total=len(users))
    except Exception as e:
        import logging

        logging.getLogger("app.api.v1.admin").error(f"Error getting users: {e}")
        # Fallback to empty list if query fails
        return AdminUsersResponse(users=[], total=0)


@router.get("/users/{user_id}/graph")
async def get_user_graph(
    user_id: str,
    limit: int = Query(
        default=settings.GRAPH_DEFAULT_NODES,
        ge=10,
        le=settings.GRAPH_MAX_NODES,
    ),
    username: str = Depends(verify_jwt),
):
    try:
        return await graphiti_client.get_user_graph(user_id, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load graph: {e}")


@router.get("/users/{user_id}/communities")
async def get_user_communities(user_id: str, username: str = Depends(verify_jwt)):
    """Topic clusters (Community nodes) of the user's graph, largest first."""
    try:
        communities = await graphiti_client.get_communities(user_id)
        return {"communities": communities, "total": len(communities)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load communities: {e}")


@router.get("/users/{user_id}/communities/status")
async def get_communities_status(user_id: str, username: str = Depends(verify_jwt)):
    return graphiti_client.get_community_job(user_id)


@router.post("/users/{user_id}/communities/build")
async def build_user_communities(
    user_id: str,
    background_tasks: BackgroundTasks,
    username: str = Depends(verify_jwt),
):
    """
    Rebuild communities for this user in background (label propagation +
    LLM summaries; replaces only this user's Community nodes).
    """
    job = graphiti_client.get_community_job(user_id)
    if job.get("status") == "running":
        return {"status": "running"}
    background_tasks.add_task(graphiti_client.build_communities_for_user, user_id)
    return {"status": "started"}


@router.get("/users/{user_id}/communities/{community_uuid}/members")
async def get_community_members(
    user_id: str,
    community_uuid: str,
    limit: int = Query(
        default=settings.GRAPH_DEFAULT_NODES,
        ge=10,
        le=settings.GRAPH_MAX_NODES,
    ),
    username: str = Depends(verify_jwt),
):
    try:
        return await graphiti_client.get_community_members_graph(
            user_id, community_uuid, limit=limit
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load community: {e}")


@router.post("/consolidate")
async def run_consolidation(username: str = Depends(verify_jwt)):
    """Run the nightly consolidation now (non-destructive unless configured)."""
    return await graphiti_client.consolidate()


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, username: str = Depends(verify_jwt)):
    """
    Delete user and all associated data from Neo4j

    This will permanently delete:
    - All episodes for this user
    - All entities (nodes)
    - All relationships (edges)
    """
    success = await graphiti_client.delete_user(user_id)

    if success:
        return {
            "ok": True,
            "message": f"User {user_id} and all associated data deleted successfully",
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to delete user")


@router.get("/users/{user_id}/episodes")
async def get_user_episodes(
    user_id: str, limit: int = None, username: str = Depends(verify_jwt)
):
    """
    Get list of episodes for a user

    Args:
        user_id: User identifier
        limit: Optional limit on number of episodes to return (most recent first)
    """
    episodes = await graphiti_client.get_user_episodes(user_id, limit=limit)
    return {"episodes": episodes, "total": len(episodes)}


@router.delete("/episodes/{uuid}")
async def delete_episode(uuid: str, username: str = Depends(verify_jwt)):
    """Delete a specific episode"""
    success = await graphiti_client.delete_episode(uuid)
    if success:
        return {"ok": True, "message": f"Episode {uuid} deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete episode")


@router.post("/login")
async def login(credentials: Dict[str, str]):
    from app.core.config import settings
    from app.core.auth import create_access_token

    username = credentials.get("username")
    password = credentials.get("password")

    if username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD:
        token = create_access_token({"sub": username})
        return {"access_token": token, "token_type": "bearer"}

    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/metrics")
async def get_metrics(username: str = Depends(verify_jwt)):
    return {"status": "ok", "queue_length": 0}


@router.get("/users/{user_id}/files")
async def get_user_files(user_id: str, username: str = Depends(verify_jwt)):
    """Get list of files for a user"""
    files = await graphiti_client.get_user_files(user_id)
    return {"files": files, "total": len(files)}


@router.delete("/users/{user_id}/files")
async def delete_user_file(
    user_id: str, file_name: str, username: str = Depends(verify_jwt)
):
    """Delete all chunks related to a file"""
    success = await graphiti_client.delete_file_episodes(user_id, file_name)
    if success:
        return {"ok": True, "message": f"File {file_name} deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete file")


@router.get("/users/{user_id}/backup")
async def download_user_backup(user_id: str, username: str = Depends(verify_jwt)):
    """
    Download complete user data backup as tar.gz archive

    Returns a tar.gz file containing:
    - metadata.json: Export version, timestamp, counts
    - episodes.json: All user episodes
    - entities.json: All entities
    - edges.json: All relationships
    """
    from fastapi.responses import Response
    from app.services.backup_service import BackupService

    backup_service = BackupService(graphiti_client.client.driver)

    try:
        archive_bytes = await backup_service.create_backup(user_id)

        return Response(
            content=archive_bytes,
            media_type="application/gzip",
            headers={"Content-Disposition": f'attachment; filename="{user_id}.tar.gz"'},
        )
    except Exception as e:
        import logging

        logging.getLogger("app.api.v1.admin").error(
            f"Error creating backup for {user_id}: {e}"
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to create backup: {str(e)}"
        )


@router.post("/users/restore")
async def restore_user_backup(
    file: UploadFile = File(...),
    replace: bool = False,
    new_user_id: str = None,
    username: str = Depends(verify_jwt),
):
    """
    Restore user data from backup archive

    Args:
        file: tar.gz backup file
        replace: If true, delete existing user data before restore
        new_user_id: Optional new user ID (for renaming during restore)

    Returns:
        RestoreResponse with restoration statistics
    """
    from fastapi import UploadFile, File
    from app.services.backup_service import BackupService
    from app.models.schemas import RestoreResponse

    backup_service = BackupService(graphiti_client.client.driver)

    try:
        # Read uploaded file
        archive_bytes = await file.read()

        # Restore backup with optional new user ID
        response = await backup_service.restore_backup(
            archive_bytes, replace=replace, new_user_id=new_user_id
        )

        return response
    except Exception as e:
        import logging

        logging.getLogger("app.api.v1.admin").error(
            f"Error restoring backup: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to restore backup: {str(e)}"
        )


@router.post("/reprocess/{user_id}")
async def reprocess_user_episodes(user_id: str, username: str = Depends(verify_jwt)):
    """
    Reprocess all episodes for a specific user to rebuild knowledge graph

    WARNING: This is an expensive operation that will make LLM calls for each episode

    Args:
        user_id: User ID to reprocess

    Returns:
        Statistics about reprocessing
    """
    try:
        result = await reprocessing_service.reprocess_user(user_id)
        return result
    except Exception as e:
        import logging

        logging.getLogger("app.api.v1.admin").error(
            f"Error reprocessing user {user_id}: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to reprocess user: {str(e)}"
        )


@router.post("/reprocess-all")
async def reprocess_all_users(username: str = Depends(verify_jwt)):
    """
    Reprocess all episodes for ALL users to rebuild knowledge graph

    WARNING: This is a VERY expensive operation that will:
    - Make LLM calls for every episode in the database
    - Take a long time to complete
    - Cost significant API credits

    Returns:
        Overall statistics about reprocessing
    """
    try:
        result = await reprocessing_service.reprocess_all_users()
        return result
    except Exception as e:
        import logging

        logging.getLogger("app.api.v1.admin").error(
            f"Error reprocessing all users: {e}", exc_info=True
        )
        raise HTTPException(
            status_code=500, detail=f"Failed to reprocess all users: {str(e)}"
        )
