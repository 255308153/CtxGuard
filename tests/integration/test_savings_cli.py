"""Integration tests for CtxGuard savings CLI command."""

import argparse
import json
from pathlib import Path
import pytest

from ctxguard.cli.cmd_savings import execute_savings
from ctxguard.storage.savings_ledger import record_savings_event


def test_savings_cli_empty(tmp_path, capsys):
    """Test CLI output when no savings events are recorded."""
    empty_ledger = tmp_path / "empty_savings.jsonl"
    args = argparse.Namespace(path=str(empty_ledger), as_json=False, reset=False, days=30)
    execute_savings(args)

    captured = capsys.readouterr().out
    assert "No savings recorded yet" in captured


def test_savings_cli_with_data(tmp_path, capsys):
    """Test CLI rendering of progress bars and model/client breakdowns."""
    ledger = tmp_path / "savings.jsonl"

    record_savings_event(
        tokens_before=28000,
        tokens_after=9000,
        model="claude-3-5-sonnet",
        client="claude-code",
        path=ledger,
    )
    record_savings_event(
        tokens_before=15000,
        tokens_after=5000,
        model="gpt-4o",
        client="codex",
        path=ledger,
    )

    args = argparse.Namespace(path=str(ledger), as_json=False, reset=False, days=30)
    execute_savings(args)

    captured = capsys.readouterr().out
    assert "Today" in captured
    assert "Last 7 days" in captured
    assert "Last 30 days" in captured
    assert "█" in captured
    assert "Cost avoided per model:" in captured
    assert "claude-3-5-sonnet" in captured
    assert "Savings by client:" in captured
    assert "claude-code" in captured


def test_savings_cli_json_mode(tmp_path, capsys):
    """Test JSON emission mode for programmatic reading."""
    ledger = tmp_path / "savings.jsonl"

    record_savings_event(
        tokens_before=10000,
        tokens_after=3000,
        model="gpt-4o",
        client="test-agent",
        path=ledger,
    )

    args = argparse.Namespace(path=str(ledger), as_json=True, reset=False, days=30)
    execute_savings(args)

    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["schema_version"] == 1
    assert "windows" in data
    assert "today" in data["windows"]
    assert data["windows"]["today"]["tokens_saved"] == 7000
    assert len(data["by_model"]) >= 1
    assert data["by_model"][0]["model"] == "gpt-4o"


def test_savings_cli_reset(tmp_path, capsys):
    """Test resetting the savings ledger."""
    ledger = tmp_path / "savings.jsonl"
    record_savings_event(
        tokens_before=5000,
        tokens_after=1000,
        path=ledger,
    )
    assert ledger.exists()

    args = argparse.Namespace(path=str(ledger), as_json=False, reset=True, days=30)
    execute_savings(args)

    assert not ledger.exists()
    captured = capsys.readouterr().out
    assert "Savings ledger reset" in captured
