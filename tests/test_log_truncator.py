"""Unit tests for LogTruncator head-tail sliding window truncation."""

import pytest
from ctxguard.config.schema import LogCleanerConfig
from ctxguard.core.compressors.log_truncator import LogTruncator
from ctxguard.core.context import Message, NormalizedRequest, RequestContext
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository


def test_log_truncator_short_log_passthrough():
    cfg = LogCleanerConfig(enabled=True, max_log_lines=50, head_lines=10, tail_lines=10)
    truncator = LogTruncator(cfg)

    short_log = "\n".join([f"line {i}" for i in range(20)])
    result = truncator.compress_text(short_log)
    assert result == short_log


def test_log_truncator_long_log_head_tail():
    cfg = LogCleanerConfig(enabled=True, max_log_lines=50, head_lines=5, tail_lines=5)
    db = DatabaseManager(":memory:")
    repo = FingerprintRepository(db)
    truncator = LogTruncator(cfg, fingerprint_repo=repo)

    lines = [f"npm build step {i}: Compiling module_{i}" for i in range(100)]
    full_log = "\n".join(lines)

    result = truncator.compress_text(full_log)
    res_lines = result.splitlines()

    # Head lines preserved (0, 1, 2, 3, 4)
    assert res_lines[0] == "npm build step 0: Compiling module_0"
    assert res_lines[4] == "npm build step 4: Compiling module_4"

    # Middle folded at index 5
    assert "lines omitted" in res_lines[5]
    assert "Use ctx_expand" in res_lines[5]

    # Tail lines preserved (95, 96, 97, 98, 99)
    assert res_lines[-5] == "npm build step 95: Compiling module_95"
    assert res_lines[-1] == "npm build step 99: Compiling module_99"

    # Total lines in result is head(5) + 1 + tail(5) = 11
    assert len(res_lines) == 11


def test_log_truncator_code_block():
    cfg = LogCleanerConfig(enabled=True, max_log_lines=30, head_lines=3, tail_lines=3)
    truncator = LogTruncator(cfg)

    body = "\n".join([f"test log line {i}" for i in range(60)])
    wrapped = f"```bash\n{body}\n```"

    result = truncator.compress_text(wrapped)
    assert result.startswith("```bash\n")
    assert result.endswith("\n```")
    assert "lines omitted" in result
