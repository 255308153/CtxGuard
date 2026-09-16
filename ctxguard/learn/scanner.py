"""Log scanner and event normalizer for Agent conversation histories."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import orjson

from ctxguard.storage.db import DatabaseManager


@dataclass
class LogEvent:
    """Normalized Agent interaction event across various log formats."""
    timestamp: float
    session_id: str
    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    output: str = ""
    is_error: bool = False
    role: str = "tool"               # "user" | "assistant" | "tool"
    user_interrupt: bool = False     # True if user rejected, cancelled, or interrupted
    metadata: Dict[str, Any] = field(default_factory=dict)


class LogScanner:
    """Scans Agent interaction logs from Claude Code, local SQLite, or custom JSONL paths."""

    USER_INTERRUPT_KEYWORDS = frozenset({"n", "no", "cancel", "stop", "abort", "不要", "取消", "停"})

    @classmethod
    def scan_claude_logs(cls, base_dir: Optional[Path] = None) -> List[LogEvent]:
        """Scan Claude Code conversation JSONL files in ~/.claude/projects or local workspace."""
        events: List[LogEvent] = []
        search_dirs: List[Path] = []

        if base_dir and base_dir.exists():
            search_dirs.append(base_dir)
        else:
            claude_home = Path.home() / ".claude" / "projects"
            if claude_home.exists():
                search_dirs.append(claude_home)
            local_claude = Path(".claude")
            if local_claude.exists():
                search_dirs.append(local_claude)

        for s_dir in search_dirs:
            for jsonl_file in s_dir.rglob("*.jsonl"):
                try:
                    events.extend(cls._parse_claude_jsonl(jsonl_file))
                except Exception:
                    continue

        events.sort(key=lambda e: e.timestamp)
        return events

    @classmethod
    def _parse_claude_jsonl(cls, file_path: Path) -> List[LogEvent]:
        """Parse single Claude Code JSONL trajectory file."""
        events: List[LogEvent] = []
        session_id = file_path.stem
        base_time = file_path.stat().st_mtime

        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue

                ts = record.get("timestamp") or (base_time + idx * 0.1)
                role = record.get("role") or record.get("type", "unknown")

                # 1. User message / rejection check
                if role == "user":
                    content = record.get("content") or record.get("message", "")
                    if isinstance(content, list):
                        text_content = " ".join(b.get("text", "") for b in content if isinstance(b, dict))
                    else:
                        text_content = str(content).strip()

                    is_interrupt = text_content.lower() in cls.USER_INTERRUPT_KEYWORDS
                    events.append(LogEvent(
                        timestamp=ts,
                        session_id=session_id,
                        tool_name="user_input",
                        output=text_content,
                        role="user",
                        user_interrupt=is_interrupt,
                    ))

                # 2. Assistant tool use
                elif role == "assistant":
                    content = record.get("content", [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_use":
                                events.append(LogEvent(
                                    timestamp=ts,
                                    session_id=session_id,
                                    tool_name=block.get("name", "unknown_tool"),
                                    tool_input=block.get("input", {}),
                                    role="assistant",
                                ))

                # 3. Tool result
                elif role in ("tool", "tool_result") or record.get("type") == "tool_result":
                    output_content = str(record.get("content", "") or record.get("output", ""))
                    is_err = bool(record.get("is_error", False))
                    if not is_err:
                        # Scan common failure signals
                        err_indicators = ["FileNotFoundError", "NoSuchFile", "ModuleNotFoundError", "command not found", "Permission denied", "Error:", "exit code 1"]
                        is_err = any(ind.lower() in output_content.lower() for ind in err_indicators)

                    events.append(LogEvent(
                        timestamp=ts,
                        session_id=session_id,
                        tool_name=record.get("name", "tool_result"),
                        tool_input=record.get("input", {}),
                        output=output_content,
                        is_error=is_err,
                        role="tool",
                    ))

        return events

    @classmethod
    def scan_ctxguard_db(cls, db_path: Path, limit: int = 500) -> List[LogEvent]:
        """Scan CtxGuard SQLite requests database for session trajectories."""
        events: List[LogEvent] = []
        if not db_path.exists():
            return events

        db_mgr = DatabaseManager(str(db_path))
        with db_mgr.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, timestamp, session_id, model, prompt_preview, applied_compressors FROM requests ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            for row in cursor.fetchall():
                req_id, ts_str, session_id, model, preview, compressors_json = row
                try:
                    ts = time.time()
                except Exception:
                    ts = time.time()

                events.append(LogEvent(
                    timestamp=ts,
                    session_id=session_id or "default",
                    tool_name="chat_request",
                    output=preview or "",
                    role="user",
                    metadata={"model": model, "request_id": req_id},
                ))

        return events
