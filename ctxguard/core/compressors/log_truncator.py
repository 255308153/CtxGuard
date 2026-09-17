"""Log Truncator implementing global Head-Tail sliding window truncation for terminal/tool outputs."""

import re
from typing import Dict, List, Optional
from ctxguard.config.schema import LogCleanerConfig
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import Message, RequestContext
from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class LogTruncator(BaseCompressor):
    """Truncates ultra-long terminal and tool execution logs preserving head and tail lines."""

    CODE_BLOCK_REGEX = re.compile(
        r"(```([a-zA-Z0-9_\-\+]*)\n([\s\S]*?)```)",
        re.MULTILINE
    )

    def __init__(
        self,
        config: LogCleanerConfig,
        fingerprint_repo: Optional[FingerprintRepository] = None
    ):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.session_fingerprints: Dict[str, Dict[str, str]] = {}

    @property
    def name(self) -> str:
        return "log_truncator"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def compress_text(self, text: str) -> str:
        return self._compress_log_content(text, session_id="default")

    def _truncate_lines(self, lines: List[str], full_text: str, session_id: str) -> Optional[str]:
        total_lines = len(lines)
        max_lines = self.config.max_log_lines
        head = self.config.head_lines
        tail = self.config.tail_lines

        if total_lines <= max_lines or total_lines <= (head + tail):
            return None

        # Store in fingerprint repository for reversible retrieval
        sha = compute_sha256(full_text)
        short_sha = compute_short_fingerprint(full_text, length=12)

        if session_id not in self.session_fingerprints:
            self.session_fingerprints[session_id] = {}
        self.session_fingerprints[session_id][sha] = full_text
        self.session_fingerprints[session_id][short_sha] = full_text

        if self.fingerprint_repo:
            self.fingerprint_repo.save_fingerprint(sha, session_id, full_text)
            self.fingerprint_repo.save_fingerprint(short_sha, session_id, full_text)

        head_part = lines[:head]
        tail_part = lines[-tail:] if tail > 0 else []
        omitted = total_lines - head - tail

        folded_msg = f"[... CtxGuard: {omitted} lines omitted (head {head} / tail {tail}). Use ctx_expand('{short_sha}') for full output ...]"
        result_lines = head_part + [folded_msg] + tail_part
        return "\n".join(result_lines)

    def _compress_log_content(self, text: str, session_id: str = "default") -> str:
        if not text:
            return text

        lines = text.splitlines()
        # Fast path if total lines is small
        if len(lines) <= self.config.max_log_lines:
            return text

        # Case 1: Markdown code blocks
        if "```" in text:
            def replace_block(match: re.Match) -> str:
                full_block = match.group(1)
                lang = (match.group(2) or "").strip().lower()
                body = match.group(3)
                block_lines = body.splitlines()

                # Focus on logs, terminal output, text, bash, sh, stdout, stderr, or plain blocks
                log_langs = {"", "log", "bash", "sh", "zsh", "text", "txt", "output", "terminal", "console", "stdout", "stderr"}
                if lang in log_langs or len(block_lines) > self.config.max_log_lines * 2:
                    truncated = self._truncate_lines(block_lines, body, session_id=session_id)
                    if truncated:
                        return f"```{lang}\n{truncated}\n```"
                return full_block

            return self.CODE_BLOCK_REGEX.sub(replace_block, text)

        # Case 2: Plain text (e.g. raw tool output)
        truncated = self._truncate_lines(lines, text, session_id=session_id)
        if truncated:
            return truncated

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

            optimized = self._compress_log_content(text, session_id=session_id)
            if optimized != text:
                msg.set_text_content(optimized)
                if self.name not in context.applied_compressors:
                    context.applied_compressors.append(self.name)
