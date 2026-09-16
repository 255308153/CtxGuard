"""Git Diff Structural Compressor Operator for CtxGuard.

Folds unmodified context lines in unified diffs while preserving chunk headers
and modified lines (+ / -), allowing lossless recovery via ctx_expand virtual tool.
"""

import re
from typing import Dict, List, Optional
from ctxguard.config.schema import GitDiffCompressorConfig
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import Message, RequestContext
from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class GitDiffCompressor(BaseCompressor):
    """Compresses git unified diff context lines."""

    # Matches diff headers or hunk headers to identify diff content
    DIFF_HUNK_HEADER_REGEX = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
    DIFF_BLOCK_REGEX = re.compile(r"(```(?:diff|patch)?\n([\s\S]*?)```)", re.MULTILINE)

    def __init__(
        self,
        config: GitDiffCompressorConfig,
        fingerprint_repo: Optional[FingerprintRepository] = None,
    ):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.session_fingerprints: Dict[str, Dict[str, str]] = {}

    @property
    def name(self) -> str:
        return "git_diff_compressor"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def compress_text(self, text: str) -> str:
        return self._compress_diff_content(text, session_id="default")

    def _compress_hunk_lines(self, lines: List[str], short_sha: str) -> List[str]:
        """Compress consecutive unmodified context lines inside a hunk."""
        result: List[str] = []
        context_buf: List[str] = []
        max_ctx = self.config.max_context_lines

        def flush_context():
            nonlocal context_buf
            if not context_buf:
                return

            if len(context_buf) <= max_ctx * 2 + 1:
                result.extend(context_buf)
            else:
                # Keep leading max_ctx lines
                if max_ctx > 0:
                    result.extend(context_buf[:max_ctx])
                skipped = len(context_buf) - (2 * max_ctx if max_ctx > 0 else 0)
                result.append(f" ... ({skipped} context lines folded, ctx_expand({short_sha})) ...")
                # Keep trailing max_ctx lines
                if max_ctx > 0:
                    result.extend(context_buf[-max_ctx:])
            context_buf = []

        for line in lines:
            if line.startswith("@@"):
                flush_context()
                result.append(line)
            elif line.startswith("+") or line.startswith("-") or line.startswith("\\"):
                flush_context()
                result.append(line)
            elif line.startswith(" ") or line == "":
                context_buf.append(line)
            elif line.startswith("diff --git") or line.startswith("index ") or line.startswith("---") or line.startswith("+++"):
                flush_context()
                result.append(line)
            else:
                # Other lines (e.g. diff metadata or commit msg)
                flush_context()
                result.append(line)

        flush_context()
        return result

    def _is_diff_text(self, text: str) -> bool:
        """Heuristic check to determine if text looks like a unified diff."""
        has_diff_header = "diff --git" in text or ("--- " in text and "+++ " in text)
        has_hunk_header = False
        for line in text.splitlines()[:50]:
            if line.startswith("@@ -") and " @@" in line:
                has_hunk_header = True
                break
        return has_diff_header or has_hunk_header

    def _compress_diff_content(self, text: str, session_id: str = "default") -> str:
        if not text or len(text.splitlines()) < self.config.min_lines:
            return text

        if session_id not in self.session_fingerprints:
            self.session_fingerprints[session_id] = {}
        fingerprint_store = self.session_fingerprints[session_id]

        def process_raw_diff(raw_diff: str) -> Optional[str]:
            lines = raw_diff.splitlines()
            if len(lines) < self.config.min_lines or not self._is_diff_text(raw_diff):
                return None

            sha = compute_sha256(raw_diff)
            short_sha = compute_short_fingerprint(raw_diff, length=12)

            fingerprint_store[sha] = raw_diff
            fingerprint_store[short_sha] = raw_diff
            if self.fingerprint_repo:
                self.fingerprint_repo.save_fingerprint(sha, session_id, raw_diff)
                self.fingerprint_repo.save_fingerprint(short_sha, session_id, raw_diff)

            compressed_lines = self._compress_hunk_lines(lines, short_sha=short_sha)
            compressed_diff = "\n".join(compressed_lines)
            if len(compressed_diff) < len(raw_diff):
                return compressed_diff
            return None

        # Case 1: Code blocks (e.g., ```diff ... ``` or ```patch ... ``` or generic ``` ... ```)
        if "```" in text:
            def replace_block(match: re.Match) -> str:
                full_block = match.group(1)
                body = match.group(2)
                compressed = process_raw_diff(body)
                if compressed:
                    return f"```diff\n{compressed}\n```"
                return full_block

            return self.DIFF_BLOCK_REGEX.sub(replace_block, text)

        # Case 2: Entire text is a diff
        compressed = process_raw_diff(text)
        if compressed:
            return compressed

        return text

    def process(self, context: RequestContext, target_messages: List[Message]) -> None:
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"

        for msg in target_messages:
            if msg.role == "assistant":
                continue  # Never mutate assistant messages

            text = msg.get_text_content()
            if not text:
                continue

            optimized = self._compress_diff_content(text, session_id=session_id)
            if optimized != text:
                msg.set_text_content(optimized)
                if self.name not in context.applied_compressors:
                    context.applied_compressors.append(self.name)
