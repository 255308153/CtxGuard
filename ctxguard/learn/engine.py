"""Industrial-grade Self-Evolution Learn Pipeline.
Coordinates multi-source plugins, precise loop token weighting, LLM/CLI session analysis, 
and round-trip carry-forward rule synchronization.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

from ctxguard.learn.models import ConversationSession, IncidentLoop, LearnedRule
from ctxguard.learn.analyzer import SessionAnalyzer
from ctxguard.learn.plugins import PluginRegistry
from ctxguard.learn.plugins.base import LearnPlugin
from ctxguard.learn.plugins.writer import RoundTripContextWriter
from ctxguard.utils.token_counter import estimate_tokens_from_text


class LearnEngine:
    """End-to-end learning pipeline following Headroom's industrial design."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet",
        api_key: Optional[str] = None,
        loop_threshold: int = 3,
    ):
        self.analyzer = SessionAnalyzer(model=model, api_key=api_key)
        self.writer = RoundTripContextWriter()
        self.loop_threshold = loop_threshold

    def discover_sessions(
        self,
        agent_type: str = "auto",
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[ConversationSession]:
        """Collect conversation sessions across enabled plugins."""
        sessions: List[ConversationSession] = []

        if agent_type == "auto":
            plugins = PluginRegistry.list_plugins()
        else:
            p = PluginRegistry.get(agent_type)
            plugins = [p] if p else []

        for plugin in plugins:
            try:
                scanner = plugin.get_scanner()
                found = scanner.scan_sessions(
                    project_path=project_path,
                    lookback_hours=lookback_hours,
                    limit=limit,
                )
                sessions.extend(found)
            except Exception:
                continue

        return sessions

    def detect_incident_loops(
        self,
        sessions: List[ConversationSession],
    ) -> List[IncidentLoop]:
        """Detect repetitive tool failures, calculate wasted tokens, and strip signature variations."""
        from collections import defaultdict

        # Group tool failure streaks by tool name and signature
        streaks: Dict[str, List[int]] = defaultdict(list)
        signatures: Dict[str, str] = {}

        for session in sessions:
            for turn in session.turns:
                for tc in turn.tool_calls:
                    if tc.is_error:
                        sig_key = f"{tc.tool_name}:{str(tc.arguments)[:60]}"
                        streaks[sig_key].append(tc.tokens_consumed)
                        signatures[sig_key] = tc.output or f"Failed execution on {tc.tool_name}"

        incidents: List[IncidentLoop] = []
        for sig_key, token_list in streaks.items():
            count = len(token_list)
            if count >= self.loop_threshold:
                tool_name = sig_key.split(":")[0]
                total_wasted = sum(token_list)
                incidents.append(
                    IncidentLoop(
                        loop_id=f"loop_{abs(hash(sig_key)) % 1000000:06x}",
                        loop_type="tool_execution_failure",
                        target_identifier=tool_name,
                        occurrence_count=count,
                        wasted_tokens=total_wasted,
                        signature_sample=signatures.get(sig_key, ""),
                    )
                )

        incidents.sort(key=lambda x: -x.wasted_tokens)
        return incidents

    def learn_and_synthesize(
        self,
        agent_type: str = "auto",
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[LearnedRule]:
        """Execute full learning: discover -> detect loops -> analyze -> synthesize rules."""
        sessions = self.discover_sessions(
            agent_type=agent_type,
            project_path=project_path,
            lookback_hours=lookback_hours,
            limit=limit,
        )

        loops = self.detect_incident_loops(sessions)
        rules = self.analyzer.analyze_sessions(sessions, loops=loops)
        return rules

    def apply_rules(
        self,
        rules: List[LearnedRule],
        target_file: Path,
        marker: str = "CTXGUARD_AUTO_RULES",
    ) -> bool:
        """Apply rules atomically to target file using round-trip carry-forward."""
        return self.writer.write_rules(
            target_path=target_file,
            new_rules=rules,
            marker=marker,
        )
