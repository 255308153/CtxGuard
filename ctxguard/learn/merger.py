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
        current_has_body = False

        def strip_render_artifacts(value: str) -> str:
            """Remove the decorations ``render_body`` adds, so a round trip is lossless.

            ``render_body`` appends a ``*(Carried Forward)*`` tag to every rule parsed from
            a previous block (all of which are carried forward by definition). If the parser
            does not strip it, the tag is re-appended on each run and the directive grows
            one tag per round trip — eventually pushing real content out of the prompt.
            """
            cleaned = value.replace("*(Carried Forward)*", "")
            return re.sub(r"\s+", " ", cleaned).strip()

        def commit_rule():
            nonlocal current_trigger, current_directive, current_rationale, current_wasted
            nonlocal current_occurrences, current_has_body
            if current_directive or current_trigger:
                rule_id = f"rule_{abs(hash((current_section, current_trigger, current_directive))) % 1000000:06x}"
                rules.append(
                    LearnedRule(
                        rule_id=rule_id,
                        section=current_section,
                        # Keep an absent trigger empty rather than inventing "General Scenario":
                        # the merge identity then falls back to the directive, which lets legacy
                        # blocks (written before the trigger line was rendered) merge in place.
                        trigger=current_trigger,
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
            current_has_body = False

        for line in lines:
            line_str = line.strip()
            # Section match: ### 1. Command Patterns (`bash`) or ## Section
            if line_str.startswith("### "):
                commit_rule()
                raw_section = re.sub(r"^###\s+(\d+\.\s+)?", "", line_str)
                current_section = raw_section
                # Legacy blocks (written by RuleRenderer) embedded the trigger in the section
                # heading: "### 1. Command Patterns (`Calling tool `bash``)". Left as-is, the
                # section name never equals the clean section a fresh run produces, so every
                # legacy rule would be duplicated once on upgrade instead of merging in place.
                # Split it back out so identity is stable across the format change.
                legacy = re.match(r"^(?P<name>.+?)\s*\(`(?P<trigger>.+)`\)$", raw_section)
                if legacy:
                    current_section = legacy.group("name").strip()
                    current_trigger = strip_render_artifacts(legacy.group("trigger"))
            elif line_str.startswith("- **Rule**:"):
                # A second "- **Rule**:" inside the same section starts a NEW rule. Only
                # committing at "### " boundaries silently collapsed every section to its
                # last rule: sections are allowed to hold multiple rules, and the legacy
                # one-rule-per-section layout is what hid this.
                #
                # The guard is `current_has_body`, not `current_trigger`: a legacy heading
                # already populates the trigger, so committing on that would emit a phantom
                # trigger-only rule before the real one.
                if current_has_body:
                    commit_rule()
                current_directive = strip_render_artifacts(line_str.replace("- **Rule**:", ""))
                current_has_body = True
            elif line_str.startswith("- **Context & Rationale**:"):
                current_rationale = strip_render_artifacts(line_str.replace("- **Context & Rationale**:", ""))
                m_tokens = re.search(r"Wasted ~(\d+)\s+Tokens", current_rationale, flags=re.IGNORECASE)
                if m_tokens:
                    current_wasted = int(m_tokens.group(1))
            elif line_str.startswith("- **Trigger**:"):
                current_trigger = strip_render_artifacts(line_str.replace("- **Trigger**:", ""))

        commit_rule()
        return rules

    @classmethod
    def merge_rules(
        cls,
        new_rules: List[LearnedRule],
        prior_rules: List[LearnedRule],
    ) -> List[LearnedRule]:
        """Merge newly generated rules with prior baseline rules.

        Rules with matching merge identities are updated in place with fresh metrics;
        historical rules not triggered in this run are Carried Forward.
        """
        def sig(r: LearnedRule) -> str:
            """Canonical merge identity: ``section + trigger``.

            The directive is deliberately EXCLUDED (this mirrors headroom's section-level
            overwrite semantics). Section + trigger is the *identity* of a rule — "when
            condition X arises in class Y". The directive is the payload, and it is
            expected to be re-worded as understanding improves. Including it in the key
            means every paraphrase counts as a brand-new rule, so the block can only grow:
            superseded guidance is never replaced, and the 10-rule cap degenerates into
            "whoever sorts first survives".

            Falls back to the directive when no trigger is present, so rules written before
            the trigger line was rendered still merge instead of duplicating.
            """
            def norm(value: str) -> str:
                return re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fa5]", "", (value or "").lower())

            section_key = norm(r.section)
            trigger_key = norm(r.trigger)
            if not trigger_key:
                return f"{section_key}:{norm(r.directive)}"
            return f"{section_key}:{trigger_key}"

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
