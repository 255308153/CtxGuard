"""Pivot analyzer for Success Correlation (Failure -> Exploration -> Eventual Success)."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
from ctxguard.learn.scanner import LogEvent


@dataclass
class PivotIncident:
    """Represents a discovered pivot point from failure to eventual success."""
    category: str              # "Path Corrections" | "Environment" | "Known Large Files" | "Command Patterns"
    wrong_attempt: str
    correct_solution: str
    rationale: str
    session_id: str = ""
    evidence_count: int = 1


class PivotAnalyzer:
    """Discovers critical pivot points where the Agent transitioned from failure to success.
    Implements CtxGuard Engine's core Success Correlation philosophy:
    'Capture the critical turning point rather than merely counting failure numbers.'
    """

    PYTHON_ERR_REGEX = re.compile(r"ModuleNotFoundError|No module named ['\"]?([a-zA-Z0-9_\-]+)['\"]?", re.IGNORECASE)
    FILE_ERR_REGEX = re.compile(r"(?:No such file|FileNotFoundError|cannot find the file|ENOENT)[:\s]*['\"]?([a-zA-Z0-9_\-\./\\]+)['\"]?", re.IGNORECASE)

    def analyze_events(self, events: List[LogEvent]) -> List[PivotIncident]:
        """Analyze normalized events and extract high-value pivot incidents."""
        pivots: List[PivotIncident] = []
        n = len(events)

        i = 0
        while i < n:
            ev = events[i]

            # 1. Check for User Rejection / Command Preference Pivot
            if ev.user_interrupt:
                # Look at previous assistant action
                prev_tool_action = ""
                for back_idx in range(i - 1, max(-1, i - 4), -1):
                    if events[back_idx].role == "assistant":
                        prev_tool_action = events[back_idx].tool_name
                        input_cmd = events[back_idx].tool_input.get("command") or events[back_idx].tool_input.get("cmd")
                        if input_cmd:
                            prev_tool_action = str(input_cmd)
                        break

                if prev_tool_action:
                    pivots.append(PivotIncident(
                        category="Command Patterns",
                        wrong_attempt=f"Auto-executing `{prev_tool_action}`",
                        correct_solution="Display command for manual user execution instead of running automatically",
                        rationale="User explicitly interrupted/rejected automated command execution.",
                        session_id=ev.session_id,
                    ))

            # 2. Check for Tool Error -> Subsequent Success Pivot
            elif ev.is_error:
                pivot = self._detect_error_recovery_pivot(events, error_idx=i)
                if pivot:
                    pivots.append(pivot)

            i += 1

        return self._deduplicate_pivots(pivots)

    def _detect_error_recovery_pivot(self, events: List[LogEvent], error_idx: int) -> Optional[PivotIncident]:
        """Inspect the forward window from error_idx to find the successful recovery action."""
        err_event = events[error_idx]
        output_text = err_event.output

        # Context: what tool call triggered this error?
        triggering_event: Optional[LogEvent] = None
        for b in range(error_idx - 1, max(-1, error_idx - 3), -1):
            if events[b].role == "assistant":
                triggering_event = events[b]
                break

        # A. Path Correction Pivot (FileNotFoundError)
        wrong_path = None
        if triggering_event and isinstance(triggering_event.tool_input, dict):
            wrong_path = triggering_event.tool_input.get("path") or triggering_event.tool_input.get("file_path")
        if not wrong_path and isinstance(err_event.tool_input, dict):
            wrong_path = err_event.tool_input.get("path") or err_event.tool_input.get("file_path")
        if not wrong_path:
            # Fallback to regex extraction
            clean_err = re.sub(r"FileNotFoundError:\s*No such file or directory:\s*", "FileNotFoundError: ", output_text, flags=re.I)
            file_match = self.FILE_ERR_REGEX.search(clean_err)
            if file_match:
                wrong_path = file_match.group(1).strip()

        if wrong_path:
            wrong_basename = Path(wrong_path).name
            # Look forward up to 8 steps for a successful Read/access of same or related file
            for f_idx in range(error_idx + 1, min(len(events), error_idx + 8)):
                cand = events[f_idx]
                if not cand.is_error and cand.role == "tool" and len(cand.output.strip()) > 10:
                    # Check candidate input
                    cand_input = cand.tool_input.get("path") or cand.tool_input.get("file_path") or ""
                    if not cand_input and f_idx > 0 and events[f_idx - 1].role == "assistant":
                        cand_input = events[f_idx - 1].tool_input.get("path") or events[f_idx - 1].tool_input.get("file_path") or ""

                    if cand_input and cand_input != wrong_path:
                        cand_basename = Path(cand_input).name
                        # If basenames match or share stem, this is a direct path correction!
                        if wrong_basename and (wrong_basename == cand_basename or Path(wrong_basename).stem == Path(cand_basename).stem):
                            return PivotIncident(
                                category="Path Corrections",
                                wrong_attempt=str(wrong_path),
                                correct_solution=str(cand_input),
                                rationale=f"Failed to find `{wrong_path}`, but successfully recovered and read from `{cand_input}`.",
                                session_id=err_event.session_id,
                            )

        # B. Environment Command Pivot (e.g. python3 -> uv run python, or npm -> pnpm)
        if "ModuleNotFoundError" in output_text or "command not found" in output_text.lower():
            # Triggering command
            wrong_cmd = ""
            if triggering_event:
                wrong_cmd = triggering_event.tool_input.get("command") or triggering_event.tool_input.get("cmd") or ""

            # Look forward for a command that succeeded
            for f_idx in range(error_idx + 1, min(len(events), error_idx + 8)):
                cand = events[f_idx]
                if not cand.is_error and cand.role == "tool" and "error" not in cand.output.lower():
                    success_cmd = ""
                    if f_idx > 0 and events[f_idx - 1].role == "assistant":
                        success_cmd = events[f_idx - 1].tool_input.get("command") or events[f_idx - 1].tool_input.get("cmd") or ""

                    if success_cmd and success_cmd != wrong_cmd:
                        return PivotIncident(
                            category="Environment",
                            wrong_attempt=str(wrong_cmd or "Default system runtime"),
                            correct_solution=str(success_cmd),
                            rationale="Command failed with missing dependencies or runtime mismatch, succeeded with project-configured environment runner.",
                            session_id=err_event.session_id,
                        )

        # C. Known Large Files Pivot
        if "too large" in output_text.lower() or "maximum line limit" in output_text.lower() or len(output_text) > 40000:
            target_file = wrong_path or "Target file"
            return PivotIncident(
                category="Known Large Files",
                wrong_attempt=f"Full-text read of `{target_file}`",
                correct_solution=f"Always read `{target_file}` using slice ranges, offset, or grep",
                rationale=f"Large file `{target_file}` caused token overflow or read truncation.",
                session_id=err_event.session_id,
            )

        return None

    def _deduplicate_pivots(self, pivots: List[PivotIncident]) -> List[PivotIncident]:
        """Aggregate identical pivot findings and increment evidence counts."""
        dedup_map: Dict[str, PivotIncident] = {}
        for p in pivots:
            key = f"{p.category}:{p.wrong_attempt}->{p.correct_solution}"
            if key in dedup_map:
                dedup_map[key].evidence_count += 1
            else:
                dedup_map[key] = p

        return list(dedup_map.values())
