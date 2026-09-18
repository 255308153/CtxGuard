"""Multi-turn context tracking and proactive recall for CtxGuard.

Tamed ContextTracker implementation aligned with Headroom CCR architecture:
1. Ingress Gatekeeper: Discard Claude Code /compact and continuation summaries.
2. Scope Gatekeeper: Fail-closed workspace and session scoping to prevent cross-project leaks.
3. Lifecycle & LRU: Strict 300s (5-min) TTL half-life decay with LRU eviction.
4. Comprehensive Lexical Heuristics: 100+ stop-words + exact symbol bonuses + tool intent boost.
5. Escaping & Provenance: Safe XML formatting, boundary escaping, and length capping.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# Content signatures that should never be proactively expanded back into user prompt
BLOCKED_CONTENT_SIGNATURES: List[str] = [
    "<!-- CTXGUARD_AUTO_RULES",
    "<!-- headroom:learn",
    "Do not repeatedly execute incremental paging queries",
    "Discovered Pivots:",
    "[DRY RUN PREVIEW]",
    "Discovered and synthesized",
    "Relevant context automatically restored by CtxGuard",
    "<proactive_context_expansion",
    "<headroom_proactive_expansion",
]


def looks_like_compact_or_continuation_summary(*texts: Optional[str]) -> bool:
    """Return true for Claude Code /compact, continuation summaries, or auto-rule dumps.

    Tracking these for proactive expansion leads to recursive prompt bloat and context poisoning.
    Aligned with Headroom's looks_like_claude_code_compact_summary gatekeeper.
    """
    combined = " ".join(t.strip() for t in texts if t and t.strip())
    if not combined:
        return False

    # Check explicit blocked signatures first
    for sig in BLOCKED_CONTENT_SIGNATURES:
        if sig in combined:
            return True

    normalized = " ".join(combined.lower().split())
    has_summary = "summary" in normalized or "summarized" in normalized or "总结" in normalized

    if "this session is being continued from a previous conversation" in normalized and has_summary:
        return True

    if "conversation is summarized below" in normalized and (
        "ran out of context" in normalized or "previous conversation" in normalized
    ):
        return True

    if (
        "/compact" in normalized
        and ("claude" in normalized or "session" in normalized)
        and has_summary
    ):
        return True

    return False


@dataclass
class CompressedContext:
    hash_key: str              # 指纹 short_sha
    session_id: str            # 会话 ID
    turn_number: int           # 产生压缩的轮次
    timestamp: float           # 产生时间（用于时间衰减）
    tool_name: Optional[str]   # 关联工具（如 read, bash）
    sample_content: str        # 截断预览（提取关键字用，限制在 1000 字符内）
    keywords: Set[str]         # 提取的符号/函数名/错误标识符
    workspace_key: str = ""    # 跨项目/工作区物理隔离键


@dataclass
class ExpansionRecommendation:
    hash_key: str
    relevance_score: float
    reason: str


class ContextTracker:
    # Comprehensive stop-word vocabulary combining Headroom's 78 natural language stop words
    # and CtxGuard's platform/agent vocabulary to prevent false positive triggers
    STOP_WORDS: Set[str] = {
        # Natural language grammatical words (aligned with Headroom 78 stop-words)
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
        "from", "as", "into", "through", "during", "before", "after", "above",
        "below", "between", "under", "again", "further", "then", "once", "here",
        "there", "when", "where", "why", "how", "all", "each", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "and", "but", "if", "or",
        "because", "until", "while", "this", "that", "these", "those", "what",
        "which", "who", "whom", "it", "its", "me", "my", "your", "them", "their",
        # Language keywords
        "def", "class", "import", "from", "return", "self", "none", "true", "false",
        "async", "await", "with", "open", "read", "write", "file", "error", "line",
        "code", "type",
        # Agent & Platform vocabulary (anti-false-positive guards)
        "agent", "macos", "linux", "windows", "bash", "shell", "zsh", "terminal",
        "codex", "claude", "gemini", "piweb", "pi-web", "ctxguard", "prompt",
        "message", "user", "assistant", "query", "tool", "test", "help", "info",
        "apply", "learn", "auto", "rule", "rules", "context", "expansion", "output",
    }

    def __init__(
        self,
        max_contexts: int = 100,
        relevance_threshold: float = 0.35,
        max_content_chars: int = 1200,
        max_context_age_seconds: float = 300.0,
        blocked_keywords: Optional[List[str]] = None,
    ):
        self._contexts: Dict[str, CompressedContext] = {}
        self._turn_order: List[str] = []  # LRU eviction queue
        self.max_contexts = max_contexts
        self.relevance_threshold = relevance_threshold
        self.max_content_chars = max_content_chars
        self.max_context_age_seconds = max_context_age_seconds
        self.blocked_keywords = set(blocked_keywords or [])
        self._current_turn: int = 0

    def track(
        self,
        hash_key: str,
        session_id: str,
        sample_content: str,
        tool_name: Optional[str] = None,
        workspace_key: str = "",
    ) -> None:
        """当任何压缩器将内容折叠存入指纹库时调用。
        
        对齐 Headroom:
        1. 摘要拦截 (looks_like_compact_or_continuation_summary)
        2. LRU 容量控制 (超额剔除最旧指纹)
        3. 样本截断 (:1000)
        """
        # Block tracking CLI dumps, summaries, or auto-rules to prevent recursive spam
        if looks_like_compact_or_continuation_summary(sample_content):
            logger.debug(f"[ContextTracker] Skipped tracking continuation/summary for hash {hash_key}")
            return

        keywords = self._extract_keywords(sample_content)
        if self.blocked_keywords:
            keywords = {k for k in keywords if k not in self.blocked_keywords}

        self._current_turn += 1
        ctx = CompressedContext(
            hash_key=hash_key,
            session_id=session_id,
            turn_number=self._current_turn,
            timestamp=time.time(),
            tool_name=tool_name,
            sample_content=sample_content[:1000],
            keywords=keywords,
            workspace_key=workspace_key,
        )

        if hash_key in self._contexts:
            if hash_key in self._turn_order:
                self._turn_order.remove(hash_key)
        self._contexts[hash_key] = ctx
        self._turn_order.append(hash_key)

        # LRU eviction
        while len(self._contexts) > self.max_contexts and self._turn_order:
            oldest = self._turn_order.pop(0)
            self._contexts.pop(oldest, None)

    def _extract_keywords(self, text: str) -> Set[str]:
        """Extract meaningful alphanumeric tokens, identifiers, and sub-tokens."""
        if not text:
            return set()
        tokens = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_-]{2,}\b|\b[a-zA-Z]{3,}\b", text)
        result: Set[str] = set()
        for t in tokens:
            tl = t.lower()
            if tl not in self.STOP_WORDS and len(tl) >= 4:
                result.add(tl)
            if "_" in t or "-" in t:
                for sub in re.split(r"[_-]", t):
                    subl = sub.lower()
                    if subl not in self.STOP_WORDS and len(subl) >= 4:
                        result.add(subl)
        return result

    def analyze_query(
        self,
        query: str,
        session_id: str,
        workspace_key: str = "",
        max_expansions: int = 2,
    ) -> List[ExpansionRecommendation]:
        """在新一轮用户消息或工具输入到达时计算相关度。

        防线体系：
        1. Fail-Closed 隔离：若既无 session_id 也无 workspace_key，直接返回 []。
        2. 作用域隔离：session 与 workspace 必须严格匹配。
        3. 5 分钟 TTL 淘汰：超过 max_context_age_seconds 直接丢弃。
        4. 半衰时间折扣：age_factor = 1.0 - (age / max_age) * 0.5。
        5. 多维打分：关键词重合 (0.5) + 子串精准命中 (+0.2) + 工具意图协同 (+0.1)。
        """
        # Fail-closed: require at least one scoped identity
        if not session_id and not workspace_key:
            return []

        query_words = self._extract_keywords(query.lower())
        if not query_words or len(query_words) < 2:
            return []

        recommendations: List[ExpansionRecommendation] = []
        now = time.time()

        for hash_key, ctx in self._contexts.items():
            # Workspace filter: cross-project leak gate
            if workspace_key and ctx.workspace_key and ctx.workspace_key != workspace_key:
                continue

            # Session filter: cross-session isolation
            if session_id and ctx.session_id and ctx.session_id != session_id:
                continue

            # Check age: strict TTL eviction
            age = now - ctx.timestamp
            if age > self.max_context_age_seconds:
                continue

            # 1. Keyword overlap with sample content (weight 0.5)
            overlap = query_words & ctx.keywords
            score = 0.0
            if overlap:
                score += (len(overlap) / len(query_words)) * 0.5

            # 2. Exact substring matches in sample content (bonus +0.25)
            sample_lower = ctx.sample_content.lower()
            for word in query_words:
                if len(word) >= 4 and word in sample_lower:
                    score += 0.25
                    break

            # 3. Tool name intent bonus (+0.1)
            if ctx.tool_name:
                tool_lower = ctx.tool_name.lower()
                if any(w in tool_lower for w in ["find", "glob", "search", "grep", "ls", "read"]):
                    if any(w in query.lower() for w in ["file", "where", "find", "show", "list", "code"]):
                        score += 0.1

            if score <= 0.0:
                continue

            # 4. Age half-life discount (older contexts get lower scores)
            age_factor = max(0.2, 1.0 - (age / self.max_context_age_seconds) * 0.5)
            final_score = min(1.0, score * age_factor)

            if final_score >= self.relevance_threshold:
                matched_tokens = list(overlap)[:3] if overlap else [w for w in query_words if w in sample_lower][:2]
                recommendations.append(
                    ExpansionRecommendation(
                        hash_key=hash_key,
                        relevance_score=final_score,
                        reason=f"Matched tokens {matched_tokens}",
                    )
                )

        recommendations.sort(key=lambda x: x.relevance_score, reverse=True)
        return recommendations[:max_expansions]

    def format_proactive_expansion(
        self,
        expansions: List[Dict[str, Any]],
        session_id: str = "",
        workspace_key: str = "",
    ) -> str:
        """将从 SQLite 读取的原始内容格式化为对模型友好的 XML 块，并严格限制最大长度与转义防逃逸。"""
        if not expansions:
            return ""

        header_info = "Relevant context automatically restored by CtxGuard"
        if workspace_key:
            header_info += f" | workspace: {workspace_key}"
        elif session_id:
            header_info += f" | session: {session_id}"

        parts = [f"<proactive_context_expansion note='{header_info}'>"]
        for exp in expansions:
            content = str(exp.get("content", ""))
            # Tag boundary escaping to prevent prompt escaping/injection
            content = content.replace("</proactive_context_expansion>", "<\\/proactive_context_expansion>")
            content = content.replace("</headroom_proactive_expansion>", "<\\/headroom_proactive_expansion>")

            # Apply strict bounding cap to prevent prompt flooding
            if len(content) > self.max_content_chars:
                content = (
                    content[: self.max_content_chars]
                    + "\n... [Restored content truncated by CtxGuard to prevent context bloat]"
                )
            parts.append(
                f"\n--- [Restored Content: {exp['hash']} | Reason: {exp.get('reason', 'relevance')}] ---"
            )
            parts.append(content)
        parts.append("</proactive_context_expansion>")
        return "\n".join(parts)

    def clear(self) -> None:
        """Clear all tracked contexts."""
        self._contexts.clear()
        self._turn_order.clear()
        self._current_turn = 0


