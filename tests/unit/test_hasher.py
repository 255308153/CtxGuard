"""Unit tests for hashing and fingerprinting."""

from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.utils.token_counter import estimate_tokens_from_text, estimate_tokens_from_payload


def test_compute_sha256():
    text = "def hello_world():\n    return 'hello'"
    hash1 = compute_sha256(text)
    hash2 = compute_sha256(text)
    assert len(hash1) == 64
    assert hash1 == hash2


def test_short_fingerprint():
    text = "sample payload content"
    short_fp = compute_short_fingerprint(text, length=12)
    assert len(short_fp) == 12
    assert short_fp == compute_sha256(text)[:12]


def test_token_counter():
    text = "Hello world! This is a test string."
    tokens = estimate_tokens_from_text(text)
    assert tokens > 0

    cjk_text = "你好，世界！这是一段中文测试内容。"
    cjk_tokens = estimate_tokens_from_text(cjk_text)
    assert cjk_tokens > len(cjk_text) * 1.0

    payload = {
        "messages": [
            {"role": "user", "content": "Tell me a story"},
            {"role": "assistant", "content": "Once upon a time..."},
        ]
    }
    payload_tokens = estimate_tokens_from_payload(payload)
    assert payload_tokens > 0
