"""Integration test for learn CLI command."""

import argparse
from pathlib import Path
import tempfile
from ctxguard.cli.cmd_learn import execute_learn


def test_cli_learn_dry_run(capsys):
    args = argparse.Namespace(dry_run=True, target=None, threshold=3)
    execute_learn(args)
    captured = capsys.readouterr().out
    assert "<!-- CTXGUARD_AUTO_RULES:START -->" in captured
    assert "<!-- CTXGUARD_AUTO_RULES:END -->" in captured


def test_cli_learn_write_file():
    temp_dir = tempfile.mkdtemp()
    target_rule = str(Path(temp_dir) / ".cursorrules")

    args = argparse.Namespace(apply=True, dry_run=False, target=target_rule, threshold=3)
    execute_learn(args)

    assert Path(target_rule).exists()
    content = Path(target_rule).read_text(encoding="utf-8")
    assert "<!-- CTXGUARD_AUTO_RULES:START -->" in content
