"""Integration test for stats CLI command."""

import argparse
import os
import tempfile
from ctxguard.cli.cmd_stats import execute_stats
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_stats import StatsRepository


def test_cli_stats_execution(capsys):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_mgr = DatabaseManager(path)
    repo = StatsRepository(db_mgr)

    # Insert mock records
    repo.record_request(
        session_id="session_test",
        protocol="openai",
        model="gpt-4o",
        raw_tokens=5000,
        optimized_tokens=2000,
        latency_ms=1.8,
        applied_compressors=["dedup", "whitespace_cleaner"],
    )

    args = argparse.Namespace(db=path, limit=5)
    execute_stats(args)

    captured = capsys.readouterr().out
    assert "CtxGuard Context Optimization Dashboard" in captured
    assert "Total Proxied Requests:" in captured
    assert "3,000" in captured  # 5000 - 2000 = 3000 saved tokens
    assert "60.0%" in captured

    try:
        os.remove(path)
    except OSError:
        pass
