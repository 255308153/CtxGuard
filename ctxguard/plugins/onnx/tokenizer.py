"""Fast, zero-heavy-dependency tokenizer and word segmenter."""

import re
from typing import List, Tuple


class FastTokenizer:
    """Regex-based high-speed tokenizer splitting words, punctuation, and CJK characters."""

    # Matches word tokens, CJK characters, whitespace sequences, and individual punctuation
    TOKEN_REGEX = re.compile(
        r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]"  # Single CJK character
        r"|[a-zA-Z0-9_\-\.]+"                          # Alphanumeric words/identifiers
        r"|\s+"                                         # Whitespace sequences
        r"|[^\s\w]"                                     # Individual punctuation / symbols
    )

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """Split string into token list preserving full text upon join."""
        if not text:
            return []
        return cls.TOKEN_REGEX.findall(text)

    @classmethod
    def detokenize(cls, tokens: List[str]) -> str:
        """Reconstruct original text from token list."""
        return "".join(tokens)
