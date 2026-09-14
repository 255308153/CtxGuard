"""Integration tests for Web Dashboard and Dashboard APIs."""

import pytest
from starlette.testclient import TestClient
from ctxguard.config.schema import AppConfig
from ctxguard.proxy.server import create_app


@pytest.fixture
def client():
    config = AppConfig()
    app = create_app(config)
    return TestClient(app)


def test_dashboard_html_view(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "CtxGuard 控制面板" in response.text

    # Also test /dashboard
    resp2 = client.get("/dashboard")
    assert resp2.status_code == 200
    assert "CtxGuard 控制面板" in resp2.text


def test_dashboard_stats_api(client):
    response = client.get("/api/stats")
    assert response.status_code == 200
    data = response.json()
    assert "summary" in data
    assert "recent" in data


def test_dashboard_test_compress_api(client):
    test_payload = {
        "text": "\x1b[31mError:\x1b[0m Failed on line 10\n\n\n\n\n"
    }
    response = client.post("/api/test/compress", json=test_payload)
    assert response.status_code == 200
    data = response.json()
    assert "raw_tokens" in data
    assert "optimized_tokens" in data
    assert "optimized_text" in data
    assert "\x1b" not in data["optimized_text"]


def test_dashboard_learn_api(client):
    response = client.post("/api/learn/run")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "rendered_rules" in data
