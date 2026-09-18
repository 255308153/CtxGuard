"""CtxGuard Gateway Plugin for Learn Engine.
Mines full live network traffic, proxy trajectories, and compression incidents from ctxguard.db.
"""

from __future__ import annotations
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Dict, List, Optional

from ctxguard.learn.models import ConversationSession, NormalizedToolCall, NormalizedTurn
from ctxguard.learn.plugins.base import BaseConversationScanner, BaseContextWriter, LearnPlugin
from ctxguard.learn.plugins.writer import RoundTripContextWriter
from ctxguard.utils.token_counter import estimate_tokens_from_text


class CtxGuardGatewayScanner(BaseConversationScanner):
    """Scans and extracts conversation sessions directly from CtxGuard SQLite requests database."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path(".ctxguard.db")

    def scan_sessions(
        self,
        project_path: Optional[Path] = None,
        lookback_hours: int = 48,
        limit: int = 50,
    ) -> List[ConversationSession]:
        target_db = self.db_path
        if not target_db.exists() and project_path:
            alt = project_path / ".ctxguard.db"
            if alt.exists():
                target_db = alt

        if not target_db.exists():
            return []

        sessions_map: Dict[str, List[Dict[str, Any]]] = {}
        cutoff_time = time.time() - (lookback_hours * 3600)

        try:
            conn = sqlite3.connect(f"file:{target_db}?mode=ro", uri=True)
            cursor = conn.cursor()

            # Inspect available tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='requests'")
            if not cursor.fetchone():
                conn.close()
                return []

            cursor.execute(
                """
                SELECT session_id, timestamp, model, raw_tokens, optimized_tokens, 
                       saved_tokens, cached_tokens, prompt_preview, applied_compressors, latency_ms
                FROM requests
                WHERE timestamp >= ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (cutoff_time, limit * 20),
            )

            rows = cursor.fetchall()
            for r in rows:
                sid = r[0] or "ses_default"
                sessions_map.setdefault(sid, []).append(
                    {
                        "session_id": sid,
                        "timestamp": r[1],
                        "model": r[2],
                        "raw_tokens": r[3],
                        "optimized_tokens": r[4],
                        "saved_tokens": r[5],
                        "cached_tokens": r[6],
                        "prompt_preview": r[7],
                        "applied_compressors": r[8],
                        "latency_ms": r[9],
                    }
                )
            conn.close()
        except Exception:
            return []

        conv_sessions: List[ConversationSession] = []
        for sid, req_list in list(sessions_map.items())[:limit]:
            turns: List[NormalizedTurn] = []
            start_ts = req_list[0]["timestamp"] if req_list else 0.0
            end_ts = req_list[-1]["timestamp"] if req_list else 0.0

            for idx, item in enumerate(req_list):
                prompt = item.get("prompt_preview") or ""
                tok = item.get("optimized_tokens") or item.get("raw_tokens") or estimate_tokens_from_text(prompt)

                tool_calls: List[NormalizedToolCall] = []
                # If prompt preview contains tool failure signatures
                is_err = "error" in prompt.lower() or "exception" in prompt.lower()
                if "tool" in prompt.lower() or "calling" in prompt.lower():
                    tool_calls.append(
                        NormalizedToolCall(
                            tool_name="gateway_tool_trace",
                            output=prompt[:500],
                            is_error=is_err,
                            tokens_consumed=tok,
                        )
                    )

                turns.append(
                    NormalizedTurn(
                        turn_id=f"{sid}_{idx}",
                        role="user" if idx % 2 == 0 else "assistant",
                        content=prompt,
                        tool_calls=tool_calls,
                        timestamp=item["timestamp"],
                        tokens=tok,
                    )
                )

            conv_sessions.append(
                ConversationSession(
                    session_id=sid,
                    agent_type="ctxguard",
                    project_path=str(project_path) if project_path else None,
                    turns=turns,
                    start_time=start_ts,
                    end_time=end_ts,
                    metadata={"total_requests": len(req_list)},
                )
            )

        return conv_sessions


class CtxGuardGatewayPlugin(LearnPlugin):
    """Ecosystem plugin extracting trajectories from CtxGuard's own proxy traffic."""

    def __init__(self, db_path: Optional[Path] = None):
        self._scanner = CtxGuardGatewayScanner(db_path=db_path)
        self._writer = RoundTripContextWriter()

    @property
    def id(self) -> str:
        return "ctxguard"

    @property
    def name(self) -> str:
        return "CtxGuard Gateway Traffic"

    def get_scanner(self) -> BaseConversationScanner:
        return self._scanner

    def get_default_writer(self) -> BaseContextWriter:
        return self._writer

    def get_default_target_files(self, project_path: Path) -> List[Path]:
        return [
            project_path / "AGENTS.md",
            project_path / "INSTRUCTIONS.md",
        ]
