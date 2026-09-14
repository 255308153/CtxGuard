"""Ultra-fast heuristic and exact token counting utilities."""

import re
from typing import Any, Dict, List, Union


def estimate_tokens_from_text(text: str) -> int:
    """Estimate token count from text with high speed (<0.1ms).

    Heuristic rule:
    - English/code: approx 1 token per 3.8 ~ 4 characters, plus punctuation
    - CJK (Chinese, Japanese, Korean): approx 1.5 tokens per CJK char
    """
    if not text:
        return 0

    cjk_count = len(re.findall(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]', text))
    non_cjk_len = len(text) - cjk_count

    # Words & whitespaces approximation
    estimated = int(non_cjk_len / 3.8) + int(cjk_count * 1.5)
    return max(1, estimated)


def estimate_tokens_from_payload(payload: Union[Dict[str, Any], List[Any], str]) -> int:
    """Estimate tokens for structured JSON payload or messages list."""
    if isinstance(payload, str):
        return estimate_tokens_from_text(payload)

    total = 0
    if isinstance(payload, dict):
        # Scan messages if present
        messages = payload.get("messages", [])
        if isinstance(messages, list):
            for msg in messages:
                if isinstance(msg, dict):
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total += estimate_tokens_from_text(content) + 4
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                total += estimate_tokens_from_text(str(block["text"])) + 4
        # Scan system if present (Anthropic top-level system)
        system = payload.get("system", "")
        if isinstance(system, str):
            total += estimate_tokens_from_text(system) + 4
    elif isinstance(payload, list):
        for item in payload:
            total += estimate_tokens_from_payload(item)

    return total if total > 0 else 1
