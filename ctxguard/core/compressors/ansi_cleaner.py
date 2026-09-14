"""Terminal ANSI color and cursor escape code cleaner."""

import re
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext
from ctxguard.config.schema import LogCleanerConfig


class ANSICleaner(BaseCompressor):
    """Strip ANSI escape sequences, color codes, and cursor movement commands."""

    # Matches ANSI escape sequences (colors, cursor control, OSC codes)
    ANSI_REGEX = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def __init__(self, config: LogCleanerConfig):
        self.config = config

    @property
    def name(self) -> str:
        return "ansi_cleaner"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled and self.config.strip_ansi

    def compress_text(self, text: str) -> str:
        if not text or "\x1b" not in text and "\033" not in text:
            return text
        return self.ANSI_REGEX.sub("", text)
