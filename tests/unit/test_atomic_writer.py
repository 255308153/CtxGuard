"""Unit tests for atomic idempotent rule file writing."""

import os
from pathlib import Path
import tempfile
from ctxguard.learn.atomic_writer import AtomicRuleWriter


def test_atomic_writer_new_file():
    temp_dir = tempfile.mkdtemp()
    target_file = Path(temp_dir) / ".cursorrules"

    block = "<!-- CTXGUARD_AUTO_RULES:START -->\n- Rule 1\n<!-- CTXGUARD_AUTO_RULES:END -->"
    success = AtomicRuleWriter.write_rules_to_file(str(target_file), block)
    assert success is True
    assert target_file.exists()
    assert "- Rule 1" in target_file.read_text(encoding="utf-8")


def test_atomic_writer_idempotent_replacement():
    temp_dir = tempfile.mkdtemp()
    target_file = Path(temp_dir) / "CLAUDE.local.md"

    initial_content = (
        "# User Manual Rules\n"
        "- Always use TypeScript\n\n"
        "<!-- CTXGUARD_AUTO_RULES:START -->\n"
        "- Old Rule\n"
        "<!-- CTXGUARD_AUTO_RULES:END -->\n\n"
        "## Footer Notes\n"
        "- Some manual note"
    )
    target_file.write_text(initial_content, encoding="utf-8")

    new_block = "<!-- CTXGUARD_AUTO_RULES:START -->\n- New Rule 2.0\n<!-- CTXGUARD_AUTO_RULES:END -->"
    AtomicRuleWriter.write_rules_to_file(str(target_file), new_block)

    updated = target_file.read_text(encoding="utf-8")
    assert "# User Manual Rules" in updated
    assert "- Always use TypeScript" in updated
    assert "## Footer Notes" in updated
    assert "- Some manual note" in updated
    assert "- New Rule 2.0" in updated
    assert "- Old Rule" not in updated
