"""Unit tests for ToolDeltaCompressor shadow state diffing."""

import pytest
from ctxguard.config.schema import ToolDeltaConfig
from ctxguard.core.compressors.tool_delta import ToolDeltaCompressor
from ctxguard.core.context import Message, NormalizedRequest, RequestContext
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository


def test_tool_delta_first_call_passthrough():
    cfg = ToolDeltaConfig(enabled=True, min_items=15)
    db = DatabaseManager(":memory:")
    repo = FingerprintRepository(db)
    compressor = ToolDeltaCompressor(cfg, fingerprint_repo=repo)

    files = [f"src/components/Module_{i}.tsx" for i in range(25)]
    full_output = "\n".join(files)

    # First call in session "sess_1": records state, passes through
    res1 = compressor._diff_and_compress(full_output, session_id="sess_1")
    assert res1 is None  # Pass-through


def test_tool_delta_second_call_small_diff():
    cfg = ToolDeltaConfig(enabled=True, min_items=15, max_delta_ratio=0.35, max_delta_items=10)
    db = DatabaseManager(":memory:")
    repo = FingerprintRepository(db)
    compressor = ToolDeltaCompressor(cfg, fingerprint_repo=repo)

    files1 = [f"src/components/Module_{i}.tsx" for i in range(25)]
    full_output1 = "\n".join(files1)
    compressor._diff_and_compress(full_output1, session_id="sess_2")

    # Second call: add 1 new file, delete Module_0
    files2 = [f"src/components/Module_{i}.tsx" for i in range(1, 25)] + ["src/components/Module_NEW.tsx"]
    full_output2 = "\n".join(files2)

    res2 = compressor._diff_and_compress(full_output2, session_id="sess_2")
    assert res2 is not None
    assert "Tool Delta: 25 total items" in res2
    assert "+ Added (1):" in res2
    assert "+ src/components/Module_NEW.tsx" in res2
    assert "- Removed (1):" in res2
    assert "- src/components/Module_0.tsx" in res2
    assert "Use ctx_expand" in res2


def test_tool_delta_second_call_identical():
    cfg = ToolDeltaConfig(enabled=True, min_items=15)
    db = DatabaseManager(":memory:")
    repo = FingerprintRepository(db)
    compressor = ToolDeltaCompressor(cfg, fingerprint_repo=repo)

    files = [f"src/components/Module_{i}.tsx" for i in range(20)]
    full_output = "\n".join(files)
    compressor._diff_and_compress(full_output, session_id="sess_3")

    # Identical second call
    res2 = compressor._diff_and_compress(full_output, session_id="sess_3")
    assert res2 is not None
    assert "State unchanged (20 items identical" in res2
    assert "Use ctx_expand" in res2


def test_tool_delta_massive_diff_passthrough():
    cfg = ToolDeltaConfig(enabled=True, min_items=15, max_delta_ratio=0.30)
    db = DatabaseManager(":memory:")
    repo = FingerprintRepository(db)
    compressor = ToolDeltaCompressor(cfg, fingerprint_repo=repo)

    files1 = [f"src/legacy/Old_{i}.tsx" for i in range(20)]
    full_output1 = "\n".join(files1)
    compressor._diff_and_compress(full_output1, session_id="sess_4")

    # Massive change (100% different directory)
    files2 = [f"src/brand_new/New_{i}.tsx" for i in range(20)]
    full_output2 = "\n".join(files2)

    res2 = compressor._diff_and_compress(full_output2, session_id="sess_4")
    # Should pass through due to exceeding max_delta_ratio
    assert res2 is None
