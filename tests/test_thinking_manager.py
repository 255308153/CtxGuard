"""Unit tests for ThinkingManager."""

import pytest
from ctxguard.config.schema import ThinkingManagerConfig
from ctxguard.core.guards.thinking_manager import ThinkingManager
from ctxguard.core.context import Message, NormalizedRequest


def test_thinking_manager_deepseek_reasoning_strip():
    cfg = ThinkingManagerConfig(enabled=True, strip_deepseek_reasoning=True)
    manager = ThinkingManager(cfg)

    req = NormalizedRequest(
        protocol="openai",
        model="deepseek-r1",
        messages=[
            Message(role="user", content="Hello"),
            Message(
                role="assistant",
                content="<think>\nLet me solve this deeply...\n</think>\nHere is the answer.",
                metadata={"reasoning_content": "Internal thought process..."}
            ),
            Message(role="user", content="Next question"),
        ]
    )

    reclaimed = manager.manage_thinking_tokens(req, provider="deepseek")
    assert reclaimed > 0

    hist_assistant = req.messages[1]
    assert "<think>" not in hist_assistant.content
    assert "Here is the answer." in hist_assistant.content
    assert "reasoning_content" not in hist_assistant.metadata


def test_thinking_manager_gemini_thought_strip():
    cfg = ThinkingManagerConfig(enabled=True, strip_gemini_thought=True)
    manager = ThinkingManager(cfg)

    req = NormalizedRequest(
        protocol="openai",
        model="gemini-2.5-flash-thinking",
        messages=[
            Message(role="user", content="Calculate X"),
            Message(
                role="assistant",
                content="<thought>\nThinking step by step...\n</thought>\nThe result is 42."
            ),
            Message(role="user", content="Now calculate Y"),
        ]
    )

    reclaimed = manager.manage_thinking_tokens(req, provider="gemini")
    assert reclaimed > 0
    assert "<thought>" not in req.messages[1].content
    assert "The result is 42." in req.messages[1].content


def test_thinking_manager_anthropic_threshold():
    cfg = ThinkingManagerConfig(enabled=True, anthropic_max_thinking_tokens=100)
    manager = ThinkingManager(cfg)

    huge_thinking = "thought " * 200  # ~200 tokens > 100 limit

    req = NormalizedRequest(
        protocol="anthropic",
        model="claude-3-7-sonnet-20250219",
        messages=[
            Message(role="user", content="Refactor this"),
            Message(
                role="assistant",
                content=[
                    {"type": "thinking", "thinking": huge_thinking, "signature": "sig123"},
                    {"type": "text", "text": "Refactoring complete."}
                ]
            ),
            Message(role="user", content="Now test it"),
        ]
    )

    reclaimed = manager.manage_thinking_tokens(req, provider="anthropic")
    assert reclaimed > 0

    # Thinking block stripped, only text block remains
    hist_assistant = req.messages[1]
    assert len(hist_assistant.content) == 1
    assert hist_assistant.content[0]["type"] == "text"
    assert hist_assistant.content[0]["text"] == "Refactoring complete."
