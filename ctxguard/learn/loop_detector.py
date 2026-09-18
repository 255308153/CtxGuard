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

    # Common developer tools/inspection commands that should never be marked as re-fetch dead loops
    COMMAND_WHITELIST = {
        "pytest", "python -m pytest", "python3 -m pytest", "python -m unittest", "python3 -m unittest",
        "git status", "git diff", "git log", "git branch", "git checkout", "git add", "git commit",
        "ls", "dir", "pwd", "cd", "echo", "cat", "clear", "which", "whoami",
        "build_pdf.sh", "make", "npm test", "npm run test", "cargo test", "cargo check",
        "ruff", "flake8", "mypy", "black", "isort", "uv run pytest", "uv run python",
    }

    # True pagination/output-limiting fragments that signal re-fetch behavior
    PAGING_PATTERNS = [
        re.compile(r"\|\s*(?:head|tail)\s*(?:-[n]?\s*\d+)?", re.IGNORECASE),
        re.compile(r"--(?:max-depth|depth|limit|max-count|lines)\s*=?\s*\d+", re.IGNORECASE),
        re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE),
        re.compile(r"\bOFFSET\s+\d+\b", re.IGNORECASE),
        re.compile(r"-n\s+\d+", re.IGNORECASE),
        re.compile(r"\b(?:head|tail)\s+-\d+\b", re.IGNORECASE),
    ]
    WS_REGEX = re.compile(r"\s+", re.MULTILINE)

    def __init__(self, threshold: int = 3):
        self.threshold = threshold

    @classmethod
    def is_whitelisted_command(cls, cmd: str) -> bool:
        """Check if command is a standard development/inspection operation exempt from loop detection."""
        if not cmd:
            return False
        clean = cmd.strip().lower()
        if clean in cls.COMMAND_WHITELIST:
            return True
        first_token = clean.split()[0] if clean.split() else ""
        if first_token in {"pytest", "git", "ls", "dir", "pwd", "cd", "cat", "echo", "make", "npm", "cargo", "ruff", "mypy"}:
            # Check for pytest or git inspection commands
            if first_token == "pytest" or clean.startswith("pytest ") or clean.startswith("uv run pytest"):
                return True
            if clean.startswith(("git status", "git diff", "git log", "git branch", "git checkout")):
                return True
            if first_token in {"ls", "pwd", "cd", "cat", "echo", "clear"}:
                return True
        return False

    @classmethod
    def has_paging_fragment(cls, cmd: str) -> bool:
        """Check whether a command actually contains pagination or output-limiting fragments."""
        if not cmd:
            return False
        return any(pat.search(cmd) for pat in cls.PAGING_PATTERNS)

    @classmethod
    def canonicalize_signature(cls, cmd: str) -> str:
        """Strip paging parameters (head -50, LIMIT 10, -n 20) to extract canonical command signature.
        Crucial for uncovering hidden Re-fetch Loops where commands return 200 OK but burn tokens.
        """
        if not cmd:
            return ""
        norm = cmd.strip()
        for pat in cls.PAGING_PATTERNS:
            norm = pat.sub(" ", norm)
        norm = cls.WS_REGEX.sub(" ", norm)
        return norm.strip().lower()

    def detect_loops_from_events(self, events: List[Any]) -> List[LoopIncident]:
        """Scan normalized LogEvent instances for failure loops and re-fetch loops.
        Groups detection per session to prevent normal developer commands across
        separate sessions from falsely being aggregated as dead loops.
        """
        if not events:
            return []

        # Group events by session_id to ensure loops are within-session phenomena
        from collections import defaultdict
        session_groups: Dict[str, List[Any]] = defaultdict(list)
        for ev in events:
            sid = ""
            if isinstance(ev, dict):
                sid = str(ev.get("session_id") or "default")
            else:
                sid = str(getattr(ev, "session_id", "default") or "default")
            session_groups[sid].append(ev)

        incidents: List[LoopIncident] = []
        seen_incident_keys = set()

        for sid, sess_events in session_groups.items():
            # 1. Repeated file not found / missing paths
            missing_file_counts: Dict[str, List[str]] = {}
            # 2. Repeated tool errors
            tool_failure_counts: Dict[str, List[str]] = {}
            # 3. Canonical command frequencies (Re-fetch Loops)
            canonical_cmd_counts: Dict[str, List[str]] = {}
            # 4. User interruptions / rejections
            rejection_counts: Dict[str, int] = {}

            for ev in sess_events:
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
                    cmd_str = str(cmd).strip()
                    # Whitelist check: Never flag standard developer inspection / testing commands
                    if not self.is_whitelisted_command(cmd_str):
                        sig = self.canonicalize_signature(cmd_str)
                        if len(sig) > 4:
                            canonical_cmd_counts.setdefault(sig, []).append(cmd_str)

                # Check user rejection
                if user_interrupt:
                    rejection_counts[tool_name] = rejection_counts.get(tool_name, 0) + 1

            # Evaluate thresholds within this session
            for path, snippets in missing_file_counts.items():
                if len(snippets) >= self.threshold:
                    key = ("repeated_query", path)
                    if key not in seen_incident_keys:
                        seen_incident_keys.add(key)
                        incidents.append(LoopIncident(
                            pattern_type="repeated_query",
                            target_identifier=path,
                            occurrence_count=len(snippets),
                            error_snippets=snippets[:3],
                            context_hint=f"Agent repeatedly attempted to access non-existent file: {path}",
                        ))

            for tool, snippets in tool_failure_counts.items():
                if len(snippets) >= self.threshold:
                    key = ("repeated_tool_failure", tool)
                    if key not in seen_incident_keys:
                        seen_incident_keys.add(key)
                        incidents.append(LoopIncident(
                            pattern_type="repeated_tool_failure",
                            target_identifier=tool,
                            occurrence_count=len(snippets),
                            error_snippets=snippets[:3],
                            context_hint=f"Agent encountered {len(snippets)} consecutive errors when executing tool: {tool}",
                        ))

            # Re-fetch loops (200 OK pseudo-successes)
            # Must satisfy: occurrence count >= threshold AND (at least one command has paging fragment OR commands vary across attempts)
            for sig, raw_cmds in canonical_cmd_counts.items():
                if len(raw_cmds) >= self.threshold:
                    has_paging = any(self.has_paging_fragment(c) for c in raw_cmds)
                    has_varying_calls = len(set(raw_cmds)) > 1
                    # A true re-fetch loop involves paging variants or offset shifts
                    if has_paging or has_varying_calls:
                        key = ("re_fetch_loop", sig)
                        if key not in seen_incident_keys:
                            seen_incident_keys.add(key)
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
                    key = ("user_rejection_loop", target)
                    if key not in seen_incident_keys:
                        seen_incident_keys.add(key)
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
