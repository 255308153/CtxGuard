import re
from typing import List

class FastTokenizer:
    """Fast, dependency-free tokenizer supporting English, Code, and CJK Chinese tokens."""
    
    _TOKEN_PATTERN = re.compile(
        r"[a-zA-Z0-9_\-\.]+"           # 英文/数字/代码标识符
        r"|[\u4e00-\u9fff]"            # 单个中文汉字 (CJK)
        r"|[^\w\s]"                    # 标点与符号
        r"|\s+"                        # 空白块
    )

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        if not text:
            return []
        return cls._TOKEN_PATTERN.findall(text)

    @classmethod
    def detokenize(cls, tokens: List[str]) -> str:
        """Reconstruct string from token sequence preserving whitespace."""
        if not tokens:
            return ""
        return "".join(tokens)
