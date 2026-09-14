"""Loop and repetitive failure detection engine for Agent trajectories."""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class LoopIncident:
    """Represents an identified loop or repeated failure pattern in conversation."""
    pattern_type: str              # "repeated_tool_failure" | "repeated_query" | "error_oscillation"
    target_identifier: str         # Tool name, file path, or error type
    occurrence_count: int
    error_snippets: List[str] = field(default_factory=list)
    context_hint: str = ""


class LoopDetector:
    """Scans conversation events or historical logs to detect dead loops and repetitive failures."""

    FILE_NOT_FOUND_REGEX = re.compile(r"(?:No such file or directory|FileNotFoundError|cannot find the file|ENOENT):\s*['\"]?([a-zA-Z0-9_\-\./\\]+)['\"]?", re.IGNORECASE)
    PERMISSION_DENIED_REGEX = re.compile(r"(?:Permission denied|EACCES|Operation not permitted):\s*['\"]?([a-zA-Z0-9_\-\./\\]+)['\"]?", re.IGNORECASE)

    def __init__(self, threshold: int = 3):
        self.threshold = threshold

    def detect_loops_from_messages(self, messages: List[Dict[str, Any]]) -> List[LoopIncident]:
        """Scan a message sequence for failure loops."""
        incidents: List[LoopIncident] = []

        # 1. Detect repeated file not found / missing paths
        missing_file_counts: Dict[str, List[str]] = {}
        # 2. Detect repeated tool execution errors
        tool_failure_counts: Dict[str, List[str]] = {}

        for msg in messages:
            content = str(msg.get("content", ""))
            role = msg.get("role", "")

            # Scan for missing file errors
            file_match = self.FILE_NOT_FOUND_REGEX.search(content)
            if file_match:
                path = file_match.group(1)
                missing_file_counts.setdefault(path, []).append(content[:150])

            # Scan for tool error keywords in tool responses
            if role in {"tool", "user"} and any(err_kw in content.lower() for err_kw in ["error:", "failed", "exception", "traceback"]):
                tool_name = msg.get("name") or "tool_call"
                tool_failure_counts.setdefault(tool_name, []).append(content[:150])

        # Evaluate thresholds
        for path, snippets in missing_file_counts.items():
            if len(snippets) >= self.threshold:
                incidents.append(LoopIncident(
                    pattern_type="repeated_query",
                    target_identifier=path,
                    occurrence_count=len(snippets),
                    error_snippets=snippets[:3],
                    context_hint=f"Agent repeatedly attempted to access non-existent file: {path}",
                ))

        for tool, snippets in tool_failure_counts.items():
            if len(snippets) >= self.threshold:
                incidents.append(LoopIncident(
                    pattern_type="repeated_tool_failure",
                    target_identifier=tool,
                    occurrence_count=len(snippets),
                    error_snippets=snippets[:3],
                    context_hint=f"Agent encountered {len(snippets)} consecutive errors when executing tool: {tool}",
                ))

        return incidents
