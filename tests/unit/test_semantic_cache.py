"""Unit tests for the Semantic Cache module (CtxGuard 06-语义缓存 implementation).

Validates:
1. Exact hash lookup O(1) matching.
2. Semantic similarity matching with conservative 0.95 threshold.
3. Different intent rejection (no false-positive hits).
4. Empty Query Guard: Prevents empty tool continuation queries from colliding semantically.
5. TTL expiration and cleanup.
6. LRU capacity eviction.
"""

import time
import pytest
from ctxguard.config.schema import SemanticCacheConfig
from ctxguard.core.semantic_cache import (
    SemanticCache,
    LightweightEmbedder,
    compute_context_hash,
)
from ctxguard.core.context import Message


def test_embedder_similarity_properties():
    """Verify LightweightEmbedder produces high similarity for paraphrases and low for different intents."""
    embedder = LightweightEmbedder()

    # Paraphrased queries (should have high similarity)
    v1 = embedder.embed("How do I return my purchased items?")
    v2 = embedder.embed("How to return my purchased items?")
    sim_high = sum(a * b for a, b in zip(v1, v2))
    assert sim_high >= 0.95, f"Expected high similarity >= 0.95, got {sim_high}"

    # Completely different queries (should have low similarity)
    v3 = embedder.embed("What is the capital of Australia?")
    sim_low = sum(a * b for a, b in zip(v1, v3))
    assert sim_low < 0.40, f"Expected low similarity < 0.40, got {sim_low}"


def test_exact_hash_match():
    """Verify exact context hash match yields 1.0 similarity and 'exact' hit type."""
    cache = SemanticCache(SemanticCacheConfig(enabled=True, similarity_threshold=0.95))
    messages = [
        {"role": "system", "content": "You are a customer support agent."},
        {"role": "user", "content": "How do I cancel my order?"},
    ]
    model = "deepseek-flash"
    resp_body = b'{"choices":[{"message":{"content":"Click orders and select cancel"}}]}'

    # Store
    cache.put(
        query="How do I cancel my order?",
        messages=messages,
        model=model,
        response_body=resp_body,
        raw_tokens=120,
    )

    # Exact retrieve
    hit = cache.get(
        query="How do I cancel my order?",
        messages=messages,
        model=model,
    )
    assert hit is not None
    entry, sim, hit_type = hit
    assert hit_type == "exact"
    assert sim == 1.0
    assert entry.response_body == resp_body


def test_semantic_similarity_match():
    """Verify semantically similar query hits with >= 0.95 similarity without identical hash."""
    cache = SemanticCache(SemanticCacheConfig(enabled=True, similarity_threshold=0.95))
    orig_messages = [{"role": "user", "content": "How do I return my purchased items?"}]
    model = "deepseek-flash"
    resp_body = b'{"choices":[{"message":{"content":"Go to your orders page to initiate a return."}}]}'

    cache.put(
        query="How do I return my purchased items?",
        messages=orig_messages,
        model=model,
        response_body=resp_body,
    )

    # Different query text and different context hash, but identical semantic meaning
    new_messages = [{"role": "user", "content": "How to return my purchased items?"}]
    hit = cache.get(
        query="How to return my purchased items?",
        messages=new_messages,
        model=model,
    )
    assert hit is not None
    entry, sim, hit_type = hit
    assert hit_type == "semantic"
    assert sim >= 0.95
    assert entry.response_body == resp_body


def test_semantic_different_intent_miss():
    """Verify different intent queries do NOT falsely hit (conservative threshold guard)."""
    cache = SemanticCache(SemanticCacheConfig(enabled=True, similarity_threshold=0.95))
    orig_messages = [{"role": "user", "content": "Where is the Eiffel Tower located?"}]
    cache.put(
        query="Where is the Eiffel Tower located?",
        messages=orig_messages,
        model="gpt-4o",
        response_body=b'{"choices":[{"message":{"content":"Paris, France."}}]}',
    )

    # Totally different query
    hit = cache.get(
        query="How to write a binary search in Python?",
        messages=[{"role": "user", "content": "How to write a binary search in Python?"}],
        model="gpt-4o",
    )
    assert hit is None


def test_empty_query_guard():
    """CRITICAL LESSON from 06-语义缓存:
    Empty/blank queries (like tool continuations) MUST NOT match semantically to prevent cross-context collisions!
    """
    cache = SemanticCache(SemanticCacheConfig(enabled=True, similarity_threshold=0.95))

    # Conversation 1: tool continuation with empty user query
    conv1_messages = [
        {"role": "user", "content": "Read file foo"},
        {"role": "tool", "content": "line 1\nline 2"},
    ]
    cache.put(
        query="",  # Empty query
        messages=conv1_messages,
        model="deepseek-flash",
        response_body=b'{"choices":[{"message":{"content":"File foo contents parsed."}}]}',
    )

    # Conversation 2: another tool continuation with empty user query but completely different context
    conv2_messages = [
        {"role": "user", "content": "Check database table users"},
        {"role": "tool", "content": "user_1, user_2"},
    ]
    hit = cache.get(
        query="",  # Empty query
        messages=conv2_messages,
        model="deepseek-flash",
    )

    # MUST BE NONE! Must not falsely match conversation 1's response!
    assert hit is None


def test_ttl_expiration():
    """Verify entries expire and are evicted when TTL is exceeded."""
    cache = SemanticCache(SemanticCacheConfig(enabled=True, ttl_seconds=1))
    messages = [{"role": "user", "content": "What time is the meeting?"}]
    model = "deepseek-flash"

    cache.put(
        query="What time is the meeting?",
        messages=messages,
        model=model,
        response_body=b'{"choices":[{"message":{"content":"At 3 PM."}}]}',
    )

    # Immediate lookup: hits
    assert cache.get("What time is the meeting?", messages, model) is not None

    # Artificially age the entry past TTL
    for entry in cache._cache.values():
        entry.created_at -= 10.0

    # Lookup after expiration: misses and cleans up
    assert cache.get("What time is the meeting?", messages, model) is None
    assert len(cache._cache) == 0


def test_lru_eviction():
    """Verify LRU capacity eviction correctly drops oldest entry when max_entries is reached."""
    cache = SemanticCache(SemanticCacheConfig(enabled=True, max_entries=2))

    m1 = [{"role": "user", "content": "Question 1"}]
    m2 = [{"role": "user", "content": "Question 2"}]
    m3 = [{"role": "user", "content": "Question 3"}]

    cache.put("Question 1", m1, "model", b"resp 1")
    cache.put("Question 2", m2, "model", b"resp 2")

    # Access Question 1 to make Question 2 the LRU entry
    cache.get("Question 1", m1, "model")

    # Put Question 3: should evict Question 2, keeping 1 and 3
    cache.put("Question 3", m3, "model", b"resp 3")

    assert cache.get("Question 2", m2, "model") is None
    assert cache.get("Question 1", m1, "model") is not None
    assert cache.get("Question 3", m3, "model") is not None
    assert len(cache._cache) == 2
