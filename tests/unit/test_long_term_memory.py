"""Unit tests for long-term memory improvements:
  - Gap 1: Supersession Chain (supersede / get_history / detach_supersession)
  - Gap 2: FTS5 keyword search
  - Gap 4: RecencyBoostRanker
  - Gap 5: MemoryInjectionBudget
"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.graph_models import Entity, MemoryScope, Relationship
from ctxguard.storage.repository_graph import (
    SQLiteGraphStore,
    _recency_score,
    _sanitize_fts_query,
)
from ctxguard.core.memory.graph_engine import MemoryInjectionBudget


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_store(tmp_path):
    """Fresh in-memory SQLiteGraphStore backed by a tmp file."""
    db = DatabaseManager(db_path=str(tmp_path / "test_graph.db"))
    store = SQLiteGraphStore(db_manager=db)
    return store


# ---------------------------------------------------------------------------
# Gap 1: Supersession Chain
# ---------------------------------------------------------------------------

class TestSupersessionChain:
    def test_supersede_basic(self, tmp_store):
        """supersede() should stamp old entity and create a new active one."""
        old = tmp_store.add_entity(Entity(name="User works at Google", entity_type="fact"))
        new = tmp_store.supersede(
            old_entity_id=old.id,
            new_content="User works at Anthropic",
            new_description="Updated employer",
        )

        # New entity is active
        assert new.is_active
        assert new.name == "User works at Anthropic"
        assert new.supersedes == old.id

        # Old entity is now superseded
        old_refreshed = tmp_store.get_entity(old.id)
        assert old_refreshed.valid_until is not None
        assert old_refreshed.superseded_by == new.id
        assert not old_refreshed.is_active

    def test_active_only_query_excludes_superseded(self, tmp_store):
        """list_entities active_only=True must not return superseded entities."""
        old = tmp_store.add_entity(Entity(name="Preferred language", entity_type="preference"))
        tmp_store.supersede(old.id, "Preferred language v2")

        active = tmp_store.list_entities(active_only=True)
        active_ids = {e.id for e in active}
        assert old.id not in active_ids

    def test_supersede_already_superseded_raises(self, tmp_store):
        """Calling supersede on an already-superseded entity should raise ValueError."""
        old = tmp_store.add_entity(Entity(name="Tech stack is Django", entity_type="fact"))
        new = tmp_store.supersede(old.id, "Tech stack is FastAPI")

        with pytest.raises(ValueError, match="already superseded"):
            tmp_store.supersede(old.id, "Tech stack is Flask")

    def test_get_history_returns_chain(self, tmp_store):
        """get_history() should return all versions in chronological order."""
        v1 = tmp_store.add_entity(Entity(name="v1_fact", entity_type="fact"))
        v2 = tmp_store.supersede(v1.id, "v2_fact")
        v3 = tmp_store.supersede(v2.id, "v3_fact")

        history = tmp_store.get_history(v3.id)
        names = [e.name for e, _ in history]
        assert names == ["v1_fact", "v2_fact", "v3_fact"]

        # Only the last one should be current
        current_flags = [is_cur for _, is_cur in history]
        assert current_flags == [False, False, True]

    def test_detach_supersession_restores_old(self, tmp_store):
        """detach_supersession() should make old entity active again."""
        old = tmp_store.add_entity(Entity(name="User is at Google", entity_type="fact"))
        new = tmp_store.supersede(old.id, "User is at Anthropic")

        ok = tmp_store.detach_supersession(old.id, new.id)
        assert ok is True

        # Old entity should be active again
        old_refreshed = tmp_store.get_entity(old.id)
        assert old_refreshed.is_active

        # New entity should be retired
        new_refreshed = tmp_store.get_entity(new.id)
        assert not new_refreshed.is_active

    def test_fts_removes_superseded_entity(self, tmp_store):
        """After supersession, old entity must NOT appear in FTS search results."""
        old = tmp_store.add_entity(
            Entity(name="Google employment", entity_type="fact", description="works at Google")
        )
        tmp_store.supersede(old.id, "Anthropic employment")

        results = tmp_store.search_entities("Google employment")
        result_ids = {e.id for e in results}
        assert old.id not in result_ids, "Superseded entity leaked into FTS results!"


# ---------------------------------------------------------------------------
# Gap 2: FTS5 / _sanitize_fts_query
# ---------------------------------------------------------------------------

class TestFTSQuery:
    def test_sanitize_simple_english(self):
        q = _sanitize_fts_query("prefer Python")
        assert '"prefer"' in q
        assert '"Python"' in q
        assert "OR" in q

    def test_sanitize_handles_fts_special_chars(self):
        """Colons and dashes are FTS5 operators — must be wrapped in quotes."""
        q = _sanitize_fts_query("error: connection-refused")
        # Should not contain bare : or - as FTS operators
        assert ":" not in q.replace('"error"', "")

    def test_sanitize_empty_returns_empty(self):
        assert _sanitize_fts_query("   ") == ""
        assert _sanitize_fts_query("") == ""

    def test_fts_search_finds_entity(self, tmp_store):
        """FTS5 search should find entities by keyword in name/description."""
        tmp_store.add_entity(Entity(
            name="Apollo project",
            entity_type="project",
            description="Apollo uses React and TypeScript",
        ))
        results = tmp_store.search_entities("Apollo")
        assert any(e.name == "Apollo project" for e in results)


# ---------------------------------------------------------------------------
# Gap 4: RecencyBoostRanker
# ---------------------------------------------------------------------------

class TestRecencyScore:
    def test_fresh_entity_scores_near_one(self):
        fresh = datetime.now(timezone.utc)
        score = _recency_score(fresh)
        assert score > 0.99

    def test_old_entity_scores_lower(self):
        old_dt = datetime.now(timezone.utc) - timedelta(days=30)
        score = _recency_score(old_dt)
        assert score < 0.5  # 30 days * lambda=0.05 -> e^-1.5 ~= 0.22

    def test_recency_ordering_in_subgraph(self, tmp_store):
        """query_subgraph should return entities sorted by recency (newest first)."""
        old_e = tmp_store.add_entity(Entity(name="OldFact", entity_type="fact"))
        # Manually backdate old_e
        import sqlite3
        with tmp_store.db.get_connection() as conn:
            conn.execute(
                "UPDATE kg_entities SET created_at = ? WHERE id = ?",
                ((datetime.now(timezone.utc) - timedelta(days=60)).isoformat(), old_e.id)
            )
            conn.commit()

        new_e = tmp_store.add_entity(Entity(name="NewFact", entity_type="fact"))

        subgraph = tmp_store.query_subgraph(["OldFact", "NewFact"])
        assert len(subgraph.entities) >= 2
        # NewFact should appear before OldFact (higher recency score)
        entity_names = [e.name for e in subgraph.entities]
        assert entity_names.index("NewFact") < entity_names.index("OldFact")


# ---------------------------------------------------------------------------
# Gap 5: MemoryInjectionBudget
# ---------------------------------------------------------------------------

class TestMemoryInjectionBudget:
    def test_budget_applies_max_items(self):
        budget = MemoryInjectionBudget(max_tokens=10000, max_items=3)
        lines = [(f"id{i}", f"Memory line {i}") for i in range(10)]
        result = budget.apply(lines)
        output_lines = result.strip().split("\n")
        assert len(output_lines) == 3

    def test_budget_applies_max_tokens(self):
        budget = MemoryInjectionBudget(max_tokens=20, max_items=100)
        # Each line ~12 chars -> ~3 tokens. 20 token budget allows ~6 lines max.
        lines = [(f"i{i}", f"Short line {i}") for i in range(50)]
        result = budget.apply(lines)
        total_chars = len(result)
        # Budget should cut well before 50 lines worth
        assert total_chars < 50 * 20

    def test_budget_prefixes_mem_id(self):
        budget = MemoryInjectionBudget(max_tokens=10000, max_items=5)
        lines = [("abc123", "User prefers Python")]
        result = budget.apply(lines)
        assert "[abc123]" in result
        assert "User prefers Python" in result

    def test_budget_empty_input(self):
        budget = MemoryInjectionBudget()
        assert budget.apply([]) == ""

    def test_budget_does_not_cut_mid_line(self):
        """Budget must stop at line boundary, never cut a line in half."""
        budget = MemoryInjectionBudget(max_tokens=50, max_items=100)
        lines = [("x", "A" * 100), ("y", "B" * 100)]
        result = budget.apply(lines)
        # Result should be a complete line (ends with "A"s), not partial
        for line in result.split("\n"):
            content = line.split("] ", 1)[-1] if "] " in line else line
            assert content == "A" * 100 or content == ""
