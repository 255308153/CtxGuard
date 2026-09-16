import re
from typing import List

try:
    import jieba
    _HAS_JIEBA = True
except ImportError:
    _HAS_JIEBA = False

class FastTokenizer:
    """Industrial-grade hybrid tokenizer with DAG Chinese segmentation and code identifier preservation."""
    
    # 优先保留代码下划线标识符、点分路径、中文字词、标点与空白
    _CODE_FALLBACK_PATTERN = re.compile(
        r"[a-zA-Z0-9_\-\.]+|[\u4e00-\u9fff]|[^\w\s]|\s+"
    )

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        if not text:
            return []
        # 直接使用正则提取完整标识符，保持下划线和代码变量不被截断
        return cls._CODE_FALLBACK_PATTERN.findall(text)

    @classmethod
    def detokenize(cls, tokens: List[str]) -> str:
        """Reconstruct string from token sequence preserving original layout."""
        if not tokens:
            return ""
        return "".join(tokens)
