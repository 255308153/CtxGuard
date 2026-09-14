"""SQLite database connection and lifecycle manager."""

from pathlib import Path
import sqlite3
from typing import Optional


class DatabaseManager:
    """Thread-safe SQLite database manager enabling WAL mode and fast lookups."""

    def __init__(self, db_path: str = ".ctxguard.db"):
        self.db_path = Path(db_path).resolve()
        # Ensure parent directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection configured with WAL mode and row factory."""
        conn = sqlite3.connect(str(self.db_path), timeout=20.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode and normal synchronous for fast concurrent reads/writes
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self) -> None:
        """Execute initial schema script."""
        schema_path = Path(__file__).parent / "schema.sql"
        if schema_path.exists():
            schema_sql = schema_path.read_text(encoding="utf-8")
        else:
            schema_sql = """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                protocol TEXT NOT NULL,
                model TEXT NOT NULL,
                raw_tokens INTEGER NOT NULL,
                optimized_tokens INTEGER NOT NULL,
                saved_tokens INTEGER NOT NULL,
                saved_ratio REAL NOT NULL,
                latency_ms REAL NOT NULL,
                applied_compressors TEXT DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS fingerprints (
                hash_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                content TEXT NOT NULL,
                char_length INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """

        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            conn.commit()
