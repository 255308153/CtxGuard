"""Progress bar merger to collapse intermediate download/build progress frames."""

import re
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext
from ctxguard.config.schema import LogCleanerConfig


class ProgressMerger(BaseCompressor):
    """Collapses multi-frame terminal progress bars, keeping only the final state."""

    # Matches carriage-return overwrite lines common in CLI progress bars
    CR_LINE_REGEX = re.compile(r"(?:[^\r\n]*\r)+([^\r\n]+)")
    # Matches common progress bar patterns like [===>    ] 45% or 45% [=====>]
    PROGRESS_PATTERN = re.compile(r"(\[[\=\>\#\-\.\s]{5,}\]\s*\d+(?:\.\d+)?%|\d+(?:\.\d+)?%\s*\[[\=\>\#\-\.\s]{5,}\])")

    def __init__(self, config: LogCleanerConfig):
        self.config = config

    @property
    def name(self) -> str:
        return "progress_merger"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled and self.config.merge_progress_bars

    def compress_text(self, text: str) -> str:
        if not text:
            return text

        # 1. Handle \r overwrites
        if "\r" in text:
            text = self.CR_LINE_REGEX.sub(r"\1", text)
            text = text.replace("\r", "\n")

        # 2. Collapse consecutive progress bar lines
        lines = text.split("\n")
        if len(lines) < 2:
            return text

        cleaned_lines = []
        consecutive_progress_group = []

        for line in lines:
            if self.PROGRESS_PATTERN.search(line):
                consecutive_progress_group.append(line)
            else:
                if consecutive_progress_group:
                    # Keep only the last progress line
                    cleaned_lines.append(consecutive_progress_group[-1])
                    consecutive_progress_group = []
                cleaned_lines.append(line)

        if consecutive_progress_group:
            cleaned_lines.append(consecutive_progress_group[-1])

        return "\n".join(cleaned_lines)
