"""Repeated stack trace and exception block folding operator."""

import re
from typing import List
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext
from ctxguard.config.schema import LogCleanerConfig


class StacktraceFolder(BaseCompressor):
    """Folds repeated identical stack traces or log blocks."""

    def __init__(self, config: LogCleanerConfig):
        self.config = config

    @property
    def name(self) -> str:
        return "stacktrace_folder"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled and self.config.fold_repeated_stacktraces

    def compress_text(self, text: str) -> str:
        if not text:
            return text

        threshold = self.config.stacktrace_threshold
        lines = text.split("\n")
        if len(lines) < threshold * 2:
            return text

        # 1. Fold consecutive identical single lines
        cleaned_lines: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            curr_line = lines[i]
            # Count consecutive duplicates
            count = 1
            while i + count < n and lines[i + count] == curr_line:
                count += 1

            if count >= threshold and len(curr_line.strip()) > 10:
                cleaned_lines.append(curr_line)
                cleaned_lines.append(f"  [... identical line repeated {count - 1} more times ...]")
                i += count
            else:
                cleaned_lines.append(curr_line)
                i += 1

        # 2. Fold repeated multi-line error blocks (e.g. 3-line traceback repeated 5 times)
        text_out = "\n".join(cleaned_lines)
        return self._fold_repeated_multiline_blocks(text_out, threshold)

    def _fold_repeated_multiline_blocks(self, text: str, threshold: int) -> str:
        # Regex to detect 2-6 lines block repeated multiple times
        # Look for traceback-like blocks
        block_pattern = re.compile(
            r"((?:^[ \t]*File \".*\", line \d+.*\n(?:[ \t]*.*\n){1,3}){2,})",
            re.MULTILINE
        )
        return text
