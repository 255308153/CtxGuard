"""Causality reflection and action rule extractor."""

from dataclasses import dataclass
from typing import List, Optional
from ctxguard.learn.loop_detector import LoopDetector, LoopIncident
from ctxguard.learn.pivot_analyzer import PivotIncident


@dataclass
class ExtractedRule:
    """A structured learned constraint rule for the Agent across 5 core categories."""
    category: str      # "Environment" | "Path Corrections" | "Search Scope" | "Command Patterns" | "Known Large Files"
    trigger: str       # Trigger condition
    directive: str     # Positive / negative action rule for agent prompt
    rationale: str     # Why this rule was created


class CausalityExtractor:
    """Extracts distilled behavioral constraints from failure-to-success pivots and loop incidents."""

    def extract_rules(
        self,
        incidents: Optional[List[LoopIncident]] = None,
        pivots: Optional[List[PivotIncident]] = None,
    ) -> List[ExtractedRule]:
        """Convert loop incidents and pivot points into actionable Agent guidelines."""
        rules: List[ExtractedRule] = []

        # 1. Process Pivot Incidents (High-value facts from Success Correlation)
        if pivots:
            for p in pivots:
                if p.category == "Path Corrections":
                    rules.append(ExtractedRule(
                        category="Path Corrections",
                        trigger=f"Accessing target `{p.wrong_attempt}`",
                        directive=f"`{p.wrong_attempt}` does not exist. The actual target is located at `{p.correct_solution}`.",
                        rationale=p.rationale,
                    ))
                elif p.category == "Environment":
                    rules.append(ExtractedRule(
                        category="Environment",
                        trigger=f"Running commands with `{p.wrong_attempt}`",
                        directive=f"Always execute using `{p.correct_solution}`. Do not rely on `{p.wrong_attempt}`.",
                        rationale=p.rationale,
                    ))
                elif p.category == "Known Large Files":
                    rules.append(ExtractedRule(
                        category="Known Large Files",
                        trigger=f"Reading `{p.wrong_attempt}`",
                        directive=f"{p.correct_solution}.",
                        rationale=p.rationale,
                    ))
                elif p.category == "Command Patterns":
                    rules.append(ExtractedRule(
                        category="Command Patterns",
                        trigger=f"Executing `{p.wrong_attempt}`",
                        directive=f"{p.correct_solution}.",
                        rationale=p.rationale,
                    ))

        # 2. Process Loop Incidents
        if incidents:
            for inc in incidents:
                if inc.pattern_type == "re_fetch_loop":
                    sig = inc.target_identifier
                    if LoopDetector.is_whitelisted_command(sig):
                        continue
                    rules.append(ExtractedRule(
                        category="Search Scope",
                        trigger=f"Running incremental queries for `{sig}`",
                        directive=f"Do not repeatedly execute incremental paging queries (`{sig}`). Fetch complete context or refine query filters directly.",
                        rationale=f"Observed {inc.occurrence_count} consecutive re-fetch loops with incremental limits.",
                    ))
                elif inc.pattern_type == "user_rejection_loop":
                    tool = inc.target_identifier
                    rules.append(ExtractedRule(
                        category="Command Patterns",
                        trigger=f"Automating `{tool}`",
                        directive=f"User prefers manual control. Display command for manual execution instead of running `{tool}` automatically.",
                        rationale=f"User repeatedly rejected automated execution {inc.occurrence_count} times.",
                    ))
                elif inc.pattern_type == "repeated_query":
                    path = inc.target_identifier
                    rules.append(ExtractedRule(
                        category="Path Corrections",
                        trigger=f"Accessing path `{path}`",
                        directive=f"Do not blindly query non-existent path `{path}`. Check directory structure first using find/ls before opening files.",
                        rationale=f"Observed {inc.occurrence_count} repeated FileNotFound failures on `{path}`.",
                    ))
                elif inc.pattern_type == "repeated_tool_failure":
                    tool = inc.target_identifier
                    rules.append(ExtractedRule(
                        category="Command Patterns",
                        trigger=f"Calling tool `{tool}`",
                        directive=f"When `{tool}` fails repeatedly, stop and inspect argument format or prerequisites rather than repeating identical parameters.",
                        rationale=f"Observed {inc.occurrence_count} consecutive execution errors with `{tool}`.",
                    ))

        return self._deduplicate_rules(rules)

    def _deduplicate_rules(self, rules: List[ExtractedRule]) -> List[ExtractedRule]:
        """Deduplicate rules sharing the same trigger and directive."""
        seen = set()
        unique_rules: List[ExtractedRule] = []
        for r in rules:
            key = (r.category, r.trigger, r.directive)
            if key not in seen:
                seen.add(key)
                unique_rules.append(r)
        return unique_rules
