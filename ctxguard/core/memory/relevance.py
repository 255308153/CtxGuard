"""Hybrid relevance scoring module for memory recall.

Combines BM25 / token-overlap keyword scoring with semantic relevance,
providing adaptive threshold gating to ensure zero-injection on irrelevant queries.

Recency handling mirrors headroom's ``memory_rank_policy``:
    factor = exp(-age_days / decay_days)      (None / future timestamp => 1.0)
    boosted = similarity * factor

Two properties of headroom's design are preserved deliberately:

1. **Decay ranks, it does not gate.** Headroom's ``MemoryRanker.rerank`` sorts by
   ``score × recency_factor`` and applies no threshold to the boosted value. Decay is
   therefore applied here as an ordering multiplier (``boosted_score``) and the
   injection gate (``should_inject``) stays a pure relevance test. Gating on decay
   would silently discard durable long-term preferences — precisely the memories the
   store exists to keep — once they pass a few decay constants.
2. **Missing and future timestamps are neutral (1.0).** A future timestamp usually
   means clock skew, and decaying it would push it *above* everything else.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Optional, Set

# Shared with the storage layer (ctxguard.storage.repository_graph.RECENCY_DECAY_DAYS).
# 30 days matches headroom's memory ranker default.
DEFAULT_DECAY_DAYS = 30.0


def recency_factor(
    created_at: Optional[Any],
    now: Optional[datetime] = None,
    decay_days: float = DEFAULT_DECAY_DAYS,
) -> float:
    """Recency multiplier for one memory candidate: ``exp(-age_days / decay_days)``.

    Returns 1.0 (recency-neutral) when the timestamp is absent, unparseable, or in the
    future, matching headroom's ``memory_recency_factor``.
    """
    if created_at is None:
        return 1.0

    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return 1.0
    if not isinstance(created_at, datetime):
        return 1.0

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    age_days = (now - created_at).total_seconds() / 86400.0
    if age_days <= 0 or decay_days <= 0:
        return 1.0
    return math.exp(-age_days / decay_days)


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

    def __init__(self, min_threshold: float = 0.25, decay_days: float = DEFAULT_DECAY_DAYS):
        self.min_threshold = min_threshold
        self.decay_days = decay_days

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
        """Compute hybrid relevance score between query and candidate text.

        This is pure text relevance — it carries no time component. See
        ``boosted_score`` for the recency-weighted variant used for ordering.
        """
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

    def boosted_score(
        self,
        query: str,
        candidate_text: str,
        created_at: Optional[Any] = None,
        now: Optional[datetime] = None,
    ) -> float:
        """``score × exp(-age_days / decay_days)`` — the ordering value.

        Mirrors headroom's ``boost_memory_score``. Used to decide *which* relevant
        memories make it into the injection budget when there are more candidates
        than room, never to decide *whether* memory is injected at all.
        """
        return self.score(query, candidate_text) * recency_factor(
            created_at, now=now, decay_days=self.decay_days
        )

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
        """Check if subgraph has any entity or relationship relevant to query.

        Intentionally does NOT apply recency decay: this is the injection gate, and
        decay is an ordering concern (see ``boosted_score``). Gating here would drop
        durable long-term preferences once they aged past a few decay constants.
        """
        if not subgraph:
            return False
        if not query:
            return False
        for entity in getattr(subgraph, "entities", []):
            if self.score(query, entity.name) >= self.min_threshold or self.score(query, entity.description or "") >= self.min_threshold:
                return True
        return False
