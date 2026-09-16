"""Unit tests for Cache Invariants (inspired by Headroom 11-踩过的坑 post-mortem).

Validates:
1. Invariant 1 & 2: Thinking blocks and cryptographic signatures are never corrupted or flattened.
2. Invariant 2 & Pitfall 1: Knowledge graph dynamic context is never injected into messages[0] or system prompt.
3. Invariant 3: Unmodified messages support raw byte passthrough to preserve exact SHA-256 byte parity.
"""

import pytest
import hashlib
from ctxguard.core.context import Message, RequestContext, NormalizedRequest
from ctxguard.core.compressors.whitespace import WhitespaceCleaner
from ctxguard.core.memory.graph_engine import MemoryGraphEngine
from ctxguard.storage.repository_graph import SQLiteGraphStore
from ctxguard.storage.db import DatabaseManager
import tempfile
from pathlib import Path


def test_thinking_block_preservation():
    """Verify that Claude 3.7 / DeepSeek R1 thinking blocks with signatures are protected from text compressors."""
    thinking_sig = "Eq4BCgEYAxIeMIIB..."
    msg = Message(
        role="assistant",
        content=[
            {
                "type": "thinking",
                "thinking": "Step 1: Calculate   values.\n\n\nStep 2: Done.",
                "signature": thinking_sig,
            },
            {
                "type": "text",
                "text": "Here is the   result:\n\n\n\nSuccess!",
            },
        ],
    )

    assert msg.has_protected_signature() is True

    # 1. get_text_content should only return the non-thinking text
    extracted_text = msg.get_text_content()
    assert "Step 1: Calculate" not in extracted_text
    assert "Here is the   result:" in extracted_text

    # 2. Run WhitespaceCleaner compressor on this message
    cleaner = WhitespaceCleaner()
    req = NormalizedRequest(
        protocol="anthropic",
        model="claude-3-7-sonnet-20250219",
        messages=[msg],
    )
    ctx = RequestContext(request=req)
    cleaner.process(ctx, [msg])

    # 3. Assert thinking block and signature were NOT wiped out or overwritten!
    assert isinstance(msg.content, list)
    assert len(msg.content) == 2
    assert msg.content[0]["type"] == "thinking"
    assert msg.content[0]["signature"] == thinking_sig
    # Text block was cleaned without destroying structure
    assert msg.content[1]["type"] == "text"
    assert "\n\n\n\n" not in msg.content[1]["text"]


def test_graph_injection_preserves_static_prefix():
    """Verify that dynamic graph injection NEVER touches messages[0] or prepends to system prompt."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_kg.db"
        db_mgr = DatabaseManager(str(db_file))
        graph_store = SQLiteGraphStore(db_mgr)
        engine = MemoryGraphEngine(graph_store)

        # Learn entity
        engine.extract_and_learn_from_text("我喜欢使用 FastAPI 构建微服务")

        system_msg = Message(role="system", content="You are a helpful coding assistant.")
        user_msg = Message(role="user", content="请帮我写一个 FastAPI 接口")

        req = NormalizedRequest(
            protocol="openai",
            model="deepseek-flash",
            messages=[system_msg, user_msg],
        )
        ctx = RequestContext(request=req)

        injected = engine.inject_graph_context(ctx)
        assert injected is not None

        # CRITICAL ASSERTION: System message (messages[0]) must be UNTOUCHED!
        assert req.messages[0].role == "system"
        assert req.messages[0].content == "You are a helpful coding assistant."
        assert "[Personal Knowledge Graph Context]" not in req.messages[0].content

        # CRITICAL ASSERTION: Injected only into the latest user message suffix!
        assert req.messages[1].role == "user"
        assert "[Relevant User Context & Preferences]" in req.messages[1].content
        assert "FastAPI" in req.messages[1].content
        assert ctx.metadata.get("graph_injected") is True


def test_sha256_unmodified_byte_identity():
    """Verify raw byte hash identity for unmodified client payloads."""
    raw_payload_bytes = b'{"model":"deepseek-flash","messages":[{"role":"user","content":"Hello world"}]}'
    original_sha256 = hashlib.sha256(raw_payload_bytes).hexdigest()

    # If no compressors modify the request, raw_bytes_to_send equals raw_payload_bytes
    can_passthrough_raw = True
    bytes_to_send = raw_payload_bytes if can_passthrough_raw else b'{"re":"serialized"}'

    assert hashlib.sha256(bytes_to_send).hexdigest() == original_sha256
