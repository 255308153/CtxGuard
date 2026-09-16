"""Unit tests for CacheGuard and CompressionPipeline."""

import asyncio
from ctxguard.config.schema import AppConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.core.guards.cache_guard import CacheGuard
from ctxguard.core.pipeline import CompressionPipeline


def test_cache_guard_partition():
    config = AppConfig()
    config.cache_guard.freeze_prefix_rounds = 1  # 2 messages frozen
    guard = CacheGuard(config.cache_guard)

    messages = [
        Message(role="user", content="Question 1"),
        Message(role="assistant", content="Answer 1"),
        Message(role="user", content="Question 2"),
        Message(role="assistant", content="Answer 2"),
    ]
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=messages)

    frozen, compressible, was_cold = guard.partition_messages(req)
    assert len(frozen) == 2
    assert len(compressible) == 2
    assert frozen[0].content == "Question 1"
    assert compressible[0].content == "Question 2"
    assert was_cold is False


def test_compression_pipeline_end_to_end():
    async def _test():
        config = AppConfig()
        pipeline = CompressionPipeline(config)

        # Add a custom hook
        hook_called = False
        @pipeline.hook("pre_compress")
        def my_hook(ctx):
            nonlocal hook_called
            hook_called = True
            return ctx

        repeated_lines = "ERROR: file not found\n" * 10
        messages = [
            Message(role="system", content="You are a helpful coding assistant."),
            Message(role="user", content="Run tests"),
            Message(role="assistant", content="Running tests..."),
            Message(role="tool", content=repeated_lines),
        ]
        req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=messages)

        ctx = await pipeline.process(req)
        assert hook_called is True
        assert ctx.optimized_tokens < ctx.original_tokens
        # System message preserved
        assert req.messages[0].content == "You are a helpful coding assistant."
        # Tool output compressed
        assert "identical line repeated" in req.messages[3].get_text_content()
        # Tool injection verified
        assert req.tools is not None
        assert any("ctx_expand" in str(t) for t in req.tools)

    asyncio.run(_test())
