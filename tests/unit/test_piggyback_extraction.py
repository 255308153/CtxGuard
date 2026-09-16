"""Unit tests for Piggyback (搭便车) Memory Extraction:
  - Extraction protocol instruction injection (tail suffix)
  - <memory> tag parsing and stripping (single / multiple / trailing newlines)
  - Fault tolerance with malformed JSON
  - op: "add" entity and relationship creation
  - op: "supersede" triggers atomic supersession chain
"""

from __future__ import annotations

import json
import pytest

from ctxguard.core.context import Message, NormalizedRequest, RequestContext
from ctxguard.core.memory.graph_engine import (
    EXTRACTION_PROTOCOL_INSTRUCTION,
    MemoryGraphEngine,
    MemoryInjectionBudget,
)
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.graph_models import Entity
from ctxguard.storage.repository_graph import SQLiteGraphStore


@pytest.fixture
def memory_engine(tmp_path):
    db = DatabaseManager(db_path=str(tmp_path / "test_piggyback.db"))
    store = SQLiteGraphStore(db_manager=db)
    engine = MemoryGraphEngine(graph_store=store, piggyback_enabled=True)
    return engine


class TestPiggybackParsingAndStripping:
    def test_strip_single_memory_tag(self, memory_engine):
        raw_text = (
            "Here is the code you requested:\n```python\nprint('hello')\n```\n\n"
            '<memory>{"op": "add", "entity": "User", "relation": "prefers", "target": "Rust"}</memory>'
        )
        clean_text, memories = memory_engine.parse_and_strip_memory(raw_text)

        assert "<memory>" not in clean_text
        assert "</memory>" not in clean_text
        assert clean_text.endswith("```")
        assert len(memories) == 1
        assert memories[0]["op"] == "add"
        assert memories[0]["target"] == "Rust"

    def test_strip_multiple_memory_tags(self, memory_engine):
        raw_text = (
            "I have updated the service.\n"
            '<memory>{"op": "add", "entity": "User", "relation": "runs_on", "target": "Linux"}</memory>\n'
            '<memory>{"op": "supersede", "mem_id": "old123", "target": "FastAPI"}</memory>'
        )
        clean_text, memories = memory_engine.parse_and_strip_memory(raw_text)

        assert "<memory>" not in clean_text
        assert clean_text == "I have updated the service."
        assert len(memories) == 2
        assert memories[0]["target"] == "Linux"
        assert memories[1]["op"] == "supersede"
        assert memories[1]["mem_id"] == "old123"

    def test_malformed_json_resilient(self, memory_engine):
        raw_text = (
            "Hello world\n"
            "<memory>THIS IS NOT JSON</memory>"
        )
        clean_text, memories = memory_engine.parse_and_strip_memory(raw_text)

        assert clean_text == "Hello world"
        assert memories == []

    def test_no_tags_returns_original_text(self, memory_engine):
        raw_text = "Just a normal response with no memories."
        clean_text, memories = memory_engine.parse_and_strip_memory(raw_text)

        assert clean_text == raw_text
        assert memories == []


class TestPiggybackInstructionInjection:
    def test_injection_appends_protocol_to_last_user_message(self, memory_engine):
        messages = [
            Message(role="system", content="You are a helpful assistant."),
            Message(role="user", content="Hello, I like using Go."),
        ]
        norm_req = NormalizedRequest(protocol="openai", messages=messages, model="gpt-4o")
        ctx = RequestContext(request=norm_req)

        # In pure Headroom mode, relevant context is cleanly injected without prompt pollution
        res = memory_engine.inject_graph_context(ctx)

        # Critical Cache Invariant: system prompt must NOT be touched
        assert "[Relevant User Context & Preferences]" not in ctx.request.messages[0].content

    def test_injection_disabled_does_not_append_protocol(self, tmp_path):
        db = DatabaseManager(db_path=str(tmp_path / "test_no_pb.db"))
        store = SQLiteGraphStore(db_manager=db)
        engine = MemoryGraphEngine(graph_store=store, piggyback_enabled=False)

        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="What is the weather?"),
        ]
        norm_req = NormalizedRequest(protocol="openai", messages=messages, model="gpt-4o")
        ctx = RequestContext(request=norm_req)

        engine.inject_graph_context(ctx)
        last_msg = ctx.request.messages[-1].content
        assert "[Memory Extraction Protocol]" not in last_msg


class TestPiggybackApplication:
    def test_apply_add_memory(self, memory_engine):
        memories = [
            {
                "op": "add",
                "entity": "User",
                "relation": "prefers",
                "target": "TypeScript",
                "entity_type": "technology",
                "desc": "User prefers strict TypeScript over JavaScript",
            }
        ]
        applied = memory_engine.apply_extracted_memories(memories, user_id="default_user")
        assert len(applied) == 1

        entity = memory_engine.store.get_entity_by_name("TypeScript")
        assert entity is not None
        assert entity.entity_type == "technology"
        assert entity.description == "User prefers strict TypeScript over JavaScript"

    def test_apply_supersede_memory(self, memory_engine):
        # 1. Create initial entity
        initial = memory_engine.store.add_entity(
            Entity(name="OldFramework", entity_type="technology", description="Initially using Django")
        )
        assert initial.is_active

        # 2. Apply supersede via piggyback
        memories = [
            {
                "op": "supersede",
                "mem_id": initial.id,
                "target": "NewFramework",
                "desc": "Migrated to FastAPI",
            }
        ]
        applied = memory_engine.apply_extracted_memories(memories, user_id="default_user")
        assert len(applied) == 1

        # 3. Check old entity is superseded and new entity is active
        old_refreshed = memory_engine.store.get_entity(initial.id)
        assert not old_refreshed.is_active
        assert old_refreshed.superseded_by == applied[0].id

        new_entity = applied[0]
        assert new_entity.name == "NewFramework"
        assert new_entity.supersedes == initial.id
        assert new_entity.is_active

        # 4. History trace
        history = memory_engine.store.get_history(new_entity.id)
        assert len(history) == 2
        assert history[0][0].name == "OldFramework"
        assert history[1][0].name == "NewFramework"
