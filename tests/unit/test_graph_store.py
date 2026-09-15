"""Unit tests for SQLiteGraphStore and MemoryGraphEngine."""

import pytest
import tempfile
from pathlib import Path

from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_graph import SQLiteGraphStore
from ctxguard.storage.graph_models import Entity, Relationship, RelationshipDirection
from ctxguard.core.memory.graph_engine import MemoryGraphEngine
from ctxguard.core.context import RequestContext, NormalizedRequest, Message


@pytest.fixture
def graph_store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "test_kg.db"
        db_mgr = DatabaseManager(str(db_file))
        yield SQLiteGraphStore(db_mgr)


def test_entity_crud(graph_store):
    # 1. Add entity
    ent = graph_store.add_entity(Entity(name="React", entity_type="technology", description="UI library"))
    assert ent.id is not None
    assert ent.name == "React"

    # 2. Get by name (case-insensitive)
    found = graph_store.get_entity_by_name("react")
    assert found is not None
    assert found.id == ent.id
    assert found.description == "UI library"

    # 3. Update existing entity
    updated = graph_store.add_entity(Entity(name="REACT", entity_type="technology", description="Modern UI library"))
    assert updated.id == ent.id
    assert updated.description == "Modern UI library"

    # 4. Search
    results = graph_store.search_entities("modern")
    assert len(results) == 1
    assert results[0].name == "React"

    # 5. Delete
    assert graph_store.delete_entity(ent.id) is True
    assert graph_store.get_entity_by_name("React") is None


def test_relationship_and_bfs_traversal(graph_store):
    # Create graph:
    # Alice -> Project_A (owns)
    # Project_A -> SQLite (uses_db)
    # Project_A -> FastApi (built_with)
    # SQLite -> WAL (configures)
    alice = graph_store.add_entity(Entity(name="Alice", entity_type="person"))
    proj_a = graph_store.add_entity(Entity(name="Project_A", entity_type="project"))
    sqlite = graph_store.add_entity(Entity(name="SQLite", entity_type="technology"))
    fastapi = graph_store.add_entity(Entity(name="FastAPI", entity_type="technology"))
    wal = graph_store.add_entity(Entity(name="WAL_Mode", entity_type="configuration"))

    r1 = graph_store.add_relationship(Relationship(source_id=alice.id, target_id=proj_a.id, relation_type="owns"))
    r2 = graph_store.add_relationship(Relationship(source_id=proj_a.id, target_id=sqlite.id, relation_type="uses_db"))
    r3 = graph_store.add_relationship(Relationship(source_id=proj_a.id, target_id=fastapi.id, relation_type="built_with"))
    r4 = graph_store.add_relationship(Relationship(source_id=sqlite.id, target_id=wal.id, relation_type="configures"))

    # Test 1-hop from Alice
    subgraph_1hop = graph_store.query_subgraph(["Alice"], max_hops=1)
    entities_1hop = {e.name for e in subgraph_1hop.entities}
    assert entities_1hop == {"Alice", "Project_A"}

    # Test 2-hop from Alice (should reach SQLite and FastAPI through Project_A, but not WAL_Mode which is 3 hops)
    subgraph_2hop = graph_store.query_subgraph(["Alice"], max_hops=2)
    entities_2hop = {e.name for e in subgraph_2hop.entities}
    assert entities_2hop == {"Alice", "Project_A", "SQLite", "FastAPI"}
    assert "WAL_Mode" not in entities_2hop

    # Test formatting
    formatted = subgraph_2hop.format_as_context()
    assert "Alice" in formatted
    assert "owns" in formatted
    assert "Project_A" in formatted

    # Test cascade delete
    graph_store.delete_entity(proj_a.id)
    # Relationships r1, r2, r3 connected to proj_a should be gone
    rels_alice = graph_store.get_relationships(alice.id)
    assert len(rels_alice) == 0


def test_memory_graph_engine_learning_and_injection(graph_store):
    engine = MemoryGraphEngine(graph_store)

    # 1. Bootstrapped default entities should exist
    stats = graph_store.get_stats()
    assert stats["total_entities"] >= 4

    # 2. Extract and learn from user text
    learned = engine.extract_and_learn_from_text("项目后台以后默认使用 pnpm 启动")
    assert len(learned) >= 1
    pnpm_entity = graph_store.get_entity_by_name("pnpm")
    assert pnpm_entity is not None

    # 3. Context injection into RequestContext
    req = NormalizedRequest(
        protocol="openai",
        model="deepseek-flash",
        messages=[Message(role="user", content="帮我初始化 pnpm 项目并配置依赖")],
    )
    ctx = RequestContext(request=req)
    injected_md = engine.inject_graph_context(ctx)
    assert injected_md is not None
    assert "pnpm" in injected_md

    # Ensure system prompt was prepended
    assert req.messages[0].role == "system"
    assert "[Personal Knowledge Graph Context]" in req.messages[0].content
