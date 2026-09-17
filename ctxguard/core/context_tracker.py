import re
# 核心数据结构与契约
from dataclasses import dataclass
import time
from typing import List, Dict, Optional, Set

@dataclass
class CompressedContext:
    hash_key: str              # 指纹 short_sha
    session_id: str            # 会话 ID
    turn_number: int           # 产生压缩的轮次
    timestamp: float           # 产生时间（用于时间衰减）
    tool_name: Optional[str]   # 关联工具（如 read, bash）
    sample_content: str        # 前 1000 字符预览（提取关键字用）
    keywords: Set[str]         # 提取的符号/函数名/错误标识符

@dataclass
class ExpansionRecommendation:
    hash_key: str
    relevance_score: float
    reason: str

class ContextTracker:
    def __init__(self, max_contexts: int = 150, relevance_threshold: float = 0.30):
        self._contexts: Dict[str, CompressedContext] = {}  # hash_key -> context
        self.max_contexts = max_contexts
        self.relevance_threshold = relevance_threshold

    def track(self, hash_key: str, session_id: str, sample_content: str, tool_name: Optional[str] = None):
        """当任何压缩器（ast_code, log_truncator, dedup）将内容折叠存入指纹库时调用"""
        keywords = self._extract_keywords(sample_content)
        self._contexts[hash_key] = CompressedContext(
            hash_key=hash_key,
            session_id=session_id,
            turn_number=len(self._contexts) + 1,
            timestamp=time.time(),
            tool_name=tool_name,
            sample_content=sample_content[:1000],
            keywords=keywords,
        )
        # 执行 LRU 淘汰...


    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract relevant identifiers, function/file names, and error tokens."""
        if not text:
            return set()
        # Match alphanumeric tokens and underscores (e.g., function_name, ErrorType, variable_1)
        tokens = re.findall(r'[a-zA-Z_][a-zA-Z0-9_-]{2,}', text)
        # Filter out common stop words / code syntax noise
        stop_words = {
            'def', 'class', 'import', 'from', 'return', 'self', 'none', 'true', 'false',
            'async', 'await', 'with', 'open', 'read', 'write', 'file', 'this', 'that',
            'have', 'will', 'your', 'what', 'here', 'error', 'line', 'code', 'type'
        }
        return {t.lower() for t in tokens if t.lower() not in stop_words and len(t) >= 3}

    def analyze_query(self, query: str, session_id: str, max_expansions: int = 2) -> List[ExpansionRecommendation]:
        """在新一轮用户消息或工具输入到达时计算相关度"""
        query_words = self._extract_keywords(query.lower())
        if not query_words:
            return []

        recommendations = []
        now = time.time()
        for hash_key, ctx in self._contexts.items():
            if ctx.session_id != session_id:
                continue

            # 1. 关键词交集与符号重合度（权重 0.6）
            overlap = query_words & ctx.keywords
            score = (len(overlap) / len(query_words)) * 0.6

            # 2. 精确子串命中（如用户提到了某个特定的函数名、文件名或报错代码，+0.3）
            for word in query_words:
                if len(word) >= 4 and word in ctx.sample_content.lower():
                    score += 0.3
                    break

            # 3. 半衰期衰减：越靠近当前轮次权重越高
            age = now - ctx.timestamp
            decay = max(0.4, 1.0 - (age / 600.0) * 0.6)
            final_score = score * decay

            if final_score >= self.relevance_threshold:
                recommendations.append(ExpansionRecommendation(
                    hash_key=hash_key,
                    relevance_score=final_score,
                    reason=f"Matched keywords {list(overlap)[:3]}",
                ))

        recommendations.sort(key=lambda x: x.relevance_score, reverse=True)
        return recommendations[:max_expansions]

    def format_proactive_expansion(self, expansions: List[Dict[str, str]]) -> str:
        """将从 SQLite 读取的原始内容格式化为对模型友好的 XML 块"""
        if not expansions:
            return ""
        parts = ["<proactive_context_expansion note='Relevant context automatically restored by CtxGuard'>"]
        for exp in expansions:
            parts.append(f"\n--- [Restored Content: {exp['hash']} | Reason: {exp['reason']}] ---")
            parts.append(exp["content"])
        parts.append("</proactive_context_expansion>")
        return "\n".join(parts)

