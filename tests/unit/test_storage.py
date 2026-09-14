"""Unit tests for SQLite storage, fingerprint persistence, and stats aggregation."""

import os
import tempfile
import pytest
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.storage.repository_stats import StatsRepository


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_mgr = DatabaseManager(path)
    yield db_mgr
    try:
        os.remove(path)
    except OSError:
        pass


def test_database_initialization(temp_db):
    conn = temp_db.get_connection()
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = {row["name"] for row in cursor.fetchall()}
    assert "sessions" in tables
    assert "requests" in tables
    assert "fingerprints" in tables
    conn.close()


def test_fingerprint_persistence(temp_db):
    repo = FingerprintRepository(temp_db)
    content = "export const API_URL = 'https://api.example.com';"
    hash_id = "sha256_abcd12345678"

    # Save
    repo.save_fingerprint(hash_id, "test_session", content)

    # Exact retrieve
    found = repo.get_content(hash_id)
    assert found == content

    # Prefix retrieve
    prefix_found = repo.get_content("sha256_abcd12")
    assert prefix_found == content

    # Non-existent
    not_found = repo.get_content("non_existent_hash")
    assert not_found is None


def test_stats_recording_and_summary(temp_db):
    repo = StatsRepository(temp_db)

    # Record 2 requests
    repo.record_request(
        session_id="sess_1",
        protocol="anthropic",
        model="claude-3-5-sonnet-20241022",
        raw_tokens=10000,
        optimized_tokens=4000,
        latency_ms=2.5,
        applied_compressors=["dedup", "ansi_cleaner"],
    )

    repo.record_request(
        session_id="sess_1",
        protocol="openai",
        model="gpt-4o",
        raw_tokens=20000,
        optimized_tokens=10000,
        latency_ms=3.1,
        applied_compressors=["json_struct"],
    )

    summary = repo.get_summary()
    assert summary["total_requests"] == 2
    assert summary["total_raw_tokens"] == 30000
    assert summary["total_optimized_tokens"] == 14000
    assert summary["total_saved_tokens"] == 16000
    assert summary["overall_saved_percent"] > 50.0
    assert summary["estimated_dollars_saved"] > 0.0
    assert summary["avg_latency_ms"] == 2.8

    recent = repo.get_recent_requests(limit=5)
    assert len(recent) == 2
    assert recent[0]["model"] == "gpt-4o"
