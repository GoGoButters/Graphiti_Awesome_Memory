from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import AdminUsersResponse, UserStats
from app.core.auth import verify_jwt
from app.services.graphiti_client import graphiti_client
from typing import Dict, Any

router = APIRouter()

@router.get("/users", response_model=AdminUsersResponse)
async def get_users(username: str = Depends(verify_jwt)):
    """Get list of all users with their episode counts"""
    try:
        # Query Neo4j to get unique users from episodes
        # Graphiti stores episodes with source_description like "api (user)" or "n8n (user)"
        # We extract user_id from episode names which follow pattern: {user_id}_{timestamp}
        
        query = """
        MATCH (e:Episodic)
        WITH split(e.name, '_')[0] AS user_id, count(e) AS episodes_count, max(e.created_at) as last_updated
        WHERE user_id IS NOT NULL AND user_id <> ''
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
            if hasattr(last_updated, 'to_native'):
                last_updated = last_updated.to_native()
            elif hasattr(last_updated, 'iso_format'):
                last_updated = last_updated.iso_format()
                
            users.append(UserStats(
                user_id=record["user_id"], 
                episodes_count=record["episodes_count"],
                last_updated=last_updated
            ))
        
        return AdminUsersResponse(users=users, total=len(users))
    except Exception as e:
        import logging
        logging.getLogger("app.api.v1.admin").error(f"Error getting users: {e}")
        # Fallback to empty list if query fails
        return AdminUsersResponse(users=[], total=0)

@router.get("/users/{user_id}/graph")
async def get_user_graph(user_id: str, depth: int = 2, username: str = Depends(verify_jwt)):
    return await graphiti_client.get_user_graph(user_id)

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
        return {"ok": True, "message": f"User {user_id} and all associated data deleted successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to delete user")

@router.get("/users/{user_id}/episodes")
async def get_user_episodes(
    user_id: str, 
    limit: int = None,
    username: str = Depends(verify_jwt)
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
async def delete_user_file(user_id: str, file_name: str, username: str = Depends(verify_jwt)):
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
            headers={
                "Content-Disposition": f'attachment; filename="{user_id}.tar.gz"'
            }
        )
    except Exception as e:
        import logging
        logging.getLogger("app.api.v1.admin").error(f"Error creating backup for {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {str(e)}")

@router.post("/users/restore")
async def restore_user_backup(
    file: Any,  # UploadFile from fastapi
    replace: bool = False,
    username: str = Depends(verify_jwt)
):
    """
    Restore user data from backup archive
    
    Args:
        file: tar.gz backup file
        replace: If true, delete existing user data before restore
        
    Returns:
        RestoreResponse with restoration statistics
    """
    from fastapi import File, UploadFile
    from app.services.backup_service import BackupService
    from app.models.schemas import RestoreResponse
    
    # Re-declare with proper type for FastAPI
    async def _restore(file: UploadFile = File(...)):
        backup_service = BackupService(graphiti_client.client.driver)
        
        try:
            # Read uploaded file
            archive_bytes = await file.read()
            
            # Restore backup
            response = await backup_service.restore_backup(archive_bytes, replace=replace)
            
            return response
        except Exception as e:
            import logging
            logging.getLogger("app.api.v1.admin").error(f"Error restoring backup: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to restore backup: {str(e)}")
    
    return await _restore(file)

