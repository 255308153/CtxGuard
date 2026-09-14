"""Markdown renderer for learned behavioral rules."""

from datetime import datetime
from typing import List
from ctxguard.learn.causality_extractor import ExtractedRule


class RuleRenderer:
    """Renders extracted rules into clean Markdown documentation blocks."""

    @classmethod
    def render_markdown_block(cls, rules: List[ExtractedRule], marker: str = "CTXGUARD_AUTO_RULES") -> str:
        """Render rules enclosed within start and end markers."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            f"<!-- {marker}:START -->",
            "## 🛡️ CtxGuard Auto-Learned Rules & Loop Guards",
            f"> *Last updated: {now_str} (Generated automatically from incident analysis)*",
            "",
        ]

        if not rules:
            lines.append("*(No active loop incidents or failure patterns recorded.)*")
        else:
            for idx, r in enumerate(rules, start=1):
                lines.append(f"### {idx}. {r.category} (`{r.trigger}`)")
                lines.append(f"- **Rule**: {r.directive}")
                lines.append(f"- **Context & Rationale**: {r.rationale}")
                lines.append("")

        lines.append(f"<!-- {marker}:END -->")
        return "\n".join(lines)
