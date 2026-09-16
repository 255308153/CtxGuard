"""Unit tests for durable append-only savings ledger."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from ctxguard.storage.savings_ledger import (
    UNKNOWN,
    DEFAULT_FALLBACK_INPUT_COST_PER_TOKEN,
    estimate_cost_usd,
    record_savings_event,
    aggregate_savings,
    resolve_savings_path,
    _maybe_compact,
)


@pytest.fixture
def ledger_file(tmp_path):
    path = tmp_path / "test_savings.jsonl"
    return path


def test_estimate_cost_usd():
    """Verify cost calculation across known, unknown, and free models."""
    # 1. Known model
    cost_gpt4o = estimate_cost_usd("gpt-4o", 1_000_000)
    assert cost_gpt4o == pytest.approx(2.50, rel=1e-3)

    cost_claude = estimate_cost_usd("claude-3-5-sonnet-20241022", 500_000)
    assert cost_claude == pytest.approx(1.50, rel=1e-3)

    # 2. Unknown model -> falls back to $3.0/M blended rate (never $0)
    cost_unknown = estimate_cost_usd("unknown", 1_000_000)
    assert cost_unknown == pytest.approx(3.00, rel=1e-3)

    cost_custom = estimate_cost_usd("some-obscure-gateway-model", 100_000)
    assert cost_custom == pytest.approx(0.30, rel=1e-3)

    # 3. Free / local models -> legitimately $0.0
    cost_ollama = estimate_cost_usd("ollama/llama3", 1_000_000)
    assert cost_ollama == 0.0

    cost_local = estimate_cost_usd("local-qwen", 500_000)
    assert cost_local == 0.0

    # 4. Zero or negative savings
    assert estimate_cost_usd("gpt-4o", 0) == 0.0
    assert estimate_cost_usd("gpt-4o", -100) == 0.0


def test_record_savings_event_basic(ledger_file):
    """Verify writing a valid savings event appends a valid JSONL line."""
    ok = record_savings_event(
        tokens_before=1000,
        tokens_after=300,
        model="gpt-4o",
        client="claude-code",
        source="proxy_pipeline",
        path=ledger_file,
    )
    assert ok is True
    assert ledger_file.exists()

    with open(ledger_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["before"] == 1000
    assert event["after"] == 300
    assert event["saved"] == 700
    assert event["model"] == "gpt-4o"
    assert event["client"] == "claude-code"
    assert event["source"] == "proxy_pipeline"
    assert event["cost_usd"] > 0.0
    assert "pid" in event
    assert "ts" in event


def test_record_invalid_savings(ledger_file):
    """Verify non-positive savings are discarded and never crash."""
    # before <= after
    assert record_savings_event(tokens_before=500, tokens_after=500, path=ledger_file) is False
    assert record_savings_event(tokens_before=300, tokens_after=500, path=ledger_file) is False
    # invalid types
    assert record_savings_event(tokens_before="invalid", tokens_after=10, path=ledger_file) is False
    assert not ledger_file.exists()


def test_aggregate_savings_windows(ledger_file):
    """Verify time window aggregation (Today, Last 7d, Last 30d) and 30-day cutoff."""
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Today event (same day)
    record_savings_event(
        tokens_before=10000,
        tokens_after=3000,
        model="claude-3-5-sonnet",
        client="claude-code",
        timestamp=now - timedelta(hours=2),
        path=ledger_file,
    )

    # 2. 3 days ago event (in 7d & 30d, but not today)
    record_savings_event(
        tokens_before=20000,
        tokens_after=10000,
        model="gpt-4o",
        client="cursor",
        timestamp=now - timedelta(days=3),
        path=ledger_file,
    )

    # 3. 15 days ago event (in 30d, but not 7d or today)
    record_savings_event(
        tokens_before=30000,
        tokens_after=10000,
        model="gpt-4o",
        client="claude-code",
        timestamp=now - timedelta(days=15),
        path=ledger_file,
    )

    # 4. 40 days ago event (expired past 30 days)
    record_savings_event(
        tokens_before=50000,
        tokens_after=10000,
        model="gemini-1.5-pro",
        client="windsurf",
        timestamp=now - timedelta(days=40),
        path=ledger_file,
    )

    report = aggregate_savings(ledger_file, now=now, retention_days=30)

    # Today: 1 call, 7,000 saved / 10,000 before
    today = report.windows["today"]
    assert today["calls"] == 1
    assert today["tokens_saved"] == 7000
    assert today["tokens_before"] == 10000
    assert today["savings_percent"] == 70.0

    # Last 7 days: 2 calls (today + 3 days ago) = 7,000 + 10,000 = 17,000 saved
    last_7 = report.windows["last_7_days"]
    assert last_7["calls"] == 2
    assert last_7["tokens_saved"] == 17000
    assert last_7["tokens_before"] == 30000

    # Last 30 days: 3 calls (today + 3d + 15d) = 7,000 + 10,000 + 20,000 = 37,000 saved
    last_30 = report.windows["last_30_days"]
    assert last_30["calls"] == 3
    assert last_30["tokens_saved"] == 37000
    assert last_30["tokens_before"] == 60000

    # 40 days ago event should NOT be in the report
    assert report.lifetime["calls"] == 3
    assert report.lifetime["tokens_saved"] == 37000


def test_aggregate_by_model_and_client(ledger_file):
    """Verify aggregation breakdowns by model and client are sorted properly."""
    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)

    # claude-3-opus ($15/M) -> 1,000 saved = $0.015
    record_savings_event(
        tokens_before=2000,
        tokens_after=1000,
        model="claude-3-opus",
        client="client-a",
        timestamp=now,
        path=ledger_file,
    )

    # gpt-4o ($2.5/M) -> 2,000 saved = $0.005
    record_savings_event(
        tokens_before=4000,
        tokens_after=2000,
        model="gpt-4o",
        client="client-b",
        timestamp=now,
        path=ledger_file,
    )

    report = aggregate_savings(ledger_file, now=now)

    # By model: claude-3-opus should be ranked #1 by cost_usd
    assert len(report.by_model) == 2
    assert report.by_model[0]["model"] == "claude-3-opus"
    assert report.by_model[0]["cost_usd"] > report.by_model[1]["cost_usd"]

    # By client: client-b has 2,000 saved, client-a has 1,000 saved -> client-b #1
    assert len(report.by_client) == 2
    assert report.by_client[0]["client"] == "client-b"
    assert report.by_client[0]["tokens_saved"] == 2000
