"""Claude ecosystem plugin for CtxGuard Learn engine.
Scans Claude Code trajectories (~/.claude/projects/...) and writes to CLAUDE.local.md / AGENTS.md.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from ctxguard.learn.models import ConversationSession, NormalizedToolCall, NormalizedTurn
from ctxguard.learn.plugins.base import BaseConversationScanner, BaseContextWriter, LearnPlugin
from ctxguard.learn.plugins.writer import RoundTripContextWriter
from ctxguard.utils.token_counter import estimate_tokens_from_text


class ClaudeConversationScanner(BaseConversationScanner):
    """Scans and normalizes Claude Code logs and subagent sessions."""

    def __init__(self, custom_dirs: Optional[List[Path]] = None):
        self.custom_dirs = custom_dirs or []

    def _get_search_dirs(self, project_path: Optional[Path] = None) -> List[Path]:
        search_dirs: List[Path] = list(self.custom_dirs)
        home = Path.home()
        claude_home = home / ".claude" / "projects"
        if claude_home.exists():
            search_dirs.append(claude_home)
        
        # Local agent dirs if applicable
        if project_path:
            p_claude = project_path / ".claude"
            if p_claude.exists():
                search_dirs.append(p_claude)
            p_pi = project_path / ".pi"
            if p_pi.exists():
                search_dirs.append(p_pi)

        # Also search home ~/.pi/agent/sessions
        pi_sessions = home / ".pi" / "agent" / "sessions"
        if pi_sessions.exists():
            search_dirs.append(pi_sessions)

        return search_dirs

    def scan_sessions(
        self,
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[ConversationSession]:
        search_dirs = self._get_search_dirs(project_path)
        found_files: List[Path] = []
        for s_dir in search_dirs:
            try:
                found_files.extend(s_dir.rglob("*.jsonl"))
            except Exception:
                continue

        now = time.time()
        max_age_sec = lookback_hours * 3600
        valid_files = []
        for f in found_files:
            try:
                mtime = f.stat().st_mtime
                if (now - mtime) <= max_age_sec:
                    valid_files.append((mtime, f))
            except Exception:
                continue

        valid_files.sort(key=lambda x: x[0], reverse=True)
        target_files = [f for _, f in valid_files[:limit]]

        sessions: List[ConversationSession] = []
        for f in target_files:
            session = self._parse_jsonl_session(f)
            if session and session.turns:
                sessions.append(session)

        return sessions

    def _parse_jsonl_session(self, file_path: Path) -> Optional[ConversationSession]:
        turns: List[NormalizedTurn] = []
        session_id = file_path.stem
        start_ts = 0.0
        end_ts = 0.0
        # tool_use_id -> tool name, so a result block can be attributed to the tool that
        # actually produced it. Claude Code writes only `tool_use_id` on a result block, so
        # without this join every failure loop is reported against the placeholder name
        # "tool_result" — evidence that names nothing and cannot be acted on.
        tool_name_by_call: Dict[str, str] = {}

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except Exception:
                        continue

                    ts = record.get("timestamp")
                    if isinstance(ts, (int, float)):
                        ts_val = float(ts)
                    elif isinstance(ts, str):
                        try:
                            from datetime import datetime
                            ts_val = datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                        except Exception:
                            ts_val = time.time()
                    else:
                        ts_val = time.time()

                    if start_ts == 0.0:
                        start_ts = ts_val
                    end_ts = ts_val

                    msg = record.get("message", record)
                    role = msg.get("role", record.get("type", "unknown"))
                    content_raw = msg.get("content", "")

                    text_content = ""
                    tool_calls: List[NormalizedToolCall] = []

                    if isinstance(content_raw, str):
                        text_content = content_raw
                    elif isinstance(content_raw, list):
                        text_parts = []
                        for item in content_raw:
                            if not isinstance(item, dict):
                                continue
                            itype = item.get("type", "")
                            if itype == "text":
                                text_parts.append(item.get("text", ""))
                            elif itype in ("toolCall", "tool_use"):
                                call_id = item.get("id")
                                tool_name = item.get("name", "unknown")
                                if call_id:
                                    tool_name_by_call[str(call_id)] = tool_name
                                tool_calls.append(
                                    NormalizedToolCall(
                                        tool_name=tool_name,
                                        arguments=item.get("arguments", item.get("input", {})),
                                        tokens_consumed=estimate_tokens_from_text(str(item)),
                                        raw_payload=item,
                                        # Claude Code writes the call id on the tool_use block and
                                        # repeats it as `tool_use_id` on the matching tool_result.
                                        call_id=call_id,
                                    )
                                )
                            elif itype in ("toolResult", "tool_result"):
                                out_text = item.get("content", item.get("text", ""))
                                is_err = item.get("is_error", False) or "error" in str(out_text).lower()
                                result_call_id = item.get("tool_use_id")
                                resolved_name = (
                                    item.get("tool_name")
                                    or tool_name_by_call.get(str(result_call_id))
                                    or "tool_result"
                                )
                                tool_calls.append(
                                    NormalizedToolCall(
                                        tool_name=resolved_name,
                                        output=str(out_text),
                                        is_error=is_err,
                                        tokens_consumed=estimate_tokens_from_text(str(out_text)),
                                        raw_payload=item,
                                        # Same provider id as the tool_use above: one call is
                                        # scanned as two events here (request + result), so the
                                        # replay check has to key on id *and* phase or a call
                                        # would be mistaken for a replay of its own result.
                                        call_id=result_call_id,
                                    )
                                )
                        text_content = "\n".join(text_parts)

                    tok = estimate_tokens_from_text(text_content)
                    for tc in tool_calls:
                        tok += tc.tokens_consumed

                    turns.append(
                        NormalizedTurn(
                            turn_id=f"{session_id}_{idx}",
                            role=role,
                            content=text_content,
                            tool_calls=tool_calls,
                            timestamp=ts_val,
                            tokens=tok,
                        )
                    )
        except Exception:
            return None

        return ConversationSession(
            session_id=session_id,
            agent_type="claude",
            project_path=str(file_path.parent),
            turns=turns,
            start_time=start_ts,
            end_time=end_ts,
        )


class ClaudePlugin(LearnPlugin):
    """Ecosystem plugin for Claude Code."""

    def __init__(self, custom_search_dirs: Optional[List[Path]] = None):
        self._scanner = ClaudeConversationScanner(custom_dirs=custom_search_dirs)
        self._writer = RoundTripContextWriter()

    @property
    def id(self) -> str:
        return "claude"

    @property
    def name(self) -> str:
        return "Claude Code Ecosystem"

    def get_scanner(self) -> BaseConversationScanner:
        return self._scanner

    def get_default_writer(self) -> BaseContextWriter:
        return self._writer

    def get_default_target_files(self, project_path: Path) -> List[Path]:
        return [
            project_path / "CLAUDE.local.md",
            project_path / "AGENTS.md",
        ]
