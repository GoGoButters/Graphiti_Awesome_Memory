from fastapi import APIRouter, Depends, HTTPException
from app.models.schemas import AdminUsersResponse, UserStats
from app.core.auth import verify_jwt
from app.services.graphiti_client import graphiti_client
from typing import Dict, Any

router = APIRouter()

@router.get("/users", response_model=AdminUsersResponse)
async def get_users(username: str = Depends(verify_jwt)):
    # Mock implementation
    return AdminUsersResponse(users=[], total=0)

@router.get("/users/{user_id}/graph")
async def get_user_graph(user_id: str, depth: int = 2, username: str = Depends(verify_jwt)):
    return await graphiti_client.get_user_graph(user_id)

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
