import re
from typing import List

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

class FastTokenizer:
    """Industrial-grade hybrid tokenizer with DAG Chinese segmentation and code safety."""
    
    _CODE_FALLBACK_PATTERN = re.compile(
        r"[a-zA-Z0-9_\-\.]+|[\u4e00-\u9fff]|[^\w\s]|\s+"
    )

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        if not text:
            return []
        if _HAS_JIEBA:
            # Precise mode: splits Chinese into accurate words while keeping symbols & English
            return list(jieba.cut(text, cut_all=False))
        return cls._CODE_FALLBACK_PATTERN.findall(text)

    @classmethod
    def detokenize(cls, tokens: List[str]) -> str:
        """Reconstruct string from token sequence preserving original layout."""
        if not tokens:
            return ""
        return "".join(tokens)
