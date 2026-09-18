"""Gemini and Codex ecosystem plugins for CtxGuard Learn engine."""

from __future__ import annotations
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from ctxguard.learn.models import ConversationSession, NormalizedTurn
from ctxguard.learn.plugins.base import BaseConversationScanner, BaseContextWriter, LearnPlugin
from ctxguard.learn.plugins.writer import RoundTripContextWriter


class GeminiConversationScanner(BaseConversationScanner):
    """Scans Gemini CLI trajectories (~/.gemini/... or project .gemini)."""

    def scan_sessions(
        self,
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[ConversationSession]:
        home = Path.home()
        target_dirs = [home / ".gemini", home / ".config" / "gemini"]
        if project_path:
            target_dirs.append(project_path / ".gemini")

        sessions: List[ConversationSession] = []
        # Support basic JSON/JSONL chat session traces
        for d in target_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*.json*"):
                try:
                    if (time.time() - f.stat().st_mtime) > (lookback_hours * 3600):
                        continue
                    sessions.append(
                        ConversationSession(
                            session_id=f.stem,
                            agent_type="gemini",
                            project_path=str(project_path) if project_path else None,
                            turns=[],
                            start_time=f.stat().st_mtime,
                        )
                    )
                    if len(sessions) >= limit:
                        break
                except Exception:
                    continue
        return sessions


class GeminiPlugin(LearnPlugin):
    """Ecosystem plugin for Gemini CLI."""

    def __init__(self):
        self._scanner = GeminiConversationScanner()
        self._writer = RoundTripContextWriter()

    @property
    def id(self) -> str:
        return "gemini"

    @property
    def name(self) -> str:
        return "Gemini CLI Ecosystem"

    def get_scanner(self) -> BaseConversationScanner:
        return self._scanner

    def get_default_writer(self) -> BaseContextWriter:
        return self._writer

    def get_default_target_files(self, project_path: Path) -> List[Path]:
        return [project_path / "GEMINI.md", project_path / "AGENTS.md"]


class CodexConversationScanner(BaseConversationScanner):
    """Scans OpenAI Codex trajectories."""

    def scan_sessions(
        self,
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[ConversationSession]:
        home = Path.home()
        target_dirs = [home / ".codex", home / ".openai"]
        if project_path:
            target_dirs.append(project_path / ".codex")

        sessions: List[ConversationSession] = []
        for d in target_dirs:
            if not d.exists():
                continue
            for f in d.rglob("*.json*"):
                try:
                    if (time.time() - f.stat().st_mtime) > (lookback_hours * 3600):
                        continue
                    sessions.append(
                        ConversationSession(
                            session_id=f.stem,
                            agent_type="codex",
                            project_path=str(project_path) if project_path else None,
                            turns=[],
                            start_time=f.stat().st_mtime,
                        )
                    )
                    if len(sessions) >= limit:
                        break
                except Exception:
                    continue
        return sessions


class CodexPlugin(LearnPlugin):
    """Ecosystem plugin for Codex."""

    def __init__(self):
        self._scanner = CodexConversationScanner()
        self._writer = RoundTripContextWriter()

    @property
    def id(self) -> str:
        return "codex"

    @property
    def name(self) -> str:
        return "OpenAI Codex Ecosystem"

    def get_scanner(self) -> BaseConversationScanner:
        return self._scanner

    def get_default_writer(self) -> BaseContextWriter:
        return self._writer

    def get_default_target_files(self, project_path: Path) -> List[Path]:
        return [project_path / "CODEX.md", project_path / "AGENTS.md"]
