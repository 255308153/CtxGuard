"""Whitespace and blank line compacting compressor."""

import re
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext


class WhitespaceCleaner(BaseCompressor):
    """Compacts excessive blank lines and trailing whitespace without breaking code indentation."""

    CONSECUTIVE_BLANKS = re.compile(r"\n{3,}")
    TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)

    @property
    def name(self) -> str:
        return "whitespace_cleaner"

    def is_applicable(self, context: RequestContext) -> bool:
        return True

    def compress_text(self, text: str) -> str:
        if not text:
            return text
        # Remove trailing spaces
        text = self.TRAILING_SPACES.sub("", text)
        # Collapse 3+ consecutive newlines into max 2
        text = self.CONSECUTIVE_BLANKS.sub("\n\n", text)
        return text
