"""Causality reflection and action rule extractor."""

from dataclasses import dataclass
from typing import List
from ctxguard.learn.loop_detector import LoopIncident


@dataclass
class ExtractedRule:
    """A structured learned constraint rule for the Agent."""
    category: str      # "File System" | "Tool Usage" | "Error Recovery"
    trigger: str       # Trigger condition
    directive: str     # Positive / negative action rule for agent prompt
    rationale: str     # Why this rule was created


class CausalityExtractor:
    """Extracts distilled behavioral constraints from failure incidents."""

    def extract_rules(self, incidents: List[LoopIncident]) -> List[ExtractedRule]:
        """Convert loop incidents into actionable Agent guidelines."""
        rules: List[ExtractedRule] = []

        for inc in incidents:
            if inc.pattern_type == "repeated_query":
                path = inc.target_identifier
                rules.append(ExtractedRule(
                    category="File Access & Navigation",
                    trigger=f"Accessing path '{path}'",
                    directive=f"Do not blindly retry querying non-existent path `{path}`. Check directory structure first using `ls` or find tools before opening files.",
                    rationale=f"Observed {inc.occurrence_count} repeated FileNotFound failures on `{path}`.",
                ))
            elif inc.pattern_type == "repeated_tool_failure":
                tool = inc.target_identifier
                rules.append(ExtractedRule(
                    category="Tool Execution Guard",
                    trigger=f"Calling tool `{tool}`",
                    directive=f"When tool `{tool}` fails repeatedly, stop and inspect argument format or prerequisites rather than immediately repeating the same parameters.",
                    rationale=f"Observed {inc.occurrence_count} consecutive execution errors with `{tool}`.",
                ))
            else:
                rules.append(ExtractedRule(
                    category="Error Recovery",
                    trigger=f"Recurring error: {inc.target_identifier}",
                    directive=f"Verify environment state and error messages carefully before retrying operations on `{inc.target_identifier}`.",
                    rationale=f"Detected pattern `{inc.pattern_type}` with {inc.occurrence_count} occurrences.",
                ))

        return rules
