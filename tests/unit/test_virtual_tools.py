"""Unit tests for virtual tool injection and local execution."""

import json
import os
import tempfile
import pytest
from ctxguard.config.schema import ToolInjectionConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.core.virtual_tools.injector import VirtualToolInjector
from ctxguard.core.virtual_tools.executor import VirtualToolExecutor
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.storage.repository_graph import SQLiteGraphStore


@pytest.fixture
def test_db_manager():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_mgr = DatabaseManager(path)
    yield db_mgr
    try:
        os.remove(path)
    except OSError:
        pass


@pytest.fixture
def fingerprint_repo(test_db_manager):
    return FingerprintRepository(test_db_manager)


@pytest.fixture
def graph_store(test_db_manager):
    return SQLiteGraphStore(test_db_manager)


def test_virtual_tool_injector():
    injector = VirtualToolInjector(ToolInjectionConfig(enabled=True, tool_name="ctx_expand"))
    req = NormalizedRequest(protocol="anthropic", model="claude-3-5-sonnet-20241022", messages=[])
    injector.inject_schema(req)

    assert req.tools is not None
    tool_names = [t["name"] for t in req.tools]
    assert "ctx_expand" in tool_names
    assert "memory_save" in tool_names


def test_virtual_tool_executor_openai(fingerprint_repo):
    original_code = "def authenticate():\n    return True\n"
    fingerprint_repo.save_fingerprint("e4d909123456", "session_1", original_code)

    executor = VirtualToolExecutor(fingerprint_repo=fingerprint_repo)

    # Simulate OpenAI assistant calling tool
    tool_call_msg = Message(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "ctx_expand",
                    "arguments": '{"ref_id": "e4d909123456"}',
                },
            }
        ],
    )

    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[tool_call_msg],
    )

    resp = executor.check_and_execute(req)
    assert resp is not None
    assert resp.content == original_code
    assert resp.prompt_tokens == 0


def test_virtual_tool_executor_memory_save(graph_store):
    executor = VirtualToolExecutor(graph_store=graph_store)

    tool_call_msg = Message(
        role="assistant",
        content="",
        tool_calls=[
            {
                "id": "call_mem_1",
                "type": "function",
                "function": {
                    "name": "memory_save",
                    "arguments": json.dumps({
                        "fact": "User prefers using FastAPI for backend services",
                        "entity": "User",
                        "scope": "USER"
                    }),
                },
            }
        ],
    )

    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[tool_call_msg],
    )

    resp = executor.check_and_execute(req)
    assert resp is not None
    data = json.loads(resp.content)
    assert data["status"] == "success"

    # Verify persisted in SQLite graph store
    subgraph = graph_store.get_full_graph()
    assert any("FastAPI" in e.name for e in subgraph.entities)
