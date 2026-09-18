"""Unified Rule Merger implementing CtxGuard Engine's Round-trip Marker Baseline Merging.
Ensures previously learned rules are carried forward instead of silently erased.
"""

from __future__ import annotations
from datetime import datetime
import re
from typing import Dict, List, Optional, Set, Tuple
from ctxguard.learn.models import LearnedRule


class RuleMerger:
    """Merges newly discovered rules with baseline rules extracted from existing file markers."""

    MARKER_PATTERN = r"<!--\s*{marker}:START\s*-->(.*?)<!--\s*{marker}:END\s*-->"

    @classmethod
    def render_markdown_block(cls, rules: List[LearnedRule], marker: str = "CTXGUARD_AUTO_RULES") -> str:
        """Render rules into a standard markdown block with HTML comments."""
        from ctxguard.learn.plugins.writer import RoundTripContextWriter
        writer = RoundTripContextWriter(marker=marker)
        rendered_body = writer.render_body(rules)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return writer.MARKER_TEMPLATE.format(
            marker=marker,
            timestamp=now_str,
            body=rendered_body,
        )

    @classmethod
    def extract_marker_block(cls, file_content: str, marker: str = "CTXGUARD_AUTO_RULES") -> Optional[str]:
        """Extract content enclosed inside the specified marker block."""
        pattern = cls.MARKER_PATTERN.format(marker=re.escape(marker))
        match = re.search(pattern, file_content, flags=re.DOTALL)
        return match.group(1) if match else None

    @classmethod
    def parse_prior_rules(
        cls, marker_content: str, marker: Optional[str] = None
    ) -> List[LearnedRule]:
        """Reverse parse existing Markdown rule block into LearnedRule objects."""
        if not marker_content:
            return []

        if marker and f"<!-- {marker}:START -->" in marker_content:
            block = cls.extract_marker_block(marker_content, marker)
            if block:
                marker_content = block

        rules: List[LearnedRule] = []
        current_section = "General Rules"
        lines = marker_content.splitlines()

        current_trigger = ""
        current_directive = ""
        current_rationale = ""
        current_wasted = 0
        current_occurrences = 1

        def commit_rule():
            nonlocal current_trigger, current_directive, current_rationale, current_wasted, current_occurrences
            if current_directive or current_trigger:
                rule_id = f"rule_{abs(hash((current_section, current_trigger, current_directive))) % 1000000:06x}"
                rules.append(
                    LearnedRule(
                        rule_id=rule_id,
                        section=current_section,
                        trigger=current_trigger or "General Scenario",
                        directive=current_directive or current_trigger,
                        rationale=current_rationale,
                        wasted_tokens=current_wasted,
                        occurrence_count=current_occurrences,
                        carried_forward=True,
                    )
                )
            current_trigger = ""
            current_directive = ""
            current_rationale = ""
            current_wasted = 0
            current_occurrences = 1

        for line in lines:
            line_str = line.strip()
            # Section match: ### 1. Command Patterns (`bash`) or ## Section
            if line_str.startswith("### "):
                commit_rule()
                current_section = re.sub(r"^###\s+(\d+\.\s+)?", "", line_str)
            elif line_str.startswith("- **Rule**:"):
                current_directive = line_str.replace("- **Rule**:", "").strip()
            elif line_str.startswith("- **Context & Rationale**:"):
                current_rationale = line_str.replace("- **Context & Rationale**:", "").strip()
                m_tokens = re.search(r"Wasted ~(\d+)\s+Tokens", current_rationale, flags=re.IGNORECASE)
                if m_tokens:
                    current_wasted = int(m_tokens.group(1))
            elif line_str.startswith("- **Trigger**:"):
                current_trigger = line_str.replace("- **Trigger**:", "").strip()

        commit_rule()
        return rules

    @classmethod
    def merge_rules(
        cls,
        new_rules: List[LearnedRule],
        prior_rules: List[LearnedRule],
    ) -> List[LearnedRule]:
        """Merge newly generated rules with prior baseline rules.
        
        Rules with matching trigger/directive signatures are updated with fresh metrics;
        historical rules not triggered in this run are Carried Forward.
        """
        def sig(r: LearnedRule) -> str:
            # Canonical key based on section and normalized directive/trigger
            norm = re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fa5]", "", f"{r.section}:{r.trigger}:{r.directive}".lower())
            return norm

        merged_dict: Dict[str, LearnedRule] = {}

        # 1. Seed with prior rules (mark as carried forward)
        for pr in prior_rules:
            k = sig(pr)
            if k:
                pr.carried_forward = True
                merged_dict[k] = pr

        # 2. Overlay new rules (fresh discoveries overwrite and clear carried_forward flag)
        for nr in new_rules:
            k = sig(nr)
            if not k:
                continue
            if k in merged_dict:
                existing = merged_dict[k]
                # Accumulate or refresh tokens and occurrences
                nr.wasted_tokens = max(nr.wasted_tokens, existing.wasted_tokens)
                nr.occurrence_count = max(nr.occurrence_count, existing.occurrence_count)
            nr.carried_forward = False
            merged_dict[k] = nr

        merged_list = list(merged_dict.values())

        # 3. Sort by priority: high wasted tokens first, then occurrence count, fresh rules before carried forward
        merged_list.sort(
            key=lambda r: (
                0 if not r.carried_forward else 1,
                -r.wasted_tokens,
                -r.occurrence_count,
            )
        )
        return merged_list
