"""Loop and repetitive failure detection engine for Agent trajectories."""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class LoopIncident:
    """Represents an identified loop or repeated failure pattern in conversation."""
    pattern_type: str              # "repeated_tool_failure" | "repeated_query" | "re_fetch_loop" | "user_rejection_loop"
    target_identifier: str         # Tool name, canonical command, or file path
    occurrence_count: int
    error_snippets: List[str] = field(default_factory=list)
    context_hint: str = ""


class LoopDetector:
    """Scans conversation events or historical logs to detect dead loops and repetitive failures.
    Includes canonical command signatures to uncover hidden 200 OK Re-fetch Loops.
    """

    FILE_NOT_FOUND_REGEX = re.compile(r"(?:No such file or directory|FileNotFoundError|cannot find the file|ENOENT):\s*['\"]?([a-zA-Z0-9_\-\./\\]+)['\"]?", re.IGNORECASE)
    PERMISSION_DENIED_REGEX = re.compile(r"(?:Permission denied|EACCES|Operation not permitted):\s*['\"]?([a-zA-Z0-9_\-\./\\]+)['\"]?", re.IGNORECASE)

    # Regex patterns to strip paging and limit noise
    PAGING_STRIP_REGEX = [
        re.compile(r"\|\s*(?:head|tail)\s*(?:-[n]?\s*\d+)?", re.IGNORECASE),
        re.compile(r"--(?:max-depth|depth|limit)\s*=?\s*\d+", re.IGNORECASE),
        re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE),
        re.compile(r"\bOFFSET\s+\d+\b", re.IGNORECASE),
        re.compile(r"-n\s+\d+", re.IGNORECASE),
        re.compile(r"\s+", re.MULTILINE),
    ]

    def __init__(self, threshold: int = 3):
        self.threshold = threshold

    @classmethod
    def canonicalize_signature(cls, cmd: str) -> str:
        """Strip paging parameters (head -50, LIMIT 10, -n 20) to extract canonical command signature.
        Crucial for uncovering hidden Re-fetch Loops where commands return 200 OK but burn tokens.
        """
        if not cmd:
            return ""
        norm = cmd.strip()
        for pat in cls.PAGING_STRIP_REGEX:
            norm = pat.sub(" ", norm)
        return norm.strip().lower()

    def detect_loops_from_events(self, events: List[Any]) -> List[LoopIncident]:
        """Scan normalized LogEvent instances for failure loops and re-fetch loops."""
        incidents: List[LoopIncident] = []

        # 1. Repeated file not found / missing paths
        missing_file_counts: Dict[str, List[str]] = {}
        # 2. Repeated tool errors
        tool_failure_counts: Dict[str, List[str]] = {}
        # 3. Canonical command frequencies (Re-fetch Loops)
        canonical_cmd_counts: Dict[str, List[str]] = {}
        # 4. User interruptions / rejections
        rejection_counts: Dict[str, int] = {}

        for ev in events:
            if isinstance(ev, dict):
                role = ev.get("role", "")
                output = str(ev.get("output") or ev.get("content") or "")
                tool_name = str(ev.get("tool_name") or ev.get("name") or "tool")
                tool_input = ev.get("tool_input") or ev.get("input") or {}
                is_err = bool(ev.get("is_error", False))
                user_interrupt = bool(ev.get("user_interrupt", False))
            else:
                role = getattr(ev, "role", "")
                output = str(getattr(ev, "output", "") or getattr(ev, "content", ""))
                tool_name = str(getattr(ev, "tool_name", "") or getattr(ev, "name", "tool"))
                tool_input = getattr(ev, "tool_input", {})
                is_err = bool(getattr(ev, "is_error", False))
                user_interrupt = bool(getattr(ev, "user_interrupt", False))

            # Check file errors
            file_match = self.FILE_NOT_FOUND_REGEX.search(output)
            if file_match:
                path = file_match.group(1)
                missing_file_counts.setdefault(path, []).append(output[:150])

            # Check tool failures
            if is_err or (role in {"tool", "user"} and any(err_kw in output.lower() for err_kw in ["error:", "failed", "exception", "traceback"])):
                tool_failure_counts.setdefault(tool_name, []).append(output[:150])

            # Check Re-fetch loop: assistant tool input commands
            cmd = None
            if isinstance(tool_input, dict):
                cmd = tool_input.get("command") or tool_input.get("cmd") or tool_input.get("query")
            if cmd:
                sig = self.canonicalize_signature(str(cmd))
                if len(sig) > 4:
                    canonical_cmd_counts.setdefault(sig, []).append(str(cmd))

            # Check user rejection
            if user_interrupt:
                rejection_counts[tool_name] = rejection_counts.get(tool_name, 0) + 1

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

        # Re-fetch loops (200 OK pseudo-successes)
        for sig, raw_cmds in canonical_cmd_counts.items():
            if len(raw_cmds) >= self.threshold:
                incidents.append(LoopIncident(
                    pattern_type="re_fetch_loop",
                    target_identifier=sig,
                    occurrence_count=len(raw_cmds),
                    error_snippets=[f"Command: {c}" for c in raw_cmds[:3]],
                    context_hint=f"Agent repeatedly executed query variations `{sig}` {len(raw_cmds)} times with incremental paging (Re-fetch Loop).",
                ))

        # User rejection loops
        for target, count in rejection_counts.items():
            if count >= self.threshold:
                incidents.append(LoopIncident(
                    pattern_type="user_rejection_loop",
                    target_identifier=target,
                    occurrence_count=count,
                    context_hint=f"User repeatedly rejected automated execution of `{target}` {count} times.",
                ))

        return incidents

    def detect_loops_from_messages(self, messages: List[Dict[str, Any]]) -> List[LoopIncident]:
        """Scan a message sequence for failure loops (backward-compatible API)."""
        return self.detect_loops_from_events(messages)
