"""Industrial-grade Session Analyzer implementing CtxGuard Engine's 3-tier analysis strategy:
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
from typing import Any, Dict, List, Optional, Sequence

from ctxguard.learn.models import ConversationSession, IncidentLoop, LearnedRule
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.loop_detector import EVIDENCE_PREVIEW_MAX, LoopDetector, truncate_head_tail
from ctxguard.learn.pivot_analyzer import PivotAnalyzer
from ctxguard.learn.scanner import LogEvent, events_from_sessions
from ctxguard.utils.token_counter import estimate_tokens_from_text


class PromptTooLongError(RuntimeError):
    """Raised when the upstream model rejects the digest for exceeding its context window.

    Used to drive the budget-halving retry loop, exactly like headroom's analyzer: an
    oversized digest must shrink and retry, never silently degrade to the heuristic tier.
    """


# Phrasings different backends use for "your prompt is too long".
_PROMPT_TOO_LONG_MARKERS = (
    "prompt is too long",
    "prompt too long",
    "context length",
    "context_length_exceeded",
    "maximum context",
    "too many tokens",
    "input is too long",
    "request too large",
    "token limit",
    "reduce the length",
)


def is_prompt_too_long(text: Optional[str]) -> bool:
    """Detect an over-length rejection across backend-specific wordings."""
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _PROMPT_TOO_LONG_MARKERS)


class SessionAnalyzer:
    """Analyzes session trajectories using LLM -> CLI -> Heuristic fallback."""

    # Lowest budget the retry loop will shrink to before giving up (headroom uses 10k).
    MIN_DIGEST_TOKENS = 10_000

    SYSTEM_PROMPT = """You are an expert autonomous agent workflow and developer environment analyzer.
Analyze the provided trajectory digest containing agent-environment interactions, tool calls, failure patterns, and causal turning points.
Identify actionable project conventions, file path corrections, environment invariants, and failure loop guards.

The digest opens with a "DETECTED LOOPS" section. Those loops carry MEASURED token waste
computed from bytes actually transferred — treat them as ground truth, and prioritise rules
that eliminate them. The following "PRIOR LEARNED PATTERNS" section is the rule set already
installed in this project.

RULE MAINTENANCE CONTRACT:
- Re-emitting a rule with the SAME section and SAME trigger REPLACES the installed rule.
  When you re-emit, always supply the complete, updated directive — never a fragment.
- If a prior rule is still correct, do NOT re-emit it. Unchanged rules are carried forward
  automatically. Re-stating a rule burns output tokens and changes nothing.
- Only omit a prior rule when it is genuinely wrong, superseded, or obsolete.
- Keep at most one rule per (section, trigger) pair; never emit two rules for the same condition.
- Prefer a small number of high-value rules over an exhaustive list.

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

    # ------------------------------------------------------------------
    # Digest construction
    # ------------------------------------------------------------------
    def _build_loops_section(self, loops: Optional[Sequence[IncidentLoop]]) -> str:
        """Render detected loops, highest measured waste first.

        This section is placed FIRST and is exempt from truncation. Loops are the only
        pattern whose cost grows linearly with repetition, so they are the one thing that
        must never be lost when the digest gets clipped — a digest that drops its loop
        list still costs the full prompt but teaches the model nothing actionable.
        """
        if not loops:
            return ""

        lines = ["## DETECTED LOOPS (measured token waste, highest first)"]
        for loop in loops:
            lines.append(
                f"- [{loop.pattern_type}] `{loop.target_identifier}` x{loop.occurrence_count}, "
                f"measured waste ~{loop.wasted_tokens} tokens"
            )
            if loop.context_hint:
                lines.append(f"  {loop.context_hint}")
            for snippet in list(loop.error_snippets)[:2]:
                lines.append(f"  sample: {snippet[:160]}")
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _build_prior_patterns_section(prior_rules: Optional[Sequence[LearnedRule]]) -> str:
        """Render the currently-installed rules as a baseline the model can amend.

        Without this the model has no idea what is already installed, so duplicates and
        mutually contradictory rules are a guaranteed output — it cannot avoid restating
        what it cannot see. The section is rendered in the same shape that is written back,
        so the model can copy a section/trigger pair verbatim to replace a rule.
        """
        if not prior_rules:
            return ""

        lines = ["## PRIOR LEARNED PATTERNS (baseline already installed — do not restate)"]
        by_section: Dict[str, List[LearnedRule]] = {}
        for rule in prior_rules:
            by_section.setdefault(rule.section, []).append(rule)

        for section, rules in by_section.items():
            lines.append(f"### {section}")
            for rule in rules:
                lines.append(f"- **Rule**: {rule.directive}")
                if rule.trigger:
                    lines.append(f"- **Trigger**: {rule.trigger}")
        return "\n".join(lines) + "\n\n"

    def build_session_digest(
        self,
        sessions: List[ConversationSession],
        max_tokens: int,
        loops: Optional[Sequence[IncidentLoop]] = None,
        prior_rules: Optional[Sequence[LearnedRule]] = None,
    ) -> str:
        """Build a compact digest of multi-turn sessions fitting within max_tokens.

        Layout, in priority order:
          1. Detected loops (exempt from truncation)
          2. Prior learned patterns (exempt from truncation)
          3. Session trajectories (this is what gets clipped)

        Only the trailing event stream competes for budget. The two leading sections are
        small and are the whole reason the digest exists, so they are reserved up front.
        """
        header = f"=== CTXGUARD LEARNING DIGEST ({len(sessions)} session(s)) ===\n\n"
        loops_section = self._build_loops_section(loops)
        prior_section = self._build_prior_patterns_section(prior_rules)

        reserved_tokens = (
            estimate_tokens_from_text(header)
            + estimate_tokens_from_text(loops_section)
            + estimate_tokens_from_text(prior_section)
        )
        parts: List[str] = [header, loops_section, prior_section]
        current_tokens = reserved_tokens

        if loops_section or prior_section:
            parts.append("## SESSION TRAJECTORIES\n")

        for s in sessions:
            session_header = f"=== SESSION {s.session_id} (Agent: {s.agent_type}) ===\n"
            session_parts: List[str] = [session_header]
            session_tokens = estimate_tokens_from_text(session_header)

            for turn in s.turns:
                turn_str = f"[{turn.role.upper()}]: {turn.content[:300]}\n"
                if turn.tool_calls:
                    for tc in turn.tool_calls:
                        status = "FAILED" if tc.is_error else "OK"
                        turn_str += f"  -> Tool {tc.tool_name} [{status}]: {str(tc.arguments)[:150]}\n"
                        if tc.output:
                            # A failure preview keeps both ends, because a traceback's root cause
                            # sits on the last line and a head-only slice would discard exactly the
                            # diagnosis this digest exists to convey. Successful output is
                            # informational, so the head alone is enough.
                            if tc.is_error:
                                preview = truncate_head_tail(tc.output)
                            else:
                                preview = " ".join(str(tc.output).split())[:EVIDENCE_PREVIEW_MAX]
                            turn_str += f"     Output: {preview}\n"

                t_tok = estimate_tokens_from_text(turn_str)
                if current_tokens + session_tokens + t_tok > max_tokens:
                    parts.append("".join(session_parts))
                    parts.append("\n[Digest truncated due to context limit]\n")
                    return "".join(parts)

                session_parts.append(turn_str)
                session_tokens += t_tok

            parts.append("".join(session_parts))
            current_tokens += session_tokens

        return "".join(parts)

    # ------------------------------------------------------------------
    # Analysis orchestration
    # ------------------------------------------------------------------
    def analyze_sessions(
        self,
        sessions: List[ConversationSession],
        loops: Optional[List[IncidentLoop]] = None,
        prior_rules: Optional[List[LearnedRule]] = None,
    ) -> List[LearnedRule]:
        """Execute 3-tier analysis flow: LLM -> Local CLI -> Heuristic Fallback.

        If an upstream rejects the digest for being too long, the budget is halved and the
        digest rebuilt (80k -> 40k -> 20k -> 10k). This is strictly better than letting the
        whole LLM tier fail: a shorter digest still carries the loop list and the baseline,
        which are the highest-value parts.
        """
        if not sessions:
            return []

        budget = self.max_context_tokens
        while True:
            digest = self.build_session_digest(
                sessions, budget, loops=loops, prior_rules=prior_rules
            )
            try:
                rules = self._try_llm_api(digest)
                if not rules:
                    rules = self._try_local_cli(digest)
                break
            except PromptTooLongError:
                if budget <= self.MIN_DIGEST_TOKENS:
                    rules = None
                    break
                budget = max(self.MIN_DIGEST_TOKENS, budget // 2)
                continue

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
        except Exception as exc:
            if is_prompt_too_long(str(exc)):
                raise PromptTooLongError(str(exc)) from exc

        return None

    def _try_local_cli(self, digest: str) -> Optional[List[LearnedRule]]:
        """CtxGuard Engine Keyless Mode: invoke local installed agent CLIs with prompt."""
        if "PYTEST_CURRENT_TEST" in os.environ or os.environ.get("CTXGUARD_SKIP_CLI"):
            return None

        # Check claude CLI
        if shutil.which("claude"):
            prompt = f"{self.SYSTEM_PROMPT}\n\nAnalyze this conversation digest and return strictly JSON array:\n\n{digest}"
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
                elif is_prompt_too_long(result.stderr or "") or is_prompt_too_long(result.stdout or ""):
                    raise PromptTooLongError(result.stderr or result.stdout or "")
            except PromptTooLongError:
                raise
            except Exception:
                pass

        # Check gemini CLI
        if shutil.which("gemini"):
            try:
                result = subprocess.run(
                    ["gemini", "-p", f"{self.SYSTEM_PROMPT}\n\n{digest}"],
                    capture_output=True,
                    text=True,
                    timeout=12,
                )
                if result.returncode == 0 and result.stdout:
                    rules = self._parse_llm_json_response(result.stdout)
                    if rules:
                        return rules
                elif is_prompt_too_long(result.stderr or "") or is_prompt_too_long(result.stdout or ""):
                    raise PromptTooLongError(result.stderr or result.stdout or "")
            except PromptTooLongError:
                raise
            except Exception:
                pass

        return None

    def _heuristic_fallback(
        self,
        sessions: List[ConversationSession],
        loops: Optional[List[IncidentLoop]] = None,
    ) -> List[LearnedRule]:
        """Zero-token heuristic extraction ensuring offline resilience."""
        raw_events: List[LogEvent] = events_from_sessions(sessions)

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

    @staticmethod
    def _significant_words(text: str) -> set:
        """Extract comparable tokens (length > 2) used for loop <-> rule matching."""
        return {w for w in re.split(r"[^a-zA-Z0-9_\u4e00-\u9fa5]+", (text or "").lower()) if len(w) > 2}

    def _enrich_rules_with_loops(
        self,
        rules: List[LearnedRule],
        loops: Optional[List[IncidentLoop]],
    ) -> List[LearnedRule]:
        """Attach measured loop waste to the rules a model merely estimated.

        Mirrors headroom's ``apply_loop_weighting``: a model's sense of which rule saves the
        most is not trustworthy, so the *measured* loop waste is used to override it upward
        (``max``, never a downgrade — a model may know about waste the detector did not see).

        Matching is by significant-word overlap rather than substring containment. Substring
        matching silently misses the common case where the rule says "chat_request" but the
        loop target is recorded as a canonicalized command, and it silently over-matches short
        identifiers such as `ls` or `git`.
        """
        if not loops:
            return rules

        loop_word_sets = [
            (loop, self._significant_words(f"{loop.target_identifier} {loop.pattern_type}"))
            for loop in loops
        ]

        for rule in rules:
            rule_words = self._significant_words(
                f"{rule.section} {rule.trigger} {rule.directive}"
            )
            if not rule_words:
                continue
            for loop, loop_words in loop_word_sets:
                if not loop_words:
                    continue
                overlap = rule_words & loop_words
                # Require a majority of the loop's identifying words to appear in the rule.
                if len(overlap) / len(loop_words) >= 0.5:
                    rule.wasted_tokens = max(rule.wasted_tokens, loop.wasted_tokens)
                    rule.occurrence_count = max(rule.occurrence_count, loop.occurrence_count)

        # Sort with highest measured waste at the top
        rules.sort(key=lambda r: (-r.wasted_tokens, -r.occurrence_count))
        return rules
