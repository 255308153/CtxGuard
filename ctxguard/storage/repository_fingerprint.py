"""Repository for persisting and retrieving content fingerprints across sessions."""

from collections import OrderedDict
from typing import Optional, Any
from ctxguard.storage.db import DatabaseManager


class FingerprintRepository:
    """Manages high-performance in-memory LRU and persistent SHA-256 fingerprint storage."""

    def __init__(self, db_manager: DatabaseManager, context_tracker: Optional[Any] = None, max_records: int = 1000):
        self.db = db_manager
        self.context_tracker = context_tracker
        self.max_records = max_records
        # High-speed in-memory LRU cache to eliminate SSD read/write overhead
        self._memory_cache: OrderedDict[str, str] = OrderedDict()
        self._memory_sessions: OrderedDict[str, str] = OrderedDict()
        self._write_counter = 0

    def _clean_hash(self, hash_id: str) -> str:
        """Strip sha256_ prefix and whitespace."""
        return hash_id.replace("sha256_", "").strip()

    def save_fingerprint(
        self,
        hash_id: str,
        session_id: str,
        content: str,
        max_records: int = 1000,
        tool_name: Optional[str] = None,
        workspace_key: str = "",
    ) -> None:
        """Save a content fingerprint into in-memory LRU and persist to SQLite with batch eviction."""
        clean_id = self._clean_hash(hash_id)

        # 1. Update in-memory LRU cache (0 disk I/O, nanosecond speed)
        effective_limit = min(self.max_records, max_records)
        self.max_records = effective_limit
        self._memory_cache[clean_id] = content
        self._memory_cache.move_to_end(clean_id)
        self._memory_sessions[clean_id] = session_id
        self._memory_sessions.move_to_end(clean_id)
        while len(self._memory_cache) > effective_limit:
            self._memory_cache.popitem(last=False)
            self._memory_sessions.popitem(last=False)

        # 2. Notify context_tracker if present
        if self.context_tracker is not None:
            try:
                self.context_tracker.track(
                    hash_key=clean_id,
                    session_id=session_id,
                    sample_content=content,
                    tool_name=tool_name,
                    workspace_key=workspace_key,
                )
            except Exception:
                pass

        # 3. Persistent SQLite storage with chunked batch eviction (eliminates per-call full-table scans)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO fingerprints (hash_id, session_id, content, char_length, created_at, last_accessed_at, hit_count)
                VALUES (?, ?, ?, ?, strftime('%Y-%m-%d %H:%M:%f', 'now'), strftime('%Y-%m-%d %H:%M:%f', 'now'), 0)
                ON CONFLICT(hash_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    content = excluded.content,
                    char_length = excluded.char_length,
                    last_accessed_at = strftime('%Y-%m-%d %H:%M:%f', 'now'),
                    hit_count = fingerprints.hit_count + 1
                """,
                (clean_id, session_id, content, len(content)),
            )

            # Lazy batch eviction: execute cleanup every 50 writes (or when max_records < 100 in tests)
            self._write_counter += 1
            if max_records < 100 or self._write_counter % 50 == 0:
                conn.execute(
                    """
                    DELETE FROM fingerprints
                    WHERE hash_id IN (
                        SELECT hash_id FROM fingerprints
                        ORDER BY last_accessed_at ASC, hit_count ASC, rowid ASC
                        LIMIT MAX(0, (SELECT COUNT(*) FROM fingerprints) - ?)
                    )
                    """,
                    (max_records,),
                )
            conn.commit()

    def get_content(self, hash_id: str, session_id: Optional[str] = None) -> Optional[str]:
        """Retrieve original content by full or prefix hash ID with memory-first lookup.

        If session_id is provided, lookups will be strictly verified against that session.
        """
        clean_hash = self._clean_hash(hash_id)

        # 1. Check in-memory LRU cache first (0 disk I/O, instant hit)
        if clean_hash in self._memory_cache:
            if session_id is None or self._memory_sessions.get(clean_hash) == session_id:
                self._memory_cache.move_to_end(clean_hash)
                if clean_hash in self._memory_sessions:
                    self._memory_sessions.move_to_end(clean_hash)
                if self.max_records < 100:
                    try:
                        with self.db.get_connection() as conn:
                            conn.execute(
                                "UPDATE fingerprints SET last_accessed_at = strftime('%Y-%m-%d %H:%M:%f', 'now'), hit_count = hit_count + 1 WHERE hash_id = ?",
                                (clean_hash,),
                            )
                            conn.commit()
                    except Exception:
                        pass
                return self._memory_cache[clean_hash]

        # In-memory prefix / bidirectional lookup for short or full hashes
        for k, v in self._memory_cache.items():
            if k.startswith(clean_hash) or clean_hash.startswith(k):
                if session_id is None or self._memory_sessions.get(k) == session_id:
                    self._memory_cache.move_to_end(k)
                    if k in self._memory_sessions:
                        self._memory_sessions.move_to_end(k)
                    if self.max_records < 100:
                        try:
                            with self.db.get_connection() as conn:
                                conn.execute(
                                    "UPDATE fingerprints SET last_accessed_at = strftime('%Y-%m-%d %H:%M:%f', 'now'), hit_count = hit_count + 1 WHERE hash_id = ?",
                                    (k,),
                                )
                                conn.commit()
                        except Exception:
                            pass
                    return v

        # 2. Fallback to SQLite query and populate in-memory LRU
        with self.db.get_connection() as conn:
            # Exact match or prefix match in either direction
            if session_id is not None:
                cursor = conn.execute(
                    "SELECT content, hash_id, session_id FROM fingerprints WHERE (hash_id = ? OR hash_id LIKE ? OR ? LIKE (hash_id || '%')) AND session_id = ? LIMIT 1",
                    (clean_hash, f"{clean_hash}%", clean_hash, session_id),
                )
            else:
                cursor = conn.execute(
                    "SELECT content, hash_id, session_id FROM fingerprints WHERE (hash_id = ? OR hash_id LIKE ? OR ? LIKE (hash_id || '%')) LIMIT 1",
                    (clean_hash, f"{clean_hash}%", clean_hash),
                )
            row = cursor.fetchone()
            if row:
                content = row["content"]
                matched_id = row["hash_id"]
                row_session = row["session_id"]
                self._memory_cache[matched_id] = content
                self._memory_sessions[matched_id] = row_session
                if len(self._memory_cache) > self.max_records:
                    self._memory_cache.popitem(last=False)
                    self._memory_sessions.popitem(last=False)
                return content

        return None

    def has_fingerprint(self, hash_id: str, session_id: Optional[str] = None) -> bool:
        """Check if a fingerprint exists, optionally scoped to session_id."""
        clean_hash = self._clean_hash(hash_id)
        if session_id is None:
            if clean_hash in self._memory_cache:
                return True
            for k in self._memory_cache:
                if k.startswith(clean_hash) or clean_hash.startswith(k):
                    return True
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM fingerprints WHERE hash_id = ? OR hash_id LIKE ? OR ? LIKE (hash_id || '%') LIMIT 1",
                    (clean_hash, f"{clean_hash}%", clean_hash),
                )
                return cursor.fetchone() is not None
        else:
            if clean_hash in self._memory_cache and self._memory_sessions.get(clean_hash) == session_id:
                return True
            for k in self._memory_cache:
                if (k.startswith(clean_hash) or clean_hash.startswith(k)) and self._memory_sessions.get(k) == session_id:
                    return True
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT 1 FROM fingerprints WHERE (hash_id = ? OR hash_id LIKE ? OR ? LIKE (hash_id || '%')) AND session_id = ? LIMIT 1",
                    (clean_hash, f"{clean_hash}%", clean_hash, session_id),
                )
                return cursor.fetchone() is not None

    def purge_and_vacuum(self, keep_limit: int = 1000) -> int:
        """Purge stale and redundant fingerprints, keeping top keep_limit records, and run VACUUM."""
        deleted_count = 0
        with self.db.get_connection() as conn:
            # 1. Delete redundant 12-char twin duplicates if a 16+ char version already exists
            conn.execute(
                """
                DELETE FROM fingerprints
                WHERE length(hash_id) = 12
                  AND EXISTS (
                      SELECT 1 FROM fingerprints f2
                      WHERE length(f2.hash_id) > 12
                        AND f2.hash_id LIKE (fingerprints.hash_id || '%')
                  )
                """
            )
            # 2. Delete older records exceeding keep_limit
            cur = conn.execute(
                """
                DELETE FROM fingerprints
                WHERE hash_id NOT IN (
                    SELECT hash_id FROM fingerprints
                    ORDER BY last_accessed_at DESC, hit_count DESC
                    LIMIT ?
                )
                """,
                (keep_limit,),
            )
            deleted_count = cur.rowcount
            conn.commit()
            conn.execute("VACUUM")

        self._memory_cache.clear()
        self._memory_sessions.clear()
        return deleted_count
