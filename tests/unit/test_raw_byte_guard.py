import pytest
from ctxguard.core.guards.raw_byte_guard import RawByteOverlayGuard
import orjson

def test_raw_byte_guard_passthrough():
    raw = b'{"model": "gpt-4o", "messages": [{"role": "user", "content": "hello"}], "temperature": 0.7}'
    parsed = orjson.loads(raw)
    
    # If no messages changed and no tools changed, should return raw verbatim
    rebuilt = RawByteOverlayGuard.rebuild_payload_bytes(
        original_raw_bytes=raw,
        original_parsed=parsed,
        optimized_messages=parsed["messages"],
        frozen_prefix_count=1,
    )
    assert rebuilt == raw

def test_raw_byte_guard_deterministic_reserialization():
    raw = b'{"b": 2, "a": 1, "messages": [{"role": "user", "content": "hello"}]}'
    parsed = orjson.loads(raw)
    
    new_msgs = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi"}]
    rebuilt1 = RawByteOverlayGuard.rebuild_payload_bytes(
        original_raw_bytes=raw,
        original_parsed=parsed,
        optimized_messages=new_msgs,
        frozen_prefix_count=1,
    )
    rebuilt2 = RawByteOverlayGuard.rebuild_payload_bytes(
        original_raw_bytes=raw,
        original_parsed=parsed,
        optimized_messages=new_msgs,
        frozen_prefix_count=1,
    )
    assert rebuilt1 == rebuilt2
    assert b'"a":1' in rebuilt1

def test_raw_byte_guard_prefix_sha256():
    msgs = [{"role": "system", "content": "You are assistant"}, {"role": "user", "content": "test"}]
    sha1 = RawByteOverlayGuard.compute_prefix_sha256(msgs, count=1)
    sha2 = RawByteOverlayGuard.compute_prefix_sha256(msgs, count=1)
    assert sha1 == sha2
    assert len(sha1) == 64
