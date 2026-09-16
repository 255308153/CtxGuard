"""Integration tests for CtxGuard proxy gateway server with mocked upstreams."""

import json
import pytest
import httpx
from starlette.testclient import TestClient

from ctxguard.config.schema import AppConfig
from ctxguard.proxy.server import create_app


@pytest.fixture
def client():
    config = AppConfig()
    app = create_app(config)
    return TestClient(app)


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "CtxGuard"


def test_list_models(client):
    response = client.get("/v1/models")
    assert response.status_code == 200
    data = response.json()
    assert "data" in data
    assert any(m["id"] == "claude-3-5-sonnet-20241022" for m in data["data"])
    assert any(m["id"] == "gpt-4o" for m in data["data"])


def test_latency_header_injected(client):
    response = client.get("/health")
    assert "X-CtxGuard-Process-Time-Ms" in response.headers
    latency = float(response.headers["X-CtxGuard-Process-Time-Ms"])
    assert latency >= 0.0


def test_openai_proxy_non_streaming(client, monkeypatch):
    """Test OpenAI proxy pipeline and mock upstream response."""
    app_instance = client.app
    upstream_client = app_instance.state.upstream

    mock_resp_body = {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello! How can I help?"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
    }

    async def mock_forward_request(url_path, payload, headers, provider_name=None, **kwargs):
        return httpx.Response(status_code=200, json=mock_resp_body)

    monkeypatch.setattr(upstream_client, "forward_request", mock_forward_request)

    request_payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": "Hello AI!\x1b[31m test\x1b[0m"},
        ],
        "stream": False,
    }

    response = client.post(
        "/v1/chat/completions",
        json=request_payload,
        headers={"Authorization": "Bearer sk-test-key"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "chatcmpl-123"
    assert "X-CtxGuard-Saved-Ratio" in response.headers


def test_anthropic_proxy_non_streaming(client, monkeypatch):
    """Test Anthropic proxy pipeline and mock upstream response."""
    app_instance = client.app
    upstream_client = app_instance.state.upstream

    mock_resp_body = {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-3-5-sonnet-20241022",
        "content": [{"type": "text", "text": "Hello human"}],
        "usage": {"input_tokens": 12, "output_tokens": 4},
    }

    async def mock_forward_request(url_path, payload, headers, provider_name=None, **kwargs):
        return httpx.Response(status_code=200, json=mock_resp_body)

    monkeypatch.setattr(upstream_client, "forward_request", mock_forward_request)

    request_payload = {
        "model": "claude-3-5-sonnet-20241022",
        "messages": [
            {"role": "user", "content": "Hi Claude\n\n\n\n\n"},
        ],
        "stream": False,
    }

    response = client.post(
        "/v1/messages",
        json=request_payload,
        headers={"x-api-key": "sk-ant-test"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "msg_01"
    assert "X-CtxGuard-Saved-Ratio" in response.headers


def test_semantic_cache_hit_and_miss(client, monkeypatch):
    """Test that repetitive queries hit the semantic cache without reaching upstream."""
    app_instance = client.app
    upstream_client = app_instance.state.upstream

    call_count = 0

    mock_resp_body = {
        "id": "chatcmpl-cache-1",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "The capital of France is Paris."},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 15, "completion_tokens": 7, "total_tokens": 22},
    }

    async def mock_forward_request(url_path, payload, headers, provider_name=None, **kwargs):
        nonlocal call_count
        call_count += 1
        return httpx.Response(status_code=200, json=mock_resp_body)

    monkeypatch.setattr(upstream_client, "forward_request", mock_forward_request)

    query1 = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "What is the capital of France?"}],
        "stream": False,
    }

    # 1. First call -> Cache MISS -> Reaches upstream
    resp1 = client.post("/v1/chat/completions", json=query1)
    assert resp1.status_code == 200
    assert call_count == 1
    assert resp1.headers.get("X-CtxGuard-Semantic-Cache") is None

    # 2. Exact match call -> Cache HIT (EXACT) -> Upstream call_count remains 1
    resp2 = client.post("/v1/chat/completions", json=query1)
    assert resp2.status_code == 200
    assert call_count == 1
    assert resp2.headers.get("X-CtxGuard-Semantic-Cache") == "HIT-EXACT"
    assert float(resp2.headers.get("X-CtxGuard-Semantic-Similarity", "0")) >= 0.99
    assert resp2.json()["choices"][0]["message"]["content"] == "The capital of France is Paris."

    # 3. Near-identical query -> Cache HIT (SEMANTIC)
    query2 = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "What is the capital of France ?"}],
        "stream": False,
    }
    resp3 = client.post("/v1/chat/completions", json=query2)
    assert resp3.status_code == 200
    assert call_count == 1
    assert resp3.headers.get("X-CtxGuard-Semantic-Cache") in ("HIT-EXACT", "HIT-SEMANTIC")
    assert resp3.json()["choices"][0]["message"]["content"] == "The capital of France is Paris."


def test_piggyback_extraction_end_to_end(client, monkeypatch):
    """Test that <memory> tags are stripped from upstream response and applied to graph store."""
    app_instance = client.app
    upstream_client = app_instance.state.upstream
    graph_store = app_instance.state.graph_store

    mock_resp_body = {
        "id": "chatcmpl-pb-1",
        "object": "chat.completion",
        "model": "gpt-4o",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": (
                        "Sure! I have noted your preference.\n\n"
                        '<memory>{"op": "add", "entity": "User", "relation": "prefers", '
                        '"target": "NextJS", "entity_type": "technology", "desc": "Prefers NextJS for frontends"}</memory>'
                    ),
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35},
    }

    async def mock_forward_request(url_path, payload, headers, provider_name=None, **kwargs):
        return httpx.Response(status_code=200, json=mock_resp_body)

    monkeypatch.setattr(upstream_client, "forward_request", mock_forward_request)

    query = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "I prefer using NextJS for my web apps."}],
        "stream": False,
    }

    resp = client.post("/v1/chat/completions", json=query)
    assert resp.status_code == 200

    # 1. Returned content must NOT contain the internal <memory> tag (100% clean for user)
    content = resp.json()["choices"][0]["message"]["content"]
    assert "<memory>" not in content
    assert "</memory>" not in content
    assert "Sure! I have noted your preference." in content

    # 2. Graph store must have learned the new entity and relationship automatically!
    if graph_store:
        entity = graph_store.get_entity_by_name("NextJS")
        assert entity is not None
        assert entity.entity_type == "technology"
        assert "Prefers NextJS" in entity.description
