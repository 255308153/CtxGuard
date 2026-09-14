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

    async def mock_forward_request(url_path, payload, headers, provider_name=None):
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

    async def mock_forward_request(url_path, payload, headers, provider_name=None):
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
