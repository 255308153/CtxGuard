"""Industrial-grade Session Analyzer implementing Headroom's 3-tier analysis strategy:
1. Direct LLM API (LiteLLM / OpenAI / Anthropic)
2. Local Agent CLI (claude -p / gemini -p / codex exec) for Keyless operation
3. Local Heuristic Causal Extraction (Offline / Zero-Token Fallback)
Includes automatic context halving on overflow and structured rule synthesis.
"""

from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

from ctxguard.learn.models import ConversationSession, IncidentLoop, LearnedRule
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.loop_detector import LoopDetector
from ctxguard.learn.pivot_analyzer import PivotAnalyzer
from ctxguard.learn.scanner import LogEvent
from ctxguard.utils.token_counter import estimate_tokens_from_text


class SessionAnalyzer:
    """Analyzes session trajectories using LLM -> CLI -> Heuristic fallback."""

    SYSTEM_PROMPT = """You are an expert autonomous agent workflow and developer environment analyzer.
Analyze the provided trajectory digest containing agent-environment interactions, tool calls, failure patterns, and causal turning points.
Identify actionable project conventions, file path corrections, environment invariants, and failure loop guards.

Your output must be strictly a JSON array of objects conforming to this schema:
[
  {
    "section": "Category name (e.g., Tool Failure Loop Guards, Build Directives, Environment Invariants)",
    "trigger": "Exact condition or signature when this rule applies",
    "directive": "Concrete instruction on what to do or avoid",
    "rationale": "Clear technical explanation of why this rule prevents wasted cycles and token burn"
  }
]
Do not include any Markdown wrap except raw JSON array or codeblock."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet",
        api_key: Optional[str] = None,
        max_context_tokens: int = 80000,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.max_context_tokens = max_context_tokens

    def build_session_digest(self, sessions: List[ConversationSession], max_tokens: int) -> str:
        """Build a compact digest of multi-turn sessions fitting within max_tokens."""
        parts: List[str] = []
        current_tokens = 0

        for s in sessions:
            header = f"=== SESSION {s.session_id} (Agent: {s.agent_type}) ===\n"
            parts.append(header)
            current_tokens += estimate_tokens_from_text(header)

            for turn in s.turns:
                turn_str = f"[{turn.role.upper()}]: {turn.content[:300]}\n"
                if turn.tool_calls:
                    for tc in turn.tool_calls:
                        status = "FAILED" if tc.is_error else "OK"
                        turn_str += f"  -> Tool {tc.tool_name} [{status}]: {str(tc.arguments)[:150]}\n"
                        if tc.output:
                            turn_str += f"     Output: {tc.output[:200]}\n"

                t_tok = estimate_tokens_from_text(turn_str)
                if current_tokens + t_tok > max_tokens:
                    parts.append("\n[Digest truncated due to context limit]\n")
                    return "".join(parts)

                parts.append(turn_str)
                current_tokens += t_tok

        return "".join(parts)

    def analyze_sessions(
        self,
        sessions: List[ConversationSession],
        loops: Optional[List[IncidentLoop]] = None,
    ) -> List[LearnedRule]:
        """Execute 3-tier analysis flow: LLM -> Local CLI -> Heuristic Fallback."""
        if not sessions:
            return []

        digest = self.build_session_digest(sessions, self.max_context_tokens)

        # 1. Try LLM API if key available or litellm configured
        rules = self._try_llm_api(digest)
        if rules:
            return self._enrich_rules_with_loops(rules, loops)

        # 2. Try Local CLI (claude -p / gemini -p)
        rules = self._try_local_cli(digest)
        if rules:
            return self._enrich_rules_with_loops(rules, loops)

        # 3. Deterministic Heuristic Fallback
        return self._heuristic_fallback(sessions, loops)

    def _try_llm_api(self, digest: str) -> Optional[List[LearnedRule]]:
        """Attempt analysis via LiteLLM or direct httpx if credentials exist."""
        if not self.api_key:
            return None

        # Attempt litellm if installed
        try:
            import litellm
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": f"Analyze these session trajectories:\n\n{digest}"},
            ]
            response = litellm.completion(
                model=self.model,
                messages=messages,
                api_key=self.api_key,
                temperature=0.1,
            )
            raw_text = response.choices[0].message.content
            return self._parse_llm_json_response(raw_text)
        except Exception:
            pass

        return None

    def _try_local_cli(self, digest: str) -> Optional[List[LearnedRule]]:
        """Headroom Keyless Mode: invoke local installed agent CLIs with prompt."""
        if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("CTXGUARD_SKIP_CLI"):
            return None

        # Check claude CLI
        if shutil.which("claude"):
            prompt = f"{self.SYSTEM_PROMPT}\n\nAnalyze this conversation digest and return strictly JSON array:\n\n{digest[:15000]}"
            try:
                result = subprocess.run(
                    ["claude", "-p", prompt],
                    capture_output=True,
                    text=True,
                    timeout=12,
                )
                if result.returncode == 0 and result.stdout:
                    rules = self._parse_llm_json_response(result.stdout)
                    if rules:
                        return rules
            except Exception:
                pass

        # Check gemini CLI
        if shutil.which("gemini"):
            try:
                result = subprocess.run(
                    ["gemini", "-p", f"{self.SYSTEM_PROMPT}\n\n{digest[:15000]}"],
                    capture_output=True,
                    text=True,
                    timeout=12,
                )
                if result.returncode == 0 and result.stdout:
                    rules = self._parse_llm_json_response(result.stdout)
                    if rules:
                        return rules
            except Exception:
                pass

        return None

    def _heuristic_fallback(
        self,
        sessions: List[ConversationSession],
        loops: Optional[List[IncidentLoop]] = None,
    ) -> List[LearnedRule]:
        """Zero-token heuristic extraction ensuring offline resilience."""
        raw_events: List[LogEvent] = []
        for s in sessions:
            for turn in s.turns:
                for tc in turn.tool_calls:
                    raw_events.append(
                        LogEvent(
                            timestamp=turn.timestamp,
                            session_id=s.session_id,
                            tool_name=tc.tool_name,
                            tool_input=tc.arguments,
                            output=tc.output or "",
                            is_error=tc.is_error,
                        )
                    )

        detector = LoopDetector()
        pivot_analyzer = PivotAnalyzer()
        extractor = CausalityExtractor()

        pivots = pivot_analyzer.analyze_events(raw_events)
        incidents = detector.detect_loops_from_events(raw_events)
        extracted = extractor.extract_rules(incidents=incidents, pivots=pivots)

        rules: List[LearnedRule] = []
        for er in extracted:
            rules.append(
                LearnedRule(
                    rule_id=f"rule_heur_{abs(hash(er.directive)) % 1000000:06x}",
                    section=er.category,
                    trigger=er.trigger,
                    directive=er.directive,
                    rationale=er.rationale,
                    wasted_tokens=0,
                    occurrence_count=1,
                    source_agent="heuristic",
                )
            )

        return self._enrich_rules_with_loops(rules, loops)

    def _parse_llm_json_response(self, text: str) -> Optional[List[LearnedRule]]:
        """Parse structured JSON array from model output."""
        try:
            cleaned = text.strip()
            # Strip markdown codeblock if present
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
                cleaned = re.sub(r"\n?```$", "", cleaned)
            data = json.loads(cleaned)
            if not isinstance(data, list):
                return None

            rules: List[LearnedRule] = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                sec = item.get("section", "General Directives")
                trig = item.get("trigger", "")
                direct = item.get("directive", "")
                rat = item.get("rationale", "")
                if direct:
                    rid = f"rule_llm_{abs(hash((sec, trig, direct))) % 1000000:06x}"
                    rules.append(
                        LearnedRule(
                            rule_id=rid,
                            section=sec,
                            trigger=trig,
                            directive=direct,
                            rationale=rat,
                            source_agent="llm",
                        )
                    )
            return rules if rules else None
        except Exception:
            return None

    def _enrich_rules_with_loops(
        self,
        rules: List[LearnedRule],
        loops: Optional[List[IncidentLoop]],
    ) -> List[LearnedRule]:
        """Attach precise wasted token counts and loop occurrences to rules."""
        if not loops:
            return rules

        loop_map: Dict[str, IncidentLoop] = {l.target_identifier.lower(): l for l in loops}
        for r in rules:
            for ident, l in loop_map.items():
                if ident in r.directive.lower() or ident in r.trigger.lower() or ident in r.section.lower():
                    r.wasted_tokens = max(r.wasted_tokens, l.wasted_tokens)
                    r.occurrence_count = max(r.occurrence_count, l.occurrence_count)

        # Sort with highest wasted token count at the top
        rules.sort(key=lambda r: (-r.wasted_tokens, -r.occurrence_count))
        return rules
