import pytest
from ctxguard.config.schema import GitDiffCompressorConfig
from ctxguard.core.compressors.git_diff import GitDiffCompressor
from ctxguard.core.context import NormalizedRequest, Message, RequestContext


SAMPLE_DIFF = """diff --git a/app/main.py b/app/main.py
index abc1234..def5678 100644
--- a/app/main.py
+++ b/app/main.py
@@ -10,25 +10,25 @@ def calculate_total():
     item_1 = get_item(1)
     item_2 = get_item(2)
     item_3 = get_item(3)
     item_4 = get_item(4)
     item_5 = get_item(5)
     item_6 = get_item(6)
     item_7 = get_item(7)
     item_8 = get_item(8)
     item_9 = get_item(9)
     item_10 = get_item(10)
-    discount = 0.05
+    discount = 0.15
     item_11 = get_item(11)
     item_12 = get_item(12)
     item_13 = get_item(13)
     item_14 = get_item(14)
     item_15 = get_item(15)
     item_16 = get_item(16)
     item_17 = get_item(17)
     item_18 = get_item(18)
     item_19 = get_item(19)
     item_20 = get_item(20)
     return total
"""


def test_git_diff_compressor_basic():
    config = GitDiffCompressorConfig(enabled=True, min_lines=5, max_context_lines=1)
    compressor = GitDiffCompressor(config=config)

    compressed = compressor.compress_text(SAMPLE_DIFF)
    assert "ctx_expand(" in compressed
    assert "discount = 0.15" in compressed
    assert "-    discount = 0.05" in compressed
    assert "item_1 = get_item(1)" in compressed
    assert "item_10 = get_item(10)" in compressed
    # item_5 should have been folded away
    assert "item_5 = get_item(5)" not in compressed
    assert len(compressed) < len(SAMPLE_DIFF)


def test_git_diff_in_markdown():
    config = GitDiffCompressorConfig(enabled=True, min_lines=5, max_context_lines=1)
    compressor = GitDiffCompressor(config=config)

    markdown_diff = f"Here is the diff:\n```diff\n{SAMPLE_DIFF}\n```\nPlease review it."
    compressed = compressor.compress_text(markdown_diff)
    assert "```diff" in compressed
    assert "ctx_expand(" in compressed
    assert "discount = 0.15" in compressed
    assert len(compressed) < len(markdown_diff)


def test_git_diff_process_pipeline_message():
    config = GitDiffCompressorConfig(enabled=True, min_lines=5, max_context_lines=1)
    compressor = GitDiffCompressor(config=config)

    msg = Message(role="user", content=SAMPLE_DIFF)
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[msg], session_id="test-session")
    ctx = RequestContext(request=req)

    compressor.process(ctx, [msg])
    assert "git_diff_compressor" in ctx.applied_compressors
    assert "ctx_expand(" in msg.content


def test_git_diff_disabled():
    config = GitDiffCompressorConfig(enabled=False)
    compressor = GitDiffCompressor(config=config)

    msg = Message(role="user", content=SAMPLE_DIFF)
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[msg])
    ctx = RequestContext(request=req)

    compressor.process(ctx, [msg])
    assert "git_diff_compressor" not in ctx.applied_compressors
    assert msg.content == SAMPLE_DIFF
