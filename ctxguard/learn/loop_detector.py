"""Loop and repetitive failure detection engine for Agent trajectories."""

from dataclasses import dataclass, field
import re
from typing import Any, Dict, List, Optional


# Measured-waste accounting (mirrors headroom's loops.py contract):
# waste is derived from the bytes that actually crossed the wire, never guessed by a model.
MEASURED_BYTES_PER_TOKEN = 4

# Budget for one piece of failure evidence kept in a digest or an incident.
EVIDENCE_PREVIEW_MAX = 200


def truncate_head_tail(text: Any, max_chars: int = EVIDENCE_PREVIEW_MAX) -> str:
    """Collapse newlines and truncate, keeping both the head and the tail of the text.

    A head-only slice of an error drops the end of the traceback, which is exactly where
    the root cause lives (``ExceptionType: message``, the failing assertion, the non-zero
    exit line). The digest would then show the preamble and lose the diagnosis while still
    costing the full prompt. Keeping both ends preserves the two informative regions: the
    attempted operation at the head and the outcome at the tail.
    """
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    sep = " … "
    keep = max_chars - len(sep)
    head = keep // 2
    tail = keep - head
    return f"{text[:head].rstrip()}{sep}{text[-tail:].lstrip()}"


def measure_event_tokens(output: Any = None, tool_input: Any = None) -> int:
    """Approximate the tokens one tool event actually pushed into the context window.

    Uses the same 4-bytes-per-token convention as headroom's loops.py, computed over
    *both* the tool result and the tool arguments, so an event that returned nothing
    but carried a huge command still registers as non-zero waste.
    """
    char_count = len(str(output or "")) + len(str(tool_input or ""))
    return max(1, char_count // MEASURED_BYTES_PER_TOKEN)


@dataclass
class _Evidence:
    """One event already attributed to a loop family.

    Carrying the measured tokens alongside the snippet means the waste can be summed at
    incident-build time without walking the events a second time, and ``replay_key`` is
    what the two dedup passes compare.
    """
    snippet: str
    tokens: int
    replay_key: str = ""
    raw: str = ""      # raw command text; re-fetch loops need it to test paging fragments


@dataclass
class LoopIncident:
    """Represents an identified loop or repeated failure pattern in conversation."""
    pattern_type: str              # "repeated_tool_failure" | "repeated_query" | "re_fetch_loop" | "user_rejection_loop"
    target_identifier: str         # Tool name, canonical command, or file path
    occurrence_count: int
    error_snippets: List[str] = field(default_factory=list)
    context_hint: str = ""
    wasted_tokens: int = 0         # MEASURED waste (not model-estimated). See measure_event_tokens().
    first_call_tokens: int = 0     # tokens of the first (legitimate) call, already excluded from wasted_tokens


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

    @staticmethod
    def replay_key(call_id: Any, role: str) -> str:
        """Identity by which a replayed call is recognised, or "" when the event carries none.

        The phase (``role``) is part of the key because the scanner splits one provider call
        into two events — the assistant's tool_use and the tool's result — which carry the
        same provider id. Keying on the id alone would make a call look like a replay of its
        own result and silently drop the failure evidence.

        An empty key means "nothing identifies this event", so it is never treated as a
        replay (mirrors headroom's ``_without_replays``).
        """
        if not call_id:
            return ""
        return f"{call_id}|{role or ''}"

    @classmethod
    def _without_replays(cls, records: List["_Evidence"], seen: set) -> List["_Evidence"]:
        """Drop records whose identity is already in ``seen``, recording the rest.

        ``seen`` is mutated, which lets the caller choose the scope a replay is judged
        against: a fresh set collapses a transcript's own repeated turns, while a set carried
        across merges suppresses a resumed session replaying earlier ones.
        """
        kept: List["_Evidence"] = []
        for rec in records:
            if rec.replay_key:
                if rec.replay_key in seen:
                    continue
                seen.add(rec.replay_key)
            kept.append(rec)
        return kept

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

        # family -> signature -> evidence, accumulated ACROSS sessions after both dedup phases.
        #
        # Replay dedup runs before the threshold, twice over (headroom's contract):
        #   1. each session is screened on its own *distinct* calls, because the question the
        #      threshold asks — did this conversation repeat itself? — is not answered by one
        #      call written into the transcript three times; and
        #   2. qualifying sessions are then merged, deduped again against the identities other
        #      sessions already contributed for that signature, so a resume replaying an earlier
        #      session adds only what is genuinely new.
        # Screening the raw groups instead would let three sessions that each merely replayed a
        # single call add up to a loop that no conversation ever ran.
        merged: Dict[str, Dict[str, List["_Evidence"]]] = {"missing": {}, "failure": {}, "refetch": {}}
        merged_seen: Dict[str, Dict[str, set]] = {"missing": {}, "failure": {}, "refetch": {}}

        for sid, sess_events in session_groups.items():
            per_session: Dict[str, Dict[str, List["_Evidence"]]] = {"missing": {}, "failure": {}, "refetch": {}}
            # User interruptions / rejections
            rejection_counts: Dict[str, int] = {}

            for ev in sess_events:
                if isinstance(ev, dict):
                    role = ev.get("role", "")
                    output = str(ev.get("output") or ev.get("content") or "")
                    tool_name = str(ev.get("tool_name") or ev.get("name") or "tool")
                    tool_input = ev.get("tool_input") or ev.get("input") or {}
                    is_err = bool(ev.get("is_error", False))
                    user_interrupt = bool(ev.get("user_interrupt", False))
                    call_id = ev.get("call_id") or ""
                else:
                    role = getattr(ev, "role", "")
                    output = str(getattr(ev, "output", "") or getattr(ev, "content", ""))
                    tool_name = str(getattr(ev, "tool_name", "") or getattr(ev, "name", "tool"))
                    tool_input = getattr(ev, "tool_input", {})
                    is_err = bool(getattr(ev, "is_error", False))
                    user_interrupt = bool(getattr(ev, "user_interrupt", False))
                    call_id = getattr(ev, "call_id", "") or ""

                # Measured waste for this single event: bytes actually transferred / 4.
                ev_tokens = measure_event_tokens(output, tool_input)
                replay_key = self.replay_key(call_id, role)

                # Error evidence keeps both ends: the tail carries the actual cause.
                file_match = self.FILE_NOT_FOUND_REGEX.search(output)
                if file_match:
                    path = file_match.group(1)
                    per_session["missing"].setdefault(path, []).append(
                        _Evidence(truncate_head_tail(output, 150), ev_tokens, replay_key)
                    )

                # Check tool failures
                if is_err or (role in {"tool", "user"} and any(err_kw in output.lower() for err_kw in ["error:", "failed", "exception", "traceback"])):
                    per_session["failure"].setdefault(tool_name, []).append(
                        _Evidence(truncate_head_tail(output, 150), ev_tokens, replay_key)
                    )

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
                            per_session["refetch"].setdefault(sig, []).append(
                                _Evidence(cmd_str, ev_tokens, replay_key, raw=cmd_str)
                            )

                # Check user rejection
                if user_interrupt:
                    rejection_counts[tool_name] = rejection_counts.get(tool_name, 0) + 1

            # Phase 1, then phase 2 (see the contract note above).
            for family, groups in per_session.items():
                for sig, records in groups.items():
                    distinct = self._without_replays(records, set())
                    if len(distinct) < self.threshold:
                        continue
                    bucket = merged[family].setdefault(sig, [])
                    bucket.extend(
                        self._without_replays(distinct, merged_seen[family].setdefault(sig, set()))
                    )

            # User rejection loops. Counted per session rather than merged: a rejection is a
            # human turn with no provider-assigned id, so nothing identifies a replay of it.
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

        # ---- Emit from the merged view --------------------------------------------
        for path, records in merged["missing"].items():
            incidents.append(LoopIncident(
                pattern_type="repeated_query",
                target_identifier=path,
                occurrence_count=len(records),
                error_snippets=[r.snippet for r in records[:3]],
                context_hint=f"Agent repeatedly attempted to access non-existent file: {path}",
                # Error loop: every occurrence bought nothing, so all of it is waste.
                wasted_tokens=sum(r.tokens for r in records),
            ))

        for tool, records in merged["failure"].items():
            incidents.append(LoopIncident(
                pattern_type="repeated_tool_failure",
                target_identifier=tool,
                occurrence_count=len(records),
                error_snippets=[r.snippet for r in records[:3]],
                context_hint=f"Agent encountered {len(records)} consecutive errors when executing tool: {tool}",
                # Error loop: all occurrences are waste.
                wasted_tokens=sum(r.tokens for r in records),
            ))

        # Re-fetch loops (200 OK pseudo-successes): a merged group needs either a paging
        # fragment or varying commands across attempts, since only those show the agent was
        # re-issuing the same query to see more.
        for sig, records in merged["refetch"].items():
            cmds_text = [r.raw for r in records]
            has_paging = any(self.has_paging_fragment(c) for c in cmds_text)
            has_varying_calls = len(set(cmds_text)) > 1
            if not (has_paging or has_varying_calls):
                continue
            # Re-fetch loop: the FIRST call was legitimate work (the agent could not have known
            # the output was too short). Only occurrences 2..N are waste, so the first call's
            # measured tokens are excluded.
            tokens = [r.tokens for r in records]
            first_call_tokens = tokens[0] if tokens else 0
            incidents.append(LoopIncident(
                pattern_type="re_fetch_loop",
                target_identifier=sig,
                occurrence_count=len(records),
                error_snippets=[f"Command: {c}" for c in cmds_text[:3]],
                context_hint=f"Agent repeatedly executed query variations `{sig}` {len(records)} times with incremental paging (Re-fetch Loop).",
                wasted_tokens=sum(tokens) - first_call_tokens,
                first_call_tokens=first_call_tokens,
            ))

        # Highest measured waste first: the digest prints this order and is budget-clipped, so
        # the ranking has to be decided here rather than by dict insertion order.
        incidents.sort(key=lambda i: i.wasted_tokens, reverse=True)
        return incidents

    def detect_loops_from_messages(self, messages: List[Dict[str, Any]]) -> List[LoopIncident]:
        """Scan a message sequence for failure loops (backward-compatible API)."""
        return self.detect_loops_from_events(messages)
