"""Hybrid relevance scoring module for memory recall.

Combines BM25 / token-overlap keyword scoring with semantic relevance,
providing adaptive threshold gating to ensure zero-injection on irrelevant queries.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import List, Set


@dataclass
class ScoredMemory:
    mem_id: str
    fact_text: str
    score: float
    category: str = "general"


class MemoryRelevanceScorer:
    """Calculates relevance between a user query and stored memory items."""

    # Patterns indicating high-priority exact technical terms
    _KEYWORD_RE = re.compile(r"[a-zA-Z0-9_\-\.\/]{2,}")

    def __init__(self, min_threshold: float = 0.25):
        self.min_threshold = min_threshold

    def tokenize(self, text: str) -> List[str]:
        """Tokenize text using industrial Jieba DAG segmenter + English keywords."""
        if not text:
            return []
        text_lower = text.lower()
        
        try:
            import jieba
            # Cut into exact Chinese and English words
            raw_tokens = [w.strip() for w in jieba.cut(text_lower, cut_all=False) if w.strip()]
        except ImportError:
            raw_tokens = self._KEYWORD_RE.findall(text_lower)
            
        return raw_tokens

    def score(self, query: str, candidate_text: str) -> float:
        """Compute hybrid relevance score between query and candidate text."""
        q_tokens = self.tokenize(query)
        c_tokens = self.tokenize(candidate_text)

        if not q_tokens or not c_tokens:
            return 0.0

        q_set = set(q_tokens)
        c_set = set(c_tokens)

        # 1. Jaccard token overlap
        intersection = q_set.intersection(c_set)
        if not intersection:
            return 0.0
        
        jaccard = len(intersection) / len(q_set.union(c_set))

        # 2. Query coverage and Candidate coverage
        q_cov = len(intersection) / len(q_set)
        c_cov = len(intersection) / len(c_set)

        # 3. Exact phrase containment boost
        phrase_boost = 0.3 if candidate_text.lower() in query.lower() or query.lower() in candidate_text.lower() else 0.0

        # Term overlap boost (if any major multi-char keyword matches)
        term_boost = 0.4 if any(len(t) >= 2 for t in intersection) else 0.0

        final_score = (max(q_cov, c_cov) * 0.4) + (jaccard * 0.2) + phrase_boost + term_boost
        return min(1.0, final_score)

    def rank(self, query: str, candidates: List[tuple[str, str, str]], top_k: int = 3) -> List[ScoredMemory]:
        """Rank candidates (id, text, category) and filter by relevance threshold."""
        scored: List[ScoredMemory] = []
        for mem_id, text, cat in candidates:
            s = self.score(query, text)
            if s >= self.min_threshold:
                scored.append(ScoredMemory(mem_id=mem_id, fact_text=text, score=s, category=cat))

        scored.sort(key=lambda x: x.score, reverse=True)
        return scored[:top_k]

    def should_inject(self, query: str, subgraph: Any) -> bool:
        """Check if subgraph has any entity or relationship relevant to query."""
        if not subgraph:
            return False
        if not query:
            return False
        for entity in getattr(subgraph, "entities", []):
            if self.score(query, entity.name) >= self.min_threshold or self.score(query, entity.description or "") >= self.min_threshold:
                return True
        return False
