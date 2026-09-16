"""Graph data models for CtxGuard's personal knowledge graph memory system."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RelationshipDirection(str, Enum):
    """Direction of relationship traversal in graph."""
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"


class MemoryScope(str, Enum):
    """Memory scope hierarchy (from broad to narrow).

    - USER:    Persists across all sessions; long-term preferences, identity.
    - SESSION: Lives for the current conversation window.
    - AGENT:   Scoped to a specific agent within a session.
    - TURN:    Single-turn scratch memory; discarded after the turn.
    """
    USER = "user"
    SESSION = "session"
    AGENT = "agent"
    TURN = "turn"


@dataclass
class Entity:
    """An entity node in the knowledge graph.

    Supersession Chain fields (Gap 1):
      valid_from     – ISO timestamp when this entity became the current fact.
      valid_until    – ISO timestamp when this entity was superseded (NULL = still active).
      supersedes     – ID of the entity this one replaces (backward pointer).
      superseded_by  – ID of the entity that replaced this one (forward pointer).

    Scope fields (Gap 6 / lightweight):
      scope          – MemoryScope enum value (default USER).
      session_id     – Optional session identifier for SESSION/AGENT scoped memories.
    """
    name: str
    entity_type: str = "concept"  # person, technology, preference, project, environment, concept
    description: Optional[str] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = "default_user"
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # --- Supersession Chain ---
    valid_from: datetime = field(default_factory=_utc_now)
    valid_until: Optional[datetime] = None
    supersedes: Optional[str] = None       # old entity id this replaces
    superseded_by: Optional[str] = None    # new entity id that replaced this
    # --- Scope ---
    scope: MemoryScope = MemoryScope.USER
    session_id: Optional[str] = None

    @property
    def name_lower(self) -> str:
        return self.name.strip().lower()

    @property
    def is_active(self) -> bool:
        """Return True if this entity is the current active fact (not superseded)."""
        return self.valid_until is None and self.superseded_by is None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "name_lower": self.name_lower,
            "entity_type": self.entity_type,
            "description": self.description or "",
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
            "scope": self.scope.value,
            "session_id": self.session_id,
            "is_active": self.is_active,
        }


@dataclass
class Relationship:
    """A directed edge connecting two entities in the knowledge graph."""
    source_id: str
    target_id: str
    relation_type: str = "related_to"  # prefers, uses, runs_on, depends_on, authored_by, etc.
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    user_id: str = "default_user"
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utc_now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "weight": self.weight,
            "properties": self.properties,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Subgraph:
    """A connected subgraph containing entities and relationships returned by BFS traversal."""
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entities": [e.to_dict() for e in self.entities],
            "relationships": [r.to_dict() for r in self.relationships],
        }

    def format_as_context(self) -> str:
        """Format the subgraph as compact, high-value Markdown bullet points for LLM prompt injection."""
        if not self.entities:
            return ""

        entity_by_id = {e.id: e for e in self.entities}
        lines = []

        # 1. First format relationships as semantic triples
        rendered_rels = set()
        for r in self.relationships:
            src = entity_by_id.get(r.source_id)
            tgt = entity_by_id.get(r.target_id)
            if src and tgt:
                rel_key = (src.name, r.relation_type, tgt.name)
                if rel_key not in rendered_rels:
                    rendered_rels.add(rel_key)
                    lines.append(f"- **{src.name}** *{r.relation_type}* **{tgt.name}**")

        # 2. Add descriptions for key entities not captured by relations alone
        for e in self.entities:
            if e.description and not any(e.name in line for line in lines):
                lines.append(f"- **{e.name}** ({e.entity_type}): {e.description}")

        return "\n".join(lines)
