"""Repository for persisting and retrieving content fingerprints across sessions."""

from typing import Optional
from ctxguard.storage.db import DatabaseManager


class FingerprintRepository:
    """Manages persistent SHA-256 fingerprint storage."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def _clean_hash(self, hash_id: str) -> str:
        """Strip sha256_ prefix and whitespace."""
        return hash_id.replace("sha256_", "").strip()

    def save_fingerprint(self, hash_id: str, session_id: str, content: str) -> None:
        """Save a content fingerprint (idempotent insert)."""
        clean_id = self._clean_hash(hash_id)
        with self.db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO fingerprints (hash_id, session_id, content, char_length)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(hash_id) DO UPDATE SET
                    session_id = excluded.session_id,
                    content = excluded.content,
                    char_length = excluded.char_length
                """,
                (clean_id, session_id, content, len(content)),
            )
            conn.commit()

    def get_content(self, hash_id: str) -> Optional[str]:
        """Retrieve original content by full or prefix hash ID."""
        clean_hash = self._clean_hash(hash_id)
        with self.db.get_connection() as conn:
            # Exact match
            cursor = conn.execute(
                "SELECT content FROM fingerprints WHERE hash_id = ? LIMIT 1",
                (clean_hash,),
            )
            row = cursor.fetchone()
            if row:
                return row["content"]

            # Prefix match for short fingerprints
            cursor = conn.execute(
                "SELECT content FROM fingerprints WHERE hash_id LIKE ? LIMIT 1",
                (f"{clean_hash}%",),
            )
            row = cursor.fetchone()
            if row:
                return row["content"]

        return None
