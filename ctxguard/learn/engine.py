"""Industrial-grade Self-Evolution Learn Pipeline.
Coordinates multi-source plugins, precise loop token weighting, LLM/CLI session analysis, 
and round-trip carry-forward rule synchronization.
"""

from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ctxguard.learn.models import ConversationSession, IncidentLoop, LearnedRule
from ctxguard.learn.analyzer import SessionAnalyzer
from ctxguard.learn.loop_detector import LoopDetector
from ctxguard.learn.merger import RuleMerger
from ctxguard.learn.plugins import PluginRegistry
from ctxguard.learn.plugins.base import LearnPlugin
from ctxguard.learn.plugins.writer import RoundTripContextWriter
from ctxguard.learn.pruner import RulePruner
from ctxguard.learn.scanner import events_from_sessions
from ctxguard.utils.token_counter import estimate_tokens_from_text


class LearnEngine:
    """End-to-end learning pipeline following CtxGuard Engine's industrial design."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet",
        api_key: Optional[str] = None,
        loop_threshold: int = 3,
        max_rules: int = RulePruner.MAX_RULES_BUDGET,
    ):
        self.analyzer = SessionAnalyzer(model=model, api_key=api_key)
        self.writer = RoundTripContextWriter()
        self.loop_threshold = loop_threshold
        self.max_rules = max_rules

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
        """Detect repetitive failures and re-fetch loops with MEASURED token waste.

        Detection is delegated to :class:`LoopDetector`, which evaluates loops strictly
        within a session, whitelists ordinary developer commands, and canonicalizes
        paging variants so that a hidden "200 OK" re-fetch loop is visible. Waste is
        *measured* from the bytes each event actually transferred (never model-guessed),
        and re-fetch loops exclude their first legitimate call.
        """
        events = events_from_sessions(sessions)
        detector = LoopDetector(threshold=self.loop_threshold)
        incidents = detector.detect_loops_from_events(events)

        loops: List[IncidentLoop] = []
        for inc in incidents:
            loops.append(
                IncidentLoop(
                    pattern_type=inc.pattern_type,
                    target_identifier=inc.target_identifier,
                    occurrence_count=inc.occurrence_count,
                    wasted_tokens=inc.wasted_tokens,
                    error_snippets=list(inc.error_snippets),
                    context_hint=inc.context_hint,
                )
            )

        loops.sort(key=lambda l: (-l.wasted_tokens, -l.occurrence_count))
        return loops

    @staticmethod
    def load_prior_rules(target_files: Sequence[Path], marker: str = "CTXGUARD_AUTO_RULES") -> List[LearnedRule]:
        """Read the existing marker blocks from every write target.

        The analyzer needs the currently-installed rules *before* it prompts a model:
        a model that never sees the baseline cannot help but re-state or contradict it.
        Returns an empty list when no target exists yet or nothing is installed.
        """
        prior: List[LearnedRule] = []
        seen_ids = set()
        for target in target_files or []:
            try:
                target_path = Path(target)
                if not target_path.exists():
                    continue
                content = target_path.read_text(encoding="utf-8")
                block = RuleMerger.extract_marker_block(content, marker=marker)
                if not block:
                    continue
                for rule in RuleMerger.parse_prior_rules(block):
                    # Deduplicate across targets: AGENTS.md and CLAUDE.local.md may both
                    # hold the same rule, and a doubled baseline wastes prompt budget.
                    if rule.rule_id in seen_ids:
                        continue
                    seen_ids.add(rule.rule_id)
                    prior.append(rule)
            except Exception:
                continue
        return prior

    def learn_and_synthesize(
        self,
        agent_type: str = "auto",
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
        prior_rules: Optional[List[LearnedRule]] = None,
    ) -> List[LearnedRule]:
        """Execute full learning: discover -> detect loops -> analyze -> synthesize rules."""
        sessions = self.discover_sessions(
            agent_type=agent_type,
            project_path=project_path,
            lookback_hours=lookback_hours,
            limit=limit,
        )

        loops = self.detect_incident_loops(sessions)
        rules = self.analyzer.analyze_sessions(
            sessions,
            loops=loops,
            prior_rules=prior_rules or [],
        )
        return rules

    def preview_rules(
        self,
        rules: List[LearnedRule],
        target_file: Path,
        marker: str = "CTXGUARD_AUTO_RULES",
    ) -> str:
        """Render exactly the rule set that ``apply_rules`` would persist.

        Dry-run previews that skip the round-trip merge and the capacity cap silently
        lie about the result — they show more rules than will survive.
        """
        merged = self._merge_and_cap(rules, target_file, marker=marker)
        return self.writer.render_body(merged)

    def _merge_and_cap(
        self,
        rules: List[LearnedRule],
        target_file: Path,
        marker: str = "CTXGUARD_AUTO_RULES",
    ) -> List[LearnedRule]:
        """Round-trip merge against the target's existing block, then enforce the cap."""
        target_path = Path(target_file)
        prior_rules: List[LearnedRule] = []
        if target_path.exists():
            try:
                existing = target_path.read_text(encoding="utf-8")
                prior_block = RuleMerger.extract_marker_block(existing, marker=marker)
                if prior_block:
                    prior_rules = RuleMerger.parse_prior_rules(prior_block)
            except Exception:
                prior_rules = []

        merged = RuleMerger.merge_rules(rules, prior_rules)
        return RulePruner.prune(merged, max_rules=self.max_rules)

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
            max_rules=self.max_rules,
        )
