"""Unit tests for virtual tool injection and local execution."""

import os
import tempfile
import pytest
from ctxguard.config.schema import ToolInjectionConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.core.virtual_tools.injector import VirtualToolInjector
from ctxguard.core.virtual_tools.executor import VirtualToolExecutor
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository


@pytest.fixture
def fingerprint_repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_mgr = DatabaseManager(path)
    repo = FingerprintRepository(db_mgr)
    yield repo
    try:
        os.remove(path)
    except OSError:
        pass


def test_virtual_tool_injector():
    injector = VirtualToolInjector(ToolInjectionConfig(enabled=True, tool_name="ctx_expand"))
    req = NormalizedRequest(protocol="anthropic", model="claude-3-5-sonnet-20241022", messages=[])
    injector.inject_schema(req)

    assert req.tools is not None
    assert len(req.tools) == 1
    assert req.tools[0]["name"] == "ctx_expand"
    assert "ref_id" in req.tools[0]["input_schema"]["properties"]


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
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[tool_call_msg])

    local_resp = executor.check_and_execute(req)
    assert local_resp is not None
    assert local_resp.protocol == "openai"
    assert local_resp.content == original_code
    assert local_resp.prompt_tokens == 0
    assert local_resp.completion_tokens == 0


def test_virtual_tool_executor_anthropic(fingerprint_repo):
    original_code = "const config = { port: 8080 };"
    fingerprint_repo.save_fingerprint("abcd98765432", "session_2", original_code)

    executor = VirtualToolExecutor(fingerprint_repo=fingerprint_repo)

    # Simulate Anthropic tool_use content block
    tool_use_msg = Message(
        role="assistant",
        content=[
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "ctx_expand",
                "input": {"ref_id": "abcd98765432"},
            }
        ],
    )
    req = NormalizedRequest(protocol="anthropic", model="claude-3-5-sonnet-20241022", messages=[tool_use_msg])

    local_resp = executor.check_and_execute(req)
    assert local_resp is not None
    assert local_resp.protocol == "anthropic"
    assert local_resp.content == original_code
    assert local_resp.prompt_tokens == 0
