"""Unit tests for OpenAI and Anthropic protocol adapters."""

from ctxguard.proxy.adapters.openai import OpenAIAdapter
from ctxguard.proxy.adapters.anthropic import AnthropicAdapter


def test_openai_adapter_roundtrip():
    adapter = OpenAIAdapter()
    raw_body = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are AI."},
            {"role": "user", "content": "Hello!"},
        ],
        "temperature": 0.7,
        "stream": True,
    }

    norm_req = adapter.parse_request(raw_body, session_id="sess_123")
    assert norm_req.model == "gpt-4o"
    assert len(norm_req.messages) == 2
    assert norm_req.messages[0].role == "system"
    assert norm_req.messages[1].content == "Hello!"
    assert norm_req.stream is True

    payload = adapter.build_upstream_payload(norm_req)
    assert payload["model"] == "gpt-4o"
    assert payload["temperature"] == 0.7
    assert len(payload["messages"]) == 2


def test_anthropic_adapter_roundtrip():
    adapter = AnthropicAdapter()
    raw_body = {
        "model": "claude-3-5-sonnet-20241022",
        "system": "System instructions",
        "messages": [
            {"role": "user", "content": "Hello Claude"},
        ],
        "max_tokens": 1024,
        "stream": True,
    }

    norm_req = adapter.parse_request(raw_body, session_id="sess_456")
    assert norm_req.model == "claude-3-5-sonnet-20241022"
    assert norm_req.system == "System instructions"
    assert len(norm_req.messages) == 1
    assert norm_req.messages[0].content == "Hello Claude"

    payload = adapter.build_upstream_payload(norm_req)
    assert payload["system"] == "System instructions"
    assert payload["max_tokens"] == 1024
    assert len(payload["messages"]) == 1
