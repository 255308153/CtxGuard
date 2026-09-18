"""Abstract base interfaces for Learn plugins, conversation scanners, and context writers.
Enables pluggable integration with Claude Code, Gemini CLI, Codex, CtxGuard Gateway, etc.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from ctxguard.learn.models import ConversationSession, LearnedRule


class BaseConversationScanner(ABC):
    """Scans and extracts conversation sessions from agent logs or databases."""

    @abstractmethod
    def scan_sessions(
        self,
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[ConversationSession]:
        """Discover and parse sessions within the lookback window."""
        pass


class BaseContextWriter(ABC):
    """Writes learned rules idempotently into target project documentation or memory."""

    @abstractmethod
    def write_rules(
        self,
        target_path: Path,
        new_rules: List[LearnedRule],
        marker: str = "CTXGUARD_AUTO_RULES",
    ) -> bool:
        """Write rules performing round-trip parsing, merging, and carry-forward."""
        pass


class LearnPlugin(ABC):
    """Plugin interface representing an AI Agent ecosystem or traffic source."""

    @property
    @abstractmethod
    def id(self) -> str:
        """Unique identifier (e.g. 'claude', 'gemini', 'codex', 'ctxguard')."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Display name of the plugin."""
        pass

    @abstractmethod
    def get_scanner(self) -> BaseConversationScanner:
        """Return the scanner instance for this agent."""
        pass

    @abstractmethod
    def get_default_writer(self) -> BaseContextWriter:
        """Return the default writer instance for this agent."""
        pass

    @abstractmethod
    def get_default_target_files(self, project_path: Path) -> List[Path]:
        """Return default configuration files modified by this agent (e.g., AGENTS.md, CLAUDE.local.md)."""
        pass
