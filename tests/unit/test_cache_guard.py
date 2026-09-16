"""Unit tests for Cache-Safe Guard core features."""

import pytest
from ctxguard.config.schema import CacheGuardConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.core.guards.cache_guard import CacheGuard, estimate_tokens_from_text


def test_dynamic_token_reverse_mapping():
    """Verify dynamic token reverse mapping respects min_cacheable_tokens and turn boundaries."""
    cfg = CacheGuardConfig(
        enabled=True,
        freeze_prefix_rounds=1,
        min_cacheable_tokens=1024,
    )
    guard = CacheGuard(cfg)

    # 4 rounds of short messages (each ~5 tokens -> far below 1024 tokens)
    messages = [
        Message(role="user", content="msg 1"),
        Message(role="assistant", content="reply 1"),
        Message(role="user", content="msg 2"),
        Message(role="assistant", content="reply 2"),
        Message(role="user", content="msg 3"),
        Message(role="assistant", content="reply 3"),
        Message(role="user", content="msg 4"),
        Message(role="assistant", content="reply 4"),
    ]
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=messages)

    # When tokens are small, it should freeze baseline freeze_prefix_rounds (1 round = 2 messages)
    frozen, compressible, was_cold = guard.partition_messages(req)
    assert len(frozen) == 2
    assert len(compressible) == 6
    assert was_cold is False

    # Now simulate a session where upstream previously cached 1200 tokens
    session_id = "ses_dynamic"
    long_text = "word " * 300  # ~300 tokens each
    messages_long = [
        Message(role="user", content=long_text),       # ~300
        Message(role="assistant", content=long_text),  # ~300 (total ~600)
        Message(role="user", content=long_text),       # ~300 (total ~900)
        Message(role="assistant", content=long_text),  # ~300 (total ~1200 >= 1024!)
        Message(role="user", content="latest query"),
        Message(role="assistant", content="latest answer"),
    ]
    # Record that upstream cached exactly the tokens for the first 4 messages
    cached_tok_sum = sum(estimate_tokens_from_text(m.get_text_content()) for m in messages_long[:4])
    guard.record_forwarded_turn(session_id, messages_long[:4], cached_tokens=cached_tok_sum)

    req_long = NormalizedRequest(protocol="openai", model="gpt-4o", messages=messages_long, session_id=session_id)
    frozen_long, compressible_long, _ = guard.partition_messages(req_long, session_id=session_id)
    # The first 4 messages accumulate to ~1200 tokens, dynamically freezing all 4 messages
    assert len(frozen_long) == 4
    assert len(compressible_long) == 2


def test_economic_savings_arbitration():
    """Verify economic arbitration prevents net-negative compression (savings_fraction > read_discount)."""
    cfg = CacheGuardConfig(
        enabled=True,
        provider_read_discounts={"anthropic": 0.90, "openai": 0.50, "deepseek": 0.50},
        provider_write_penalties={"anthropic": 1.25, "openai": 1.0, "deepseek": 1.0},
    )
    guard = CacheGuard(cfg)

    # Anthropic: 90% read discount
    # Scenario A: 60% compression savings (1000 -> 400).
    # 0.60 < 0.90 => Keeping cache is cheaper! Should NOT break cache.
    assert guard.should_break_cache_for_compression(1000, 400, provider="anthropic") is False

    # Scenario B: 95% compression savings (1000 -> 50).
    # 0.95 > 0.90 => Saving 95% outweighs the 90% discount. Approved!
    assert guard.should_break_cache_for_compression(1000, 50, provider="anthropic") is True

    # OpenAI: 50% read discount
    # Scenario C: 60% compression savings (1000 -> 400).
    # 0.60 > 0.50 => Compression wins!
    assert guard.should_break_cache_for_compression(1000, 400, provider="openai") is True

    # Scenario D: 30% compression savings (1000 -> 700).
    # 0.30 < 0.50 => Cache wins!
    assert guard.should_break_cache_for_compression(1000, 700, provider="openai") is False


def test_overlay_cached_prefix_and_stability():
    """Verify overlay_cached_prefix replaces modified prefix bytes with forwarded turn bytes."""
    guard = CacheGuard(CacheGuardConfig(enabled=True))
    session_id = "test_session_overlay"

    msg1 = Message(role="user", content="Hello CtxGuard")
    msg2 = Message(role="assistant", content="Hello! How can I help?")

    # Record turn 1
    guard.record_forwarded_turn(session_id, [msg1, msg2], cached_tokens=500)

    # In turn 2, client sends messages where msg1 has extra metadata or minor change
    msg1_client = Message(role="user", content="Hello CtxGuard", name="UserA")
    msg2_client = Message(role="assistant", content="Hello! How can I help?")

    is_stable = guard.is_prefix_stable(session_id, [msg1_client, msg2_client])
    assert is_stable is True

    # Overlay should restore the exact prior messages
    overlaid = guard.overlay_cached_prefix(session_id, [msg1_client, msg2_client])
    assert overlaid[0].content == msg1.content
    assert overlaid[0].name is None  # Reverted to recorded prefix bytes to guarantee 100% hash hit


def test_semantic_prefix_normalization():
    """Verify semantic normalization ignores ephemeral keys like cache_control but preserves tool arguments."""
    guard = CacheGuard(CacheGuardConfig(enabled=True))

    msg_with_cache_control = Message(
        role="user",
        content=[{"type": "text", "text": "Run analysis", "cache_control": {"type": "ephemeral"}}],
    )
    msg_clean = Message(role="user", content="Run analysis")

    norm1 = guard.normalize_message_for_comparison(msg_with_cache_control)
    norm2 = guard.normalize_message_for_comparison(msg_clean)
    assert norm1 == norm2  # Semantic match!

    # Verify opaque payload arguments are NOT stripped
    msg_tool_call_1 = Message(
        role="assistant",
        content="calling tool",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "query", "arguments": "{\"index\": 5}"}}],
    )
    msg_tool_call_2 = Message(
        role="assistant",
        content="calling tool",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "query", "arguments": "{\"index\": 10}"}}],
    )
    norm_t1 = guard.normalize_message_for_comparison(msg_tool_call_1)
    norm_t2 = guard.normalize_message_for_comparison(msg_tool_call_2)
    assert norm_t1 != norm_t2  # Arguments preserved; correctly detected as different!


def test_cache_miss_attribution_and_ttl_tie_breaker():
    """Verify cache miss attribution logic and the TTL-wins tie breaker."""
    guard = CacheGuard(CacheGuardConfig(enabled=True, cache_ttl_seconds=300))

    # 1. Cache hit
    reason = guard.classify_cache_miss(expected_cached=1000, actual_cached=800, idle_seconds=60, prefix_stable=True)
    assert reason == "hit"

    # 2. TTL Expiry - even if prefix changed! ("TTL wins tie-breaker")
    reason_ttl = guard.classify_cache_miss(expected_cached=1000, actual_cached=0, idle_seconds=400, prefix_stable=False)
    assert reason_ttl == "ttl_expiry"

    # 3. Prefix change within TTL
    reason_pfx = guard.classify_cache_miss(expected_cached=1000, actual_cached=0, idle_seconds=60, prefix_stable=False)
    assert reason_pfx == "prefix_change"

    # 4. Provider eviction within TTL and prefix stable
    reason_evict = guard.classify_cache_miss(expected_cached=1000, actual_cached=0, idle_seconds=60, prefix_stable=True)
    assert reason_evict == "provider_eviction"


def test_cold_recompact():
    """Verify cold recompact unfreezes all messages when idle_seconds > cache_ttl_seconds."""
    cfg = CacheGuardConfig(
        enabled=True,
        freeze_prefix_rounds=1,
        cache_ttl_seconds=300,
        cold_recompact_enabled=True,
    )
    guard = CacheGuard(cfg)

    messages = [
        Message(role="user", content="Earlier user query"),
        Message(role="assistant", content="Earlier assistant reply"),
        Message(role="user", content="Latest query"),
    ]
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=messages)

    # Case 1: Active session (idle 30s <= 300s) -> Prefix is frozen normally
    frozen, compressible, was_cold = guard.partition_messages(req, session_id="ses_active", idle_seconds=30.0)
    assert len(frozen) == 2
    assert len(compressible) == 1
    assert was_cold is False

    # Case 2: Expired session (idle 600s > 300s) -> Cold recompact triggers, prefix is empty!
    frozen_cold, compressible_cold, was_cold = guard.partition_messages(req, session_id="ses_cold", idle_seconds=600.0)
    assert len(frozen_cold) == 0
    assert len(compressible_cold) == 3
    assert was_cold is True


def test_anti_cache_bust_multi_turn_replay():
    """Verify that in multi-turn sessions, historical turns are never re-compressed,
    even when incoming raw messages are huge, guaranteeing 100% prefix cache stability."""
    guard = CacheGuard(CacheGuardConfig(enabled=True))
    session_id = "ses_anti_bust"

    # Turn 1: Forwarded compressed messages
    fwd_m1 = Message(role="system", content="System Prompt v1")
    fwd_m2 = Message(role="user", content="[Ref:compressed_hash_123]")
    fwd_m3 = Message(role="assistant", content="Assistant reply 1")
    guard.record_forwarded_turn(session_id, [fwd_m1, fwd_m2, fwd_m3], cached_tokens=2500)

    # Turn 2: Client sends huge raw history + assistant reply + new user query
    huge_raw_text = "def massive_code(): pass\n" * 5000  # ~25,000 raw tokens
    req_turn2 = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[
            Message(role="system", content="System Prompt v1"),
            Message(role="user", content=huge_raw_text),      # Raw version of m2
            Message(role="assistant", content="Assistant reply 1"),
            Message(role="user", content="New query for Turn 2"),
        ],
        session_id=session_id,
    )

    frozen, compressible, was_cold = guard.partition_messages(req_turn2, session_id=session_id)

    # The first 3 messages must be frozen
    assert len(frozen) == 3
    # Only the latest user query is compressible
    assert len(compressible) == 1
    assert compressible[0].content == "New query for Turn 2"

    # The frozen messages must exact-replay the previously forwarded bytes, NOT the raw text!
    assert frozen[0].content == "System Prompt v1"
    assert frozen[1].content == "[Ref:compressed_hash_123]"  # Exact byte replay! Zero cache bust!
    assert frozen[2].content == "Assistant reply 1"


def test_session_level_system_prompt_freeze():
    """Verify that mid-session changes to system prompt or AGENTS.md are frozen to guarantee 100% KV cache stability."""
    guard = CacheGuard(CacheGuardConfig(enabled=True, freeze_system_prompt=True, cache_ttl_seconds=300))
    session_id = "ses_freeze_test"

    # Turn 1: Client starts session with initial system prompt
    req1 = NormalizedRequest(
        protocol="anthropic",
        model="claude-3-5-sonnet",
        system="Initial System Prompt v1",
        messages=[
            Message(role="user", content="Hello turn 1"),
            Message(role="assistant", content="Hi turn 1"),
        ],
        session_id=session_id,
    )
    guard.partition_messages(req1, session_id=session_id)
    guard.record_forwarded_turn(session_id, req1.messages, cached_tokens=5000)

    # Turn 2: Background self-evolution modified system prompt mid-session
    req2 = NormalizedRequest(
        protocol="anthropic",
        model="claude-3-5-sonnet",
        system="Mutated System Prompt v2 with dynamic rules",  # Client sent mutated system prompt
        messages=[
            Message(role="user", content="Hello turn 1"),
            Message(role="assistant", content="Hi turn 1"),
            Message(role="user", content="Hello turn 2"),
        ],
        session_id=session_id,
    )
    guard.partition_messages(req2, session_id=session_id)

    # The mutated system prompt is automatically restored to v1 to preserve 100% KV cache hit!
    assert req2.system == "Initial System Prompt v1"

    # Turn 3: After cold idle timeout (>300s), cold recompact unlocks and accepts new system prompt
    req3 = NormalizedRequest(
        protocol="anthropic",
        model="claude-3-5-sonnet",
        system="Refreshed System Prompt v3",
        messages=[
            Message(role="user", content="Hello after long idle"),
        ],
        session_id=session_id,
    )
    _, _, was_cold = guard.partition_messages(req3, session_id=session_id, idle_seconds=350.0)
    assert was_cold is True
    # Now it accepts the refreshed prompt v3
    guard.partition_messages(req3, session_id=session_id)
    assert req3.system == "Refreshed System Prompt v3"


