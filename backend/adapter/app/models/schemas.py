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

class SourceGroup(BaseModel):
    """Group of facts from a single source (file or conversation)"""
    source_type: Literal["file", "conversation"] = "conversation"
    source_name: Optional[str] = None  # file name if source_type is "file"
    facts: List[MemoryHit]

class GroupedMemoryQueryResponse(BaseModel):
    """Search results grouped by source"""
    groups: List[SourceGroup]
    total_facts: int

# Backup/Restore Schemas
class BackupMetadata(BaseModel):
    """Metadata for user data backup"""
    version: str = "1.0"
    export_timestamp: datetime
    user_id: str
    total_episodes: int
    total_entities: int
    total_edges: int

class RestoreResponse(BaseModel):
    """Response from restore operation"""
    status: str
    user_id: str
    episodes_created: int = 0
    entities_created: int = 0
    edges_created: int = 0
    conflicts_skipped: int = 0
    message: str

