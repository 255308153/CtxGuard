"""Unified data models for the Learn evolutionary engine.
Aligns with CtxGuard Engine's industrial-grade session analysis and incremental rule consolidation.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Set


@dataclass
class NormalizedToolCall:
    """Canonical representation of an agent's tool execution across different frameworks."""
    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    output: Optional[str] = None
    is_error: bool = False
    tokens_consumed: int = 0
    raw_payload: Optional[Dict[str, Any]] = None


@dataclass
class NormalizedTurn:
    """Canonical turn in a conversation trajectory."""
    turn_id: str
    role: str  # 'user', 'assistant', 'tool', 'system'
    content: str = ""
    tool_calls: List[NormalizedToolCall] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    tokens: int = 0


@dataclass
class ConversationSession:
    """Complete multi-turn session captured from any agent or gateway."""
    session_id: str
    agent_type: str  # 'claude', 'gemini', 'codex', 'ctxguard'
    project_path: Optional[str] = None
    turns: List[NormalizedTurn] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    start_time: float = 0.0
    end_time: float = 0.0


@dataclass
class IncidentLoop:
    """Represents an identified loop or repetitive failure with token waste measurement."""
    pattern_type: str  # 'repeated_tool_failure', 'repeated_query', 're_fetch_loop', 'user_rejection_loop'
    target_identifier: str  # Tool name, command pattern, or file path
    occurrence_count: int
    wasted_tokens: int = 0
    error_snippets: List[str] = field(default_factory=list)
    context_hint: str = ""


@dataclass
class LearnedRule:
    """A synthesized workflow rule or loop guard."""
    rule_id: str
    section: str  # e.g., 'Tool Failure Loop Guards', 'Environment & Path Invariants', 'Project Architecture'
    trigger: str  # Failure signature or scenario
    directive: str  # What the agent must do or avoid
    rationale: str  # Why this rule exists
    wasted_tokens: int = 0
    occurrence_count: int = 1
    confidence: float = 1.0
    source_agent: str = "auto"
    carried_forward: bool = False  # True if retained from prior run without new occurrences
