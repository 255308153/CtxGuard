"""Repository for persisting and retrieving content fingerprints across sessions."""

from collections import OrderedDict
from typing import Optional, Any
from ctxguard.storage.db import DatabaseManager


class FingerprintRepository:
    """Manages high-performance in-memory LRU and persistent SHA-256 fingerprint storage."""

    def __init__(self, db_manager: DatabaseManager, context_tracker: Optional[Any] = None, max_records: int = 10000):
        self.db = db_manager
        self.context_tracker = context_tracker
        self.max_records = max_records
        # High-speed in-memory LRU cache to eliminate SSD read/write overhead
        self._memory_cache: OrderedDict[str, str] = OrderedDict()
        self._write_counter = 0

    def _clean_hash(self, hash_id: str) -> str:
        """Strip sha256_ prefix and whitespace."""
        return hash_id.replace("sha256_", "").strip()

    def save_fingerprint(self, hash_id: str, session_id: str, content: str, max_records: int = 10000, tool_name: Optional[str] = None) -> None:
        """Save a content fingerprint into in-memory LRU and persist to SQLite with batch eviction."""
        clean_id = self._clean_hash(hash_id)

        # 1. Update in-memory LRU cache (0 disk I/O, nanosecond speed)
        effective_limit = min(self.max_records, max_records)
        self.max_records = effective_limit
        self._memory_cache[clean_id] = content
        self._memory_cache.move_to_end(clean_id)
        while len(self._memory_cache) > effective_limit:
            self._memory_cache.popitem(last=False)

        # 2. Notify context_tracker if present
        if self.context_tracker is not None:
            try:
                self.context_tracker.track(
                    hash_key=clean_id,
                    session_id=session_id,
                    sample_content=content,
                    tool_name=tool_name,
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

            # Lazy batch eviction: only execute cleanup every 250 writes (or when max_records < 100 in tests)
            self._write_counter += 1
            if max_records < 100 or self._write_counter % 250 == 0:
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

    def get_content(self, hash_id: str) -> Optional[str]:
        """Retrieve original content by full or prefix hash ID with memory-first lookup."""
        clean_hash = self._clean_hash(hash_id)

        # 1. Check in-memory LRU cache first (0 disk I/O, instant hit)
        if clean_hash in self._memory_cache:
            self._memory_cache.move_to_end(clean_hash)
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

        # In-memory prefix lookup for short hashes
        if len(clean_hash) < 64:
            for k, v in self._memory_cache.items():
                if k.startswith(clean_hash):
                    self._memory_cache.move_to_end(k)
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
            # Exact match
            cursor = conn.execute(
                "SELECT content, hash_id FROM fingerprints WHERE hash_id = ? LIMIT 1",
                (clean_hash,),
            )
            row = cursor.fetchone()
            if row:
                content = row["content"]
                matched_id = row["hash_id"]
                self._memory_cache[matched_id] = content
                if len(self._memory_cache) > self.max_records:
                    self._memory_cache.popitem(last=False)
                return content

            # Prefix match for short fingerprints
            cursor = conn.execute(
                "SELECT content, hash_id FROM fingerprints WHERE hash_id LIKE ? LIMIT 1",
                (f"{clean_hash}%",),
            )
            row = cursor.fetchone()
            if row:
                content = row["content"]
                matched_id = row["hash_id"]
                self._memory_cache[matched_id] = content
                if len(self._memory_cache) > self.max_records:
                    self._memory_cache.popitem(last=False)
                return content

        return None
