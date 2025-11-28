from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from pydantic import BaseModel, Field

class MemoryAppendRequest(BaseModel):
    user_id: str
    text: str
    role: Literal["user", "assistant", "system"] = "user"
    metadata: Optional[Dict[str, Any]] = {}

class MemoryAppendResponse(BaseModel):
    ok: bool
    id: str
    created_ts: datetime

class MemoryQueryRequest(BaseModel):
    user_id: str
    query: str
    limit: int = 10

class MemoryHit(BaseModel):
    fact: str  # The relationship fact from Graphiti
    score: float
    uuid: str
    created_at: datetime
    metadata: Optional[Dict[str, Any]] = {}

class MemoryQueryResponse(BaseModel):
    hits: List[MemoryHit]
    total: int

class MemorySummaryRequest(BaseModel):
    user_id: str
    limit: int = 100

class MemorySummaryResponse(BaseModel):
    summary: str

# Admin Schemas
class UserStats(BaseModel):
    user_id: str
    episodes_count: int
    last_updated: Optional[datetime]

class AdminUsersResponse(BaseModel):
    users: List[UserStats]
    total: int
