"""SQLite graph store for CtxGuard's personal knowledge graph memory system.

Modeled after Headroom's SQLiteGraphStore architecture with bounded SQLite storage,
fast indexed lookups, and BFS-based subgraph traversal.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional, Set

from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.graph_models import (
    Entity,
    Relationship,
    RelationshipDirection,
    Subgraph,
)

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteGraphStore:
    """SQLite-based knowledge graph repository with BFS subgraph traversal."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._lock = RLock()
        self._init_tables()

    def _init_tables(self) -> None:
        """Initialize entity and relationship tables and indexes if not exist."""
        with self._lock:
            with self.db.get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS kg_entities (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL DEFAULT 'default_user',
                        name TEXT NOT NULL,
                        name_lower TEXT NOT NULL,
                        entity_type TEXT NOT NULL DEFAULT 'concept',
                        description TEXT,
                        properties TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    )
                """)

                conn.execute("""
                    CREATE TABLE IF NOT EXISTS kg_relationships (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL DEFAULT 'default_user',
                        source_id TEXT NOT NULL,
                        target_id TEXT NOT NULL,
                        relation_type TEXT NOT NULL DEFAULT 'related_to',
                        weight REAL NOT NULL DEFAULT 1.0,
                        properties TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}',
                        FOREIGN KEY (source_id) REFERENCES kg_entities(id) ON DELETE CASCADE,
                        FOREIGN KEY (target_id) REFERENCES kg_entities(id) ON DELETE CASCADE
                    )
                """)

                # Indexes
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_user ON kg_entities(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(user_id, name_lower)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_source ON kg_relationships(source_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_target ON kg_relationships(target_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_type ON kg_relationships(relation_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_user ON kg_relationships(user_id)")
                conn.commit()

    def _row_to_entity(self, row: sqlite3.Row) -> Optional[Entity]:
        try:
            return Entity(
                id=row["id"],
                user_id=row["user_id"],
                name=row["name"],
                entity_type=row["entity_type"],
                description=row["description"],
                properties=json.loads(row["properties"]) if row["properties"] else {},
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )
        except Exception as exc:
            logger.warning("Skipping corrupted entity row %r: %s", row["id"], exc)
            return None

    def _row_to_relationship(self, row: sqlite3.Row) -> Optional[Relationship]:
        try:
            return Relationship(
                id=row["id"],
                user_id=row["user_id"],
                source_id=row["source_id"],
                target_id=row["target_id"],
                relation_type=row["relation_type"],
                weight=float(row["weight"]),
                properties=json.loads(row["properties"]) if row["properties"] else {},
                created_at=datetime.fromisoformat(row["created_at"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            )
        except Exception as exc:
            logger.warning("Skipping corrupted relationship row %r: %s", row["id"], exc)
            return None

    # --------------------------------------------------------------------------
    # Entity Operations
    # --------------------------------------------------------------------------
    def add_entity(self, entity: Entity) -> Entity:
        """Insert or update an entity (matched by user_id and case-insensitive name)."""
        with self._lock:
            existing = self.get_entity_by_name(entity.name, user_id=entity.user_id)
            with self.db.get_connection() as conn:
                now_str = _utc_now_iso()
                if existing:
                    # Update existing entity
                    merged_props = {**existing.properties, **entity.properties}
                    desc = entity.description if entity.description else existing.description
                    etype = entity.entity_type if entity.entity_type != "concept" else existing.entity_type
                    conn.execute("""
                        UPDATE kg_entities SET
                            entity_type = ?,
                            description = ?,
                            properties = ?,
                            updated_at = ?
                        WHERE id = ?
                    """, (etype, desc, json.dumps(merged_props), now_str, existing.id))
                    conn.commit()
                    entity.id = existing.id
                    entity.created_at = existing.created_at
                    entity.updated_at = datetime.now(timezone.utc)
                    entity.description = desc
                    entity.entity_type = etype
                    entity.properties = merged_props
                    return entity
                else:
                    # Insert new entity
                    conn.execute("""
                        INSERT INTO kg_entities (
                            id, user_id, name, name_lower, entity_type,
                            description, properties, created_at, updated_at, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entity.id,
                        entity.user_id,
                        entity.name,
                        entity.name_lower,
                        entity.entity_type,
                        entity.description,
                        json.dumps(entity.properties),
                        entity.created_at.isoformat(),
                        now_str,
                        json.dumps(entity.metadata),
                    ))
                    conn.commit()
                    return entity

    def get_entity_by_name(self, name: str, user_id: str = "default_user") -> Optional[Entity]:
        """Look up entity by name (case-insensitive)."""
        with self._lock:
            name_clean = name.strip().lower()
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM kg_entities WHERE user_id = ? AND name_lower = ? LIMIT 1",
                    (user_id, name_clean),
                )
                row = cursor.fetchone()
                return self._row_to_entity(row) if row else None

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Look up entity by unique ID."""
        with self._lock:
            with self.db.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM kg_entities WHERE id = ? LIMIT 1", (entity_id,))
                row = cursor.fetchone()
                return self._row_to_entity(row) if row else None

    def list_entities(
        self,
        user_id: str = "default_user",
        entity_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Entity]:
        """List entities with optional type filter."""
        with self._lock:
            with self.db.get_connection() as conn:
                if entity_type:
                    cursor = conn.execute(
                        "SELECT * FROM kg_entities WHERE user_id = ? AND entity_type = ? ORDER BY updated_at DESC LIMIT ?",
                        (user_id, entity_type, limit),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM kg_entities WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                        (user_id, limit),
                    )
                return [e for r in cursor.fetchall() if (e := self._row_to_entity(r)) is not None]

    def search_entities(
        self,
        query: str,
        user_id: str = "default_user",
        limit: int = 10,
    ) -> List[Entity]:
        """Search entities by name or description substring."""
        with self._lock:
            q_clean = f"%{query.strip().lower()}%".strip()
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM kg_entities
                    WHERE user_id = ? AND (name_lower LIKE ? OR LOWER(description) LIKE ?)
                    ORDER BY updated_at DESC LIMIT ?
                    """,
                    (user_id, q_clean, q_clean, limit),
                )
                return [e for r in cursor.fetchall() if (e := self._row_to_entity(r)) is not None]

    def delete_entity(self, entity_id: str) -> bool:
        """Delete entity and cascade delete connected relationships."""
        with self._lock:
            with self.db.get_connection() as conn:
                conn.execute("DELETE FROM kg_relationships WHERE source_id = ? OR target_id = ?", (entity_id, entity_id))
                cursor = conn.execute("DELETE FROM kg_entities WHERE id = ?", (entity_id,))
                conn.commit()
                return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Relationship Operations
    # --------------------------------------------------------------------------
    def add_relationship(self, rel: Relationship) -> Relationship:
        """Insert or update a relationship between two entities."""
        with self._lock:
            with self.db.get_connection() as conn:
                # Check if identical relationship already exists
                cursor = conn.execute("""
                    SELECT id FROM kg_relationships
                    WHERE user_id = ? AND source_id = ? AND target_id = ? AND relation_type = ?
                    LIMIT 1
                """, (rel.user_id, rel.source_id, rel.target_id, rel.relation_type))
                existing = cursor.fetchone()

                now_str = _utc_now_iso()
                if existing:
                    rel_id = existing["id"]
                    conn.execute("""
                        UPDATE kg_relationships SET weight = ?, properties = ?
                        WHERE id = ?
                    """, (rel.weight, json.dumps(rel.properties), rel_id))
                    conn.commit()
                    rel.id = rel_id
                    return rel
                else:
                    conn.execute("""
                        INSERT INTO kg_relationships (
                            id, user_id, source_id, target_id, relation_type,
                            weight, properties, created_at, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        rel.id,
                        rel.user_id,
                        rel.source_id,
                        rel.target_id,
                        rel.relation_type,
                        rel.weight,
                        json.dumps(rel.properties),
                        now_str,
                        json.dumps(rel.metadata),
                    ))
                    conn.commit()
                    return rel

    def get_relationships(
        self,
        entity_id: str,
        direction: RelationshipDirection = RelationshipDirection.BOTH,
        user_id: str = "default_user",
    ) -> List[Relationship]:
        """Get incoming, outgoing, or both relationships for an entity."""
        with self._lock:
            with self.db.get_connection() as conn:
                if direction == RelationshipDirection.OUTGOING:
                    cursor = conn.execute(
                        "SELECT * FROM kg_relationships WHERE user_id = ? AND source_id = ?",
                        (user_id, entity_id),
                    )
                elif direction == RelationshipDirection.INCOMING:
                    cursor = conn.execute(
                        "SELECT * FROM kg_relationships WHERE user_id = ? AND target_id = ?",
                        (user_id, entity_id),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM kg_relationships WHERE user_id = ? AND (source_id = ? OR target_id = ?)",
                        (user_id, entity_id, entity_id),
                    )
                return [r for row in cursor.fetchall() if (r := self._row_to_relationship(row)) is not None]

    def delete_relationship(self, relationship_id: str) -> bool:
        """Delete a relationship by ID."""
        with self._lock:
            with self.db.get_connection() as conn:
                cursor = conn.execute("DELETE FROM kg_relationships WHERE id = ?", (relationship_id,))
                conn.commit()
                return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # BFS Subgraph Traversal Algorithm (Core Multi-hop Retrieval)
    # --------------------------------------------------------------------------
    def query_subgraph(
        self,
        entity_names_or_ids: List[str],
        max_hops: int = 2,
        direction: RelationshipDirection = RelationshipDirection.BOTH,
        user_id: str = "default_user",
    ) -> Subgraph:
        """Perform Breadth-First Search (BFS) traversal starting from seed entities.

        Collects all entities and relationships within max_hops distance.
        Guarantees loop-termination with visited set tracking.
        """
        with self._lock:
            seed_entities: List[Entity] = []
            for item in entity_names_or_ids:
                e = self.get_entity_by_name(item, user_id=user_id) or self.get_entity(item)
                if e:
                    seed_entities.append(e)

            if not seed_entities:
                return Subgraph()

            visited_entity_ids: Set[str] = set()
            collected_entities: Dict[str, Entity] = {}
            collected_relationships: Dict[str, Relationship] = {}

            # Queue holds: (entity_id, current_hop)
            queue = deque((e.id, 0) for e in seed_entities)
            for e in seed_entities:
                visited_entity_ids.add(e.id)
                collected_entities[e.id] = e

            while queue:
                current_id, current_hop = queue.popleft()
                if current_hop >= max_hops:
                    continue

                # Fetch all relationships connected to current_id
                rels = self.get_relationships(current_id, direction=direction, user_id=user_id)
                for rel in rels:
                    collected_relationships[rel.id] = rel
                    neighbor_id = rel.target_id if rel.source_id == current_id else rel.source_id
                    if neighbor_id not in visited_entity_ids:
                        visited_entity_ids.add(neighbor_id)
                        neighbor_entity = self.get_entity(neighbor_id)
                        if neighbor_entity:
                            collected_entities[neighbor_id] = neighbor_entity
                            queue.append((neighbor_id, current_hop + 1))

            return Subgraph(
                entities=list(collected_entities.values()),
                relationships=list(collected_relationships.values()),
            )

    def get_stats(self, user_id: str = "default_user") -> Dict[str, Any]:
        """Get graph summary statistics."""
        with self._lock:
            with self.db.get_connection() as conn:
                c_ent = conn.execute("SELECT COUNT(*) as cnt FROM kg_entities WHERE user_id = ?", (user_id,))
                total_entities = c_ent.fetchone()["cnt"]

                c_rel = conn.execute("SELECT COUNT(*) as cnt FROM kg_relationships WHERE user_id = ?", (user_id,))
                total_relationships = c_rel.fetchone()["cnt"]

                type_cur = conn.execute("""
                    SELECT entity_type, COUNT(*) as cnt FROM kg_entities
                    WHERE user_id = ? GROUP BY entity_type ORDER BY cnt DESC
                """, (user_id,))
                type_counts = {r["entity_type"]: r["cnt"] for r in type_cur.fetchall()}

                recent_cur = conn.execute("""
                    SELECT name, entity_type, description FROM kg_entities
                    WHERE user_id = ? ORDER BY updated_at DESC LIMIT 6
                """, (user_id,))
                top_entities = [dict(r) for r in recent_cur.fetchall()]

                return {
                    "total_entities": total_entities,
                    "total_relationships": total_relationships,
                    "entity_types": type_counts,
                    "top_entities": top_entities,
                }
