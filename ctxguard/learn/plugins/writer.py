"""Round-trip Context Writer for idempotent project rule injection and memory synchronization.
Implements CtxGuard Engine's round-trip marker preservation, section-level carry-forward, and .gitignore safeguards.
"""

from __future__ import annotations
from datetime import datetime
import os
from pathlib import Path
import re
import tempfile
from typing import List, Optional

from ctxguard.learn.models import LearnedRule
from ctxguard.learn.merger import RuleMerger
from ctxguard.learn.plugins.base import BaseContextWriter


class RoundTripContextWriter(BaseContextWriter):
    """Writes learned rules idempotently while preserving prior historical learnings."""

    def __init__(self, marker: str = "CTXGUARD_AUTO_RULES"):
        self.marker = marker

    MARKER_TEMPLATE = """<!-- {marker}:START -->
## CtxGuard Auto-Learned Rules & Loop Guards
> *Last updated: {timestamp} (Generated automatically from incident analysis)*

{body}
<!-- {marker}:END -->"""

    @classmethod
    def render_body(cls, rules: List[LearnedRule]) -> str:
        """Render markdown body grouped by sections.

        Every field that participates in the merge identity MUST be rendered. The
        ``- **Trigger**:`` line is part of the ``section + trigger`` identity, so
        omitting it makes the block non-round-trippable: on the next run the parser
        would fall back to ``"General Scenario"``, the identity would drift, and the
        merge would append a duplicate instead of overwriting in place.
        """
        if not rules:
            return "*(No active loop incidents or failure patterns recorded.)*"

        sections: dict[str, List[LearnedRule]] = {}
        for r in rules:
            sections.setdefault(r.section, []).append(r)

        output_parts: List[str] = []
        sec_idx = 1
        for sec_name, sec_rules in sections.items():
            output_parts.append(f"### {sec_idx}. {sec_name}")
            sec_idx += 1
            for r in sec_rules:
                cf_tag = " *(Carried Forward)*" if r.carried_forward else ""
                output_parts.append(f"- **Rule**: {r.directive}{cf_tag}")
                # Always emit the trigger (never collapse it into a default) so the
                # identity survives the write -> parse round trip.
                if r.trigger:
                    output_parts.append(f"- **Trigger**: {r.trigger}")

                context_info = []
                if r.rationale:
                    context_info.append(r.rationale)
                if r.wasted_tokens > 0:
                    context_info.append(f"Wasted ~{r.wasted_tokens} Tokens across {r.occurrence_count} loop(s).")
                elif r.occurrence_count > 1:
                    context_info.append(f"Observed in {r.occurrence_count} occurrences.")
                
                if context_info:
                    output_parts.append(f"- **Context & Rationale**: {' '.join(context_info)}")
            output_parts.append("")

        return "\n".join(output_parts).rstrip()

    @classmethod
    def ensure_gitignore_safety(cls, target_file: Path) -> None:
        """Ensure local private rule files (like CLAUDE.local.md) are ignored in .gitignore."""
        if not target_file.name.endswith(".local.md"):
            return
        gitignore_path = target_file.parent / ".gitignore"
        rule_entry = target_file.name
        try:
            if gitignore_path.exists():
                content = gitignore_path.read_text(encoding="utf-8")
                if rule_entry not in content.splitlines():
                    with open(gitignore_path, "a", encoding="utf-8") as f:
                        if content and not content.endswith("\n"):
                            f.write("\n")
                        f.write(f"{rule_entry}\n")
            else:
                gitignore_path.write_text(f"{rule_entry}\n", encoding="utf-8")
        except Exception:
            pass

    def write_rules(
        self,
        target_path: Path,
        new_rules: List[LearnedRule],
        marker: str = "CTXGUARD_AUTO_RULES",
        max_rules: Optional[int] = None,
    ) -> bool:
        """Write rules into target_path with round-trip carry-forward of prior baseline rules.

        ``max_rules`` is applied *after* the merge, so the cap governs the total number
        of installed rules rather than only the newly discovered ones. Without a cap the
        block grows monotonically: every run can add more than it supersedes.
        """
        target_path = Path(target_path).resolve()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_gitignore_safety(target_path)

        existing_content = ""
        prior_rules: List[LearnedRule] = []
        if target_path.exists():
            try:
                existing_content = target_path.read_text(encoding="utf-8")
                prior_marker = RuleMerger.extract_marker_block(existing_content, marker=marker)
                if prior_marker:
                    prior_rules = RuleMerger.parse_prior_rules(prior_marker)
            except Exception:
                pass

        # Perform round-trip merge, then enforce the capacity cap
        merged_rules = RuleMerger.merge_rules(new_rules, prior_rules)
        if max_rules is not None:
            from ctxguard.learn.pruner import RulePruner
            merged_rules = RulePruner.prune(merged_rules, max_rules=max_rules)

        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rendered_body = self.render_body(merged_rules)
        new_block = self.MARKER_TEMPLATE.format(
            marker=marker,
            timestamp=timestamp_str,
            body=rendered_body,
        )

        marker_pattern = rf"<!--\s*{re.escape(marker)}:START\s*-->.*?<!--\s*{re.escape(marker)}:END\s*-->"
        if re.search(marker_pattern, existing_content, flags=re.DOTALL):
            final_content = re.sub(marker_pattern, new_block, existing_content, flags=re.DOTALL)
        else:
            if existing_content.strip():
                final_content = f"{existing_content.rstrip()}\n\n{new_block}\n"
            else:
                final_content = f"{new_block}\n"

        # Atomic file replacement
        try:
            with tempfile.NamedTemporaryFile("w", dir=str(target_path.parent), delete=False, encoding="utf-8") as tf:
                tf.write(final_content)
                temp_name = tf.name
            os.replace(temp_name, str(target_path))
            return True
        except Exception:
            if os.path.exists(temp_name):
                os.remove(temp_name)
            raise
