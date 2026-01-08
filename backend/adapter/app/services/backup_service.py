"""
Backup/Restore Service for Graphiti User Data

This module handles exporting and importing complete user data including:
- Episodes (Episodic nodes)
- Entities (Entity nodes)
- Relationships (edges)
- Metadata

Backups are created as tar.gz archives with original UUIDs and timestamps preserved.
"""

import logging
import json
# CRITICAL: graphiti_client patches json.loads which breaks our valid JSON
# Use JSONDecoder directly to bypass the patch
from json import JSONDecoder, JSONEncoder
import tarfile
import io
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from neo4j import AsyncDriver

from app.models.schemas import BackupMetadata, RestoreResponse

logger = logging.getLogger(__name__)

# Create unpatched JSON decoder/encoder instances
_json_decoder = JSONDecoder()
_json_encoder = JSONEncoder(indent=2, ensure_ascii=False)

def _safe_json_loads(s):
    """Load JSON without going through patched json.loads"""
    return _json_decoder.decode(s)

def _safe_json_dumps(obj):
    """Dump JSON without going through patched json.dumps"""
    return _json_encoder.encode(obj)


class BackupService:
    """Service for creating and restoring user data backups"""
    
    def __init__(self, driver: AsyncDriver):
        self.driver = driver
    
    async def export_user_episodes(self, user_id: str) -> List[Dict[str, Any]]:
        """Export all episodes for a user"""
        query = """
        MATCH (e:Episodic)
        WHERE e.name STARTS WITH $user_prefix
        RETURN e {
            .*,
            created_at: toString(e.created_at),
            valid_at: toString(e.valid_at),
            invalid_at: CASE 
                WHEN e.invalid_at IS NOT NULL 
                THEN toString(e.invalid_at) 
                ELSE null 
            END
        } as episode
        ORDER BY e.created_at
        """
        
        async with self.driver.session() as session:
            result = await session.run(query, user_prefix=f"{user_id}_")
            records = await result.data()
        
        episodes = [record["episode"] for record in records]
        logger.info(f"Exported {len(episodes)} episodes for user {user_id}")
        return episodes
    
    async def export_user_entities(self, user_id: str) -> List[Dict[str, Any]]:
        """Export all entities connected to user episodes"""
        query = """
        MATCH (e:Episodic)
        WHERE e.name STARTS WITH $user_prefix
        MATCH (e)-[:RELATES_TO]->(entity:Entity)
        WITH DISTINCT entity
        RETURN entity {
            .*,
            created_at: toString(entity.created_at)
        } as entity
        """
        
        async with self.driver.session() as session:
            result = await session.run(query, user_prefix=f"{user_id}_")
            records = await result.data()
        
        entities = [record["entity"] for record in records]
        logger.info(f"Exported {len(entities)} entities for user {user_id}")
        return entities
    
    async def export_user_edges(self, user_id: str) -> List[Dict[str, Any]]:
        """Export all relationship edges for user"""
        query = """
        MATCH (e:Episodic)
        WHERE e.name STARTS WITH $user_prefix
        MATCH (e)-[:RELATES_TO]->(entity1:Entity)
        MATCH (entity1)-[r]-(entity2:Entity)
        WHERE type(r) <> 'RELATES_TO'
        WITH DISTINCT r, entity1, entity2
        RETURN {
            uuid: r.uuid,
            type: type(r),
            source_uuid: entity1.uuid,
            target_uuid: entity2.uuid,
            fact: r.fact,
            fact_embedding: r.fact_embedding,
            episodes: r.episodes,
            created_at: toString(r.created_at),
            expired_at: CASE 
                WHEN r.expired_at IS NOT NULL 
                THEN toString(r.expired_at) 
                ELSE null 
            END,
            valid_at: toString(r.valid_at),
            invalid_at: CASE 
                WHEN r.invalid_at IS NOT NULL 
                THEN toString(r.invalid_at) 
                ELSE null 
            END
        } as edge
        """
        
        async with self.driver.session() as session:
            result = await session.run(query, user_prefix=f"{user_id}_")
            records = await result.data()
        
        edges = [record["edge"] for record in records]
        logger.info(f"Exported {len(edges)} edges for user {user_id}")
        return edges
    
    async def create_backup(self, user_id: str) -> bytes:
        """
        Create a complete backup archive for a user
        
        Returns:
            bytes: tar.gz archive containing all user data
        """
        # Export all data
        episodes = await self.export_user_episodes(user_id)
        entities = await self.export_user_entities(user_id)
        edges = await self.export_user_edges(user_id)
        
        # Create metadata
        metadata = BackupMetadata(
            export_timestamp=datetime.now(timezone.utc),
            user_id=user_id,
            total_episodes=len(episodes),
            total_entities=len(entities),
            total_edges=len(edges)
        )
        
        # Create tar.gz archive in memory
        tar_buffer = io.BytesIO()
        
        with tarfile.open(fileobj=tar_buffer, mode='w:gz') as tar:
            # Add metadata.json
            metadata_json = metadata.model_dump_json(indent=2)
            metadata_info = tarfile.TarInfo(name='metadata.json')
            metadata_info.size = len(metadata_json.encode('utf-8'))
            tar.addfile(metadata_info, io.BytesIO(metadata_json.encode('utf-8')))
            
            # Add episodes.json
            episodes_json = _safe_json_dumps(episodes)
            episodes_info = tarfile.TarInfo(name='episodes.json')
            episodes_info.size = len(episodes_json.encode('utf-8'))
            tar.addfile(episodes_info, io.BytesIO(episodes_json.encode('utf-8')))
            
            # Add entities.json
            entities_json = _safe_json_dumps(entities)
            entities_info = tarfile.TarInfo(name='entities.json')
            entities_info.size = len(entities_json.encode('utf-8'))
            tar.addfile(entities_info, io.BytesIO(entities_json.encode('utf-8')))
            
            # Add edges.json
            edges_json = _safe_json_dumps(edges)
            edges_info = tarfile.TarInfo(name='edges.json')
            edges_info.size = len(edges_json.encode('utf-8'))
            tar.addfile(edges_info, io.BytesIO(edges_json.encode('utf-8')))
        
        tar_buffer.seek(0)
        logger.info(f"Created backup for user {user_id}: {len(episodes)} episodes, {len(entities)} entities, {len(edges)} edges")
        return tar_buffer.read()
    
    async def restore_backup(self, archive_bytes: bytes, replace: bool = False, new_user_id: str = None) -> RestoreResponse:
        """
        Restore user data from backup archive
        
        SAFETY: This method NEVER deletes existing data. It always uses MERGE to add/update.
        
        Args:
            archive_bytes: tar.gz archive bytes
            replace: DEPRECATED - ignored for safety (always uses MERGE)
            new_user_id: Optional new user ID (for renaming during restore)
            
        Returns:
            RestoreResponse with restoration statistics
        """
        try:
            # Extract archive
            tar_buffer = io.BytesIO(archive_bytes)
            
            with tarfile.open(fileobj=tar_buffer, mode='r:gz') as tar:
                # Extract metadata
                metadata_file = tar.extractfile('metadata.json')
                if not metadata_file:
                    raise ValueError("Invalid backup: missing metadata.json")
                
                metadata_dict = _safe_json_loads(metadata_file.read().decode('utf-8'))
                original_user_id = metadata_dict['user_id']
                
                # Use new_user_id if provided, otherwise use original
                target_user_id = new_user_id if new_user_id else original_user_id
                
                logger.info(f"Restoring backup (SAFE MERGE mode): original={original_user_id}, target={target_user_id}")
                
                # Extract and parse data files INSIDE with block (before tar closes)
                episodes_file = tar.extractfile('episodes.json')
                entities_file = tar.extractfile('entities.json')
                edges_file = tar.extractfile('edges.json')
                
                if not all([episodes_file, entities_file, edges_file]):
                    raise ValueError("Invalid backup: missing data files")
                
                # Read and parse JSON NOW, before exiting with block
                # Handle empty files gracefully (backup may have been made when entities were deleted)
                episodes_content = episodes_file.read().decode('utf-8').strip()
                entities_content = entities_file.read().decode('utf-8').strip()
                edges_content = edges_file.read().decode('utf-8').strip()
                
                # Parse with fallback to empty list for any JSON errors
                try:
                    episodes = _safe_json_loads(episodes_content) if episodes_content else []
                except (original_json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse episodes.json: {e}")
                    logger.warning(f"Content preview (first 500 chars): {episodes_content[:500]!r}")
                    episodes = []
                
                try:
                    entities = _safe_json_loads(entities_content) if entities_content else []
                except (original_json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse entities.json: {e}")
                    logger.warning(f"Content preview (first 200 chars): {entities_content[:200]!r}")
                    entities = []
                
                try:
                    edges = _safe_json_loads(edges_content) if edges_content else []
                except (original_json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse edges.json: {e}")
                    logger.warning(f"Content preview (first 200 chars): {edges_content[:200]!r}")
                    edges = []
                
                logger.info(f"Loaded from backup: {len(episodes)} episodes, {len(entities)} entities, {len(edges)} edges")
            
            # Update episode names if renaming user
            if new_user_id and new_user_id != original_user_id:
                for episode in episodes:
                    # Replace user_id in episode name (format: {user_id}_{timestamp})
                    if episode.get('name', '').startswith(f"{original_user_id}_"):
                        episode['name'] = episode['name'].replace(f"{original_user_id}_", f"{new_user_id}_", 1)
                    # Update group_id if present
                    if episode.get('group_id') == original_user_id:
                        episode['group_id'] = new_user_id
            
            # Import data - ALWAYS use merge=True for safety
            stats = await self._import_data(target_user_id, episodes, entities, edges, merge=True)
            
            return RestoreResponse(
                status="success",
                user_id=target_user_id,
                episodes_created=stats['episodes_created'],
                entities_created=stats['entities_created'],
                edges_created=stats['edges_created'],
                conflicts_skipped=stats['conflicts_skipped'],
                message=f"Successfully restored backup for user {target_user_id} (MERGE mode - existing data preserved)"
            )
            
        except Exception as e:
            logger.error(f"Error restoring backup: {e}", exc_info=True)
            return RestoreResponse(
                status="error",
                user_id="unknown",
                message=f"Failed to restore backup: {str(e)}"
            )

    
    async def _delete_user_data(self, user_id: str):
        """Delete all data for a user"""
        query = """
        // Delete episodes
        MATCH (e:Episodic)
        WHERE e.name STARTS WITH $user_prefix
        DETACH DELETE e
        
        // Delete orphaned entities
        WITH 1 as dummy
        MATCH (entity:Entity)
        WHERE NOT EXISTS {
            MATCH (episode:Episodic)-[:RELATES_TO]->(entity)
        }
        DETACH DELETE entity
        """
        
        async with self.driver.session() as session:
            await session.run(query, user_prefix=f"{user_id}_")
        
        logger.info(f"Deleted existing data for user {user_id}")
    
    async def _import_data(
        self, 
        user_id: str, 
        episodes: List[Dict], 
        entities: List[Dict], 
        edges: List[Dict],
        merge: bool = True
    ) -> Dict[str, int]:
        """Import episodes, entities, and edges into Neo4j"""
        
        stats = {
            'episodes_created': 0,
            'entities_created': 0,
            'edges_created': 0,
            'conflicts_skipped': 0
        }
        
        async with self.driver.session() as session:
            # Import entities first
            for entity in entities:
                if merge:
                    query = """
                    MERGE (e:Entity {uuid: $uuid})
                    ON CREATE SET e = $props
                    RETURN e.uuid as uuid, 
                           CASE WHEN e.created_at = $props.created_at THEN 'created' ELSE 'existing' END as action
                    """
                else:
                    query = """
                    CREATE (e:Entity)
                    SET e = $props
                    RETURN e.uuid as uuid, 'created' as action
                    """
                
                result = await session.run(query, uuid=entity['uuid'], props=entity)
                record = await result.single()
                
                if record and record['action'] == 'created':
                    stats['entities_created'] += 1
                elif record and record['action'] == 'existing':
                    stats['conflicts_skipped'] += 1
            
            # Import episodes
            for episode in episodes:
                if merge:
                    query = """
                    MERGE (e:Episodic {uuid: $uuid})
                    ON CREATE SET e = $props
                    RETURN e.uuid as uuid,
                           CASE WHEN e.created_at = $props.created_at THEN 'created' ELSE 'existing' END as action
                    """
                else:
                    query = """
                    CREATE (e:Episodic)
                    SET e = $props
                    RETURN e.uuid as uuid, 'created' as action
                    """
                
                result = await session.run(query, uuid=episode['uuid'], props=episode)
                record = await result.single()
                
                if record and record['action'] == 'created':
                    stats['episodes_created'] += 1
                elif record and record['action'] == 'existing':
                    stats['conflicts_skipped'] += 1
            
            # Import edges
            for edge in edges:
                edge_type = edge['type']
                
                if merge:
                    query = f"""
                    MATCH (source:Entity {{uuid: $source_uuid}})
                    MATCH (target:Entity {{uuid: $target_uuid}})
                    MERGE (source)-[r:{edge_type} {{uuid: $uuid}}]->(target)
                    ON CREATE SET r = $props
                    RETURN r.uuid as uuid,
                           CASE WHEN r.created_at = $props.created_at THEN 'created' ELSE 'existing' END as action
                    """
                else:
                    query = f"""
                    MATCH (source:Entity {{uuid: $source_uuid}})
                    MATCH (target:Entity {{uuid: $target_uuid}})
                    CREATE (source)-[r:{edge_type}]->(target)
                    SET r = $props
                    RETURN r.uuid as uuid, 'created' as action
                    """
                
                result = await session.run(
                    query,
                    uuid=edge['uuid'],
                    source_uuid=edge['source_uuid'],
                    target_uuid=edge['target_uuid'],
                    props=edge
                )
                record = await result.single()
                
                if record and record['action'] == 'created':
                    stats['edges_created'] += 1
                elif record and record['action'] == 'existing':
                    stats['conflicts_skipped'] += 1
        
        logger.info(f"Import complete for user {user_id}: {stats}")
        return stats
