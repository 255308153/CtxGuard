"""SQLite graph store for CtxGuard's personal knowledge graph memory system.

Modeled after CtxGuard Engine's SQLiteGraphStore architecture with bounded SQLite storage,
fast indexed lookups, BFS-based subgraph traversal, and supersession chain support.

Key design principles (from ctxguard 05-长期记忆):
  - Supersession Chain: facts are never deleted, only timestamped as superseded.
  - Active-Only Retrieval: all queries default to valid_until IS NULL.
  - FTS5 BM25: keyword retrieval for code symbols and proper nouns (Gap 2).
  - RecencyBoostRanker: time-decay scoring to prefer fresh memories (Gap 4).
"""

from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
from collections import deque
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Dict, List, Optional, Set, Tuple

from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.graph_models import (
    Entity,
    MemoryScope,
    Relationship,
    RelationshipDirection,
    Subgraph,
)

logger = logging.getLogger(__name__)

# Recency decay: score = exp(-lambda * days). lambda=0.05 means 14-day-old ~50%.
_RECENCY_LAMBDA = 0.05


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_fts_query(query: str) -> str:
    """Convert a natural-language query into an FTS5 OR-connected phrase query.

    Each token is wrapped in double-quotes to prevent FTS5 operator injection,
    then joined with OR so any matching token triggers a hit (BM25 then ranks).
    """
    words = re.findall(r"\w+", query)
    if not words:
        return ""
    escaped = [f'"{w}"' for w in words]
    return " OR ".join(escaped)


def _recency_score(created_at: datetime) -> float:
    """Compute a freshness multiplier in [0, 1] using exponential decay."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - created_at
    days = max(0.0, delta.total_seconds() / 86400.0)
    return math.exp(-_RECENCY_LAMBDA * days)


class SQLiteGraphStore:
    """SQLite-based knowledge graph repository with BFS subgraph traversal.

    Schema additions vs. original:
      kg_entities: + valid_from, valid_until, supersedes, superseded_by,
                     scope, session_id
      kg_entities_fts: FTS5 virtual table for BM25 keyword search (Gap 2)
    """

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
                        metadata TEXT NOT NULL DEFAULT '{}',
                        valid_from TEXT NOT NULL DEFAULT '',
                        valid_until TEXT,
                        supersedes TEXT,
                        superseded_by TEXT,
                        scope TEXT NOT NULL DEFAULT 'user',
                        session_id TEXT
                    )
                """)

                # Migrate existing databases: add new columns if they don't exist
                existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(kg_entities)").fetchall()}
                for col, defn in [
                    ("valid_from", "TEXT NOT NULL DEFAULT ''"),
                    ("valid_until", "TEXT"),
                    ("supersedes", "TEXT"),
                    ("superseded_by", "TEXT"),
                    ("scope", "TEXT NOT NULL DEFAULT 'user'"),
                    ("session_id", "TEXT"),
                ]:
                    if col not in existing_cols:
                        conn.execute(f"ALTER TABLE kg_entities ADD COLUMN {col} {defn}")

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

                # FTS5 virtual table — trigram tokenizer for CJK substring matching (Gap 2)
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS kg_entities_fts
                    USING fts5(
                        entity_id UNINDEXED,
                        name,
                        description,
                        tokenize='trigram'
                    )
                """)

                # Indexes
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_user ON kg_entities(user_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_name ON kg_entities(user_id, name_lower)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_type ON kg_entities(entity_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_entities_active ON kg_entities(user_id, valid_until)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_source ON kg_relationships(source_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_target ON kg_relationships(target_id)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_type ON kg_relationships(relation_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_user ON kg_relationships(user_id)")
                conn.commit()

    # --------------------------------------------------------------------------
    # Internal Helpers
    # --------------------------------------------------------------------------
    def _row_to_entity(self, row: sqlite3.Row) -> Optional[Entity]:
        try:
            def _parse_dt(val: Optional[str]) -> Optional[datetime]:
                if not val:
                    return None
                try:
                    return datetime.fromisoformat(val)
                except (ValueError, TypeError):
                    return None

            keys = row.keys()
            valid_from_raw = row["valid_from"] if "valid_from" in keys else None
            valid_from = _parse_dt(valid_from_raw) or datetime.fromisoformat(row["created_at"])

            scope_raw = row["scope"] if "scope" in keys else "user"
            try:
                scope = MemoryScope(scope_raw or "user")
            except ValueError:
                scope = MemoryScope.USER

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
                valid_from=valid_from,
                valid_until=_parse_dt(row["valid_until"] if "valid_until" in keys else None),
                supersedes=row["supersedes"] if "supersedes" in keys else None,
                superseded_by=row["superseded_by"] if "superseded_by" in keys else None,
                scope=scope,
                session_id=row["session_id"] if "session_id" in keys else None,
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

    def _fts_upsert(self, conn: sqlite3.Connection, entity: Optional[Entity]) -> None:
        """Sync FTS5 index for an entity. Only active entities are indexed."""
        if entity is None:
            return
        conn.execute("DELETE FROM kg_entities_fts WHERE entity_id = ?", (entity.id,))
        if entity.is_active:
            conn.execute(
                "INSERT INTO kg_entities_fts(entity_id, name, description) VALUES (?, ?, ?)",
                (entity.id, entity.name, entity.description or ""),
            )

    def _fts_remove(self, conn: sqlite3.Connection, entity_id: str) -> None:
        """Remove an entity from FTS5 index (Iron Rule: called on supersession)."""
        conn.execute("DELETE FROM kg_entities_fts WHERE entity_id = ?", (entity_id,))

    # --------------------------------------------------------------------------
    # Entity Operations
    # --------------------------------------------------------------------------
    def add_entity(self, entity: Entity) -> Entity:
        """Insert or update an entity (matched by user_id and case-insensitive name)."""
        with self._lock:
            existing = self.get_entity_by_name(entity.name, user_id=entity.user_id)
            with self.db.get_connection() as conn:
                now_str = _utc_now_iso()
                if existing and existing.is_active:
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
                    entity.id = existing.id
                    entity.created_at = existing.created_at
                    entity.updated_at = datetime.now(timezone.utc)
                    entity.description = desc
                    entity.entity_type = etype
                    entity.properties = merged_props
                    entity.valid_from = existing.valid_from
                    self._fts_upsert(conn, entity)
                    conn.commit()
                    return entity
                else:
                    conn.execute("""
                        INSERT INTO kg_entities (
                            id, user_id, name, name_lower, entity_type,
                            description, properties, created_at, updated_at, metadata,
                            valid_from, valid_until, supersedes, superseded_by, scope, session_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        entity.valid_from.isoformat(),
                        entity.valid_until.isoformat() if entity.valid_until else None,
                        entity.supersedes,
                        entity.superseded_by,
                        entity.scope.value,
                        entity.session_id,
                    ))
                    self._fts_upsert(conn, entity)
                    conn.commit()
                    return entity

    def get_entity_by_name(
        self,
        name: str,
        user_id: str = "default_user",
        active_only: bool = True,
    ) -> Optional[Entity]:
        """Look up entity by name (case-insensitive). Returns only active facts by default."""
        with self._lock:
            name_clean = name.strip().lower()
            with self.db.get_connection() as conn:
                if active_only:
                    cursor = conn.execute(
                        "SELECT * FROM kg_entities WHERE user_id = ? AND name_lower = ? AND valid_until IS NULL LIMIT 1",
                        (user_id, name_clean),
                    )
                else:
                    cursor = conn.execute(
                        "SELECT * FROM kg_entities WHERE user_id = ? AND name_lower = ? ORDER BY created_at DESC LIMIT 1",
                        (user_id, name_clean),
                    )
                row = cursor.fetchone()
                return self._row_to_entity(row) if row else None

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Look up entity by unique ID (regardless of supersession status)."""
        with self._lock:
            with self.db.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM kg_entities WHERE id = ? LIMIT 1", (entity_id,))
                row = cursor.fetchone()
                return self._row_to_entity(row) if row else None

    def list_entities(
        self,
        user_id: str = "default_user",
        entity_type: Optional[str] = None,
        active_only: bool = True,
        limit: int = 100,
    ) -> List[Entity]:
        """List entities with optional type filter. Defaults to active-only."""
        with self._lock:
            with self.db.get_connection() as conn:
                base = "SELECT * FROM kg_entities WHERE user_id = ?"
                params: list = [user_id]
                if active_only:
                    base += " AND valid_until IS NULL"
                if entity_type:
                    base += " AND entity_type = ?"
                    params.append(entity_type)
                base += " ORDER BY updated_at DESC LIMIT ?"
                params.append(limit)
                cursor = conn.execute(base, params)
                return [e for r in cursor.fetchall() if (e := self._row_to_entity(r)) is not None]

    def search_entities(
        self,
        query: str,
        user_id: str = "default_user",
        limit: int = 10,
        active_only: bool = True,
    ) -> List[Entity]:
        """Search entities using FTS5/BM25 keyword search (Gap 2).

        Uses trigram-based FTS5 for CJK + English. Falls back to LIKE if FTS unavailable.
        """
        with self._lock:
            fts_q = _sanitize_fts_query(query)
            results: List[Entity] = []

            with self.db.get_connection() as conn:
                if fts_q:
                    try:
                        active_clause = "AND e.valid_until IS NULL" if active_only else ""
                        cursor = conn.execute(f"""
                            SELECT e.* FROM kg_entities e
                            INNER JOIN kg_entities_fts fts ON e.id = fts.entity_id
                            WHERE e.user_id = ?
                              AND fts.kg_entities_fts MATCH ?
                              {active_clause}
                            ORDER BY rank
                            LIMIT ?
                        """, (user_id, fts_q, limit))
                        results = [e for r in cursor.fetchall() if (e := self._row_to_entity(r)) is not None]
                    except sqlite3.OperationalError:
                        pass  # FTS table empty or unavailable; fall through

                if not results:
                    q_clean = f"%{query.strip().lower()}%"
                    base = """
                        SELECT * FROM kg_entities
                        WHERE user_id = ? AND (name_lower LIKE ? OR LOWER(description) LIKE ?)
                    """
                    params: list = [user_id, q_clean, q_clean]
                    if active_only:
                        base += " AND valid_until IS NULL"
                    base += " ORDER BY updated_at DESC LIMIT ?"
                    params.append(limit)
                    cursor = conn.execute(base, params)
                    results = [e for r in cursor.fetchall() if (e := self._row_to_entity(r)) is not None]

            return results

    def delete_entity(self, entity_id: str) -> bool:
        """Delete entity and cascade delete connected relationships."""
        with self._lock:
            with self.db.get_connection() as conn:
                self._fts_remove(conn, entity_id)
                conn.execute("DELETE FROM kg_relationships WHERE source_id = ? OR target_id = ?", (entity_id, entity_id))
                cursor = conn.execute("DELETE FROM kg_entities WHERE id = ?", (entity_id,))
                conn.commit()
                return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # Supersession Chain (Gap 1)
    # --------------------------------------------------------------------------
    def supersede(
        self,
        old_entity_id: str,
        new_content: str,
        new_description: Optional[str] = None,
        new_metadata: Optional[Dict[str, Any]] = None,
    ) -> Entity:
        """Atomically supersede an existing entity with new content.

        Old entity is stamped with valid_until=now and superseded_by=new.id.
        New entity is inserted with supersedes=old.id and valid_from=now.
        Both operations are in a single transaction (atomic).
        Old entity is immediately removed from FTS (Iron Rule, Issue #2143).

        Raises:
            ValueError: If old_entity_id not found or already superseded.
        """
        with self._lock:
            old = self.get_entity(old_entity_id)
            if old is None:
                raise ValueError(f"Entity not found: {old_entity_id}")
            if not old.is_active:
                raise ValueError(
                    f"Entity {old_entity_id!r} is already superseded "
                    f"(superseded_by={old.superseded_by}). Use the replacement entity instead."
                )

            import uuid as _uuid
            now_str = _utc_now_iso()
            new_id = str(_uuid.uuid4())[:8]

            with self.db.get_connection() as conn:
                # Step 1: Stamp old entity as superseded
                conn.execute("""
                    UPDATE kg_entities
                    SET valid_until = ?, superseded_by = ?, updated_at = ?
                    WHERE id = ?
                """, (now_str, new_id, now_str, old_entity_id))

                # Iron Rule: Remove old entity from FTS immediately
                self._fts_remove(conn, old_entity_id)

                # Step 2: Insert replacement entity
                now_dt = datetime.fromisoformat(now_str)
                conn.execute("""
                    INSERT INTO kg_entities (
                        id, user_id, name, name_lower, entity_type,
                        description, properties, created_at, updated_at, metadata,
                        valid_from, valid_until, supersedes, superseded_by, scope, session_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    new_id,
                    old.user_id,
                    new_content,
                    new_content.strip().lower(),
                    old.entity_type,
                    new_description or old.description,
                    json.dumps(old.properties),
                    now_str,
                    now_str,
                    json.dumps({**(old.metadata or {}), **(new_metadata or {}), "supersedes": old_entity_id}),
                    now_str,   # valid_from
                    None,      # valid_until (active)
                    old_entity_id,  # supersedes
                    None,      # superseded_by
                    old.scope.value,
                    old.session_id,
                ))

                # Index the new entity in FTS
                new_entity = Entity(
                    id=new_id,
                    user_id=old.user_id,
                    name=new_content,
                    entity_type=old.entity_type,
                    description=new_description or old.description,
                    valid_from=now_dt,
                    supersedes=old_entity_id,
                    scope=old.scope,
                    session_id=old.session_id,
                )
                self._fts_upsert(conn, new_entity)
                conn.commit()

            logger.info("[Supersession] (%s) '%s' -> (%s) '%s'", old_entity_id, old.name, new_id, new_content)
            return new_entity

    def detach_supersession(self, old_entity_id: str, new_entity_id: str) -> bool:
        """Atomically undo a supersession — restores old entity as active.

        Used when an Agent made an incorrect supersession and needs to roll back.
        Returns True if detach succeeded, False if no matching chain was found.
        """
        with self._lock:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT id FROM kg_entities WHERE id = ? AND superseded_by = ?",
                    (old_entity_id, new_entity_id),
                )
                if not cursor.fetchone():
                    logger.warning(
                        "detach_supersession: no chain %r -> %r", old_entity_id, new_entity_id
                    )
                    return False

                now_str = _utc_now_iso()
                # Resurrect old entity
                conn.execute("""
                    UPDATE kg_entities
                    SET valid_until = NULL, superseded_by = NULL, updated_at = ?
                    WHERE id = ?
                """, (now_str, old_entity_id))
                old_entity = self.get_entity(old_entity_id)
                self._fts_upsert(conn, old_entity)

                # Retire the (wrong) new entity
                conn.execute("""
                    UPDATE kg_entities SET valid_until = ?, updated_at = ? WHERE id = ?
                """, (now_str, now_str, new_entity_id))
                self._fts_remove(conn, new_entity_id)
                conn.commit()

            logger.info("[Supersession] Detached: %r resurrected, %r retired.", old_entity_id, new_entity_id)
            return True

    def get_history(self, entity_id: str) -> List[Tuple[Entity, bool]]:
        """Walk the supersession chain and return full version history (oldest first).

        Returns:
            List of (Entity, is_current) tuples ordered oldest -> newest.
        """
        with self._lock:
            visited: Set[str] = set()
            chain: List[Entity] = []

            # Walk backward to root
            current_id: Optional[str] = entity_id
            while current_id and current_id not in visited:
                visited.add(current_id)
                e = self.get_entity(current_id)
                if not e:
                    break
                chain.append(e)
                current_id = e.supersedes

            chain.reverse()  # oldest first

            # Walk forward from input entity
            start = self.get_entity(entity_id)
            forward_id = start.superseded_by if start else None
            while forward_id and forward_id not in visited:
                visited.add(forward_id)
                e = self.get_entity(forward_id)
                if not e:
                    break
                chain.append(e)
                forward_id = e.superseded_by

            return [(e, e.is_active) for e in chain]

    # --------------------------------------------------------------------------
    # Relationship Operations
    # --------------------------------------------------------------------------
    def add_relationship(self, rel: Relationship) -> Relationship:
        """Insert or update a relationship between two entities."""
        with self._lock:
            with self.db.get_connection() as conn:
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
                        UPDATE kg_relationships SET weight = ?, properties = ? WHERE id = ?
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
                        rel.id, rel.user_id, rel.source_id, rel.target_id,
                        rel.relation_type, rel.weight, json.dumps(rel.properties),
                        now_str, json.dumps(rel.metadata),
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

    def get_all_relationships(self, user_id: str = "default_user", limit: int = 500) -> List[Relationship]:
        """Retrieve all relationships for graph visualization."""
        with self._lock:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM kg_relationships WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                    (user_id, limit),
                )
                return [r for row in cursor.fetchall() if (r := self._row_to_relationship(row)) is not None]

    def get_full_graph(self, user_id: str = "default_user", limit: int = 500) -> Subgraph:
        """Retrieve full graph (active entities + all relationships) for visualization."""
        entities = self.list_entities(user_id=user_id, limit=limit, active_only=True)
        relationships = self.get_all_relationships(user_id=user_id, limit=limit)
        return Subgraph(entities=entities, relationships=relationships)

    def delete_relationship(self, relationship_id: str) -> bool:
        """Delete a relationship by ID."""
        with self._lock:
            with self.db.get_connection() as conn:
                cursor = conn.execute("DELETE FROM kg_relationships WHERE id = ?", (relationship_id,))
                conn.commit()
                return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # BFS Subgraph Traversal with RecencyBoostRanker (Gap 4)
    # --------------------------------------------------------------------------
    def query_subgraph(
        self,
        entity_names_or_ids: List[str],
        max_hops: int = 2,
        direction: RelationshipDirection = RelationshipDirection.BOTH,
        user_id: str = "default_user",
        active_only: bool = True,
    ) -> Subgraph:
        """BFS traversal from seed entities up to max_hops.

        - Active-only filtering: superseded entities are skipped (Iron Rule).
        - RecencyBoostRanker: result entities sorted by exp(-lambda*days) desc.
        - Visited set prevents infinite loops in cyclic graphs.
        """
        with self._lock:
            seed_entities: List[Entity] = []
            for item in entity_names_or_ids:
                e = self.get_entity_by_name(item, user_id=user_id, active_only=active_only)
                if not e:
                    e = self.get_entity(item)
                    if e and active_only and not e.is_active:
                        e = None
                if e:
                    seed_entities.append(e)

            if not seed_entities:
                return Subgraph()

            visited_entity_ids: Set[str] = set()
            collected_entities: Dict[str, Entity] = {}
            collected_relationships: Dict[str, Relationship] = {}

            queue = deque((e.id, 0) for e in seed_entities)
            for e in seed_entities:
                visited_entity_ids.add(e.id)
                collected_entities[e.id] = e

            while queue:
                current_id, current_hop = queue.popleft()
                if current_hop >= max_hops:
                    continue

                rels = self.get_relationships(current_id, direction=direction, user_id=user_id)
                for rel in rels:
                    collected_relationships[rel.id] = rel
                    neighbor_id = rel.target_id if rel.source_id == current_id else rel.source_id
                    if neighbor_id not in visited_entity_ids:
                        visited_entity_ids.add(neighbor_id)
                        neighbor_entity = self.get_entity(neighbor_id)
                        if neighbor_entity and (not active_only or neighbor_entity.is_active):
                            collected_entities[neighbor_id] = neighbor_entity
                            queue.append((neighbor_id, current_hop + 1))

            # RecencyBoostRanker: sort by freshness descending
            sorted_entities = sorted(
                collected_entities.values(),
                key=lambda e: _recency_score(e.created_at),
                reverse=True,
            )

            return Subgraph(
                entities=sorted_entities,
                relationships=list(collected_relationships.values()),
            )

    # --------------------------------------------------------------------------
    # Stats
    # --------------------------------------------------------------------------
    def get_stats(self, user_id: str = "default_user") -> Dict[str, Any]:
        """Get graph summary statistics."""
        with self._lock:
            with self.db.get_connection() as conn:
                c_ent = conn.execute(
                    "SELECT COUNT(*) as cnt FROM kg_entities WHERE user_id = ? AND valid_until IS NULL",
                    (user_id,),
                )
                total_entities = c_ent.fetchone()["cnt"]

                c_sup = conn.execute(
                    "SELECT COUNT(*) as cnt FROM kg_entities WHERE user_id = ? AND valid_until IS NOT NULL",
                    (user_id,),
                )
                total_superseded = c_sup.fetchone()["cnt"]

                c_rel = conn.execute(
                    "SELECT COUNT(*) as cnt FROM kg_relationships WHERE user_id = ?", (user_id,)
                )
                total_relationships = c_rel.fetchone()["cnt"]

                type_cur = conn.execute("""
                    SELECT entity_type, COUNT(*) as cnt FROM kg_entities
                    WHERE user_id = ? AND valid_until IS NULL
                    GROUP BY entity_type ORDER BY cnt DESC
                """, (user_id,))
                type_counts = {r["entity_type"]: r["cnt"] for r in type_cur.fetchall()}

                recent_cur = conn.execute("""
                    SELECT name, entity_type, description FROM kg_entities
                    WHERE user_id = ? AND valid_until IS NULL
                    ORDER BY updated_at DESC LIMIT 6
                """, (user_id,))
                top_entities = [dict(r) for r in recent_cur.fetchall()]

                return {
                    "total_entities": total_entities,
                    "total_superseded": total_superseded,
                    "total_relationships": total_relationships,
                    "entity_types": type_counts,
                    "top_entities": top_entities,
                }
