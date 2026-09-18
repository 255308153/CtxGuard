"""Semantic cache engine for query-level response reuse.

Inspired by CtxGuard Engine's semantic cache and the lessons in 06-语义缓存:
1. Slashes entire LLM invocations (100% token savings, single-digit ms latency).
2. Dual-track lookup: Exact full-context SHA-256 hash first, followed by Cosine Semantic similarity.
3. Conservative threshold (0.95) to prevent catastrophic false-positive answers.
4. Empty Query Guard: Never semantically match empty query turns (e.g. tool results).
5. O(1) LRU eviction via OrderedDict and 5-minute TTL cleanup.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from ctxguard.config.schema import SemanticCacheConfig


@dataclass
class CacheEntry:
    """Entry stored in the semantic cache."""
    query: str
    response_body: bytes
    response_headers: Dict[str, str]
    embedding: List[float]
    messages_hash: str
    raw_tokens: int = 0
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    hit_count: int = 1


class LightweightEmbedder:
    """Ultra-fast, zero-dependency 384-dimensional hashed n-gram embedding vectorizer.
    Runs entirely in pure Python in < 0.1ms with zero network or heavy ML dependencies.
    """

    STOP_WORDS = frozenset({
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by", "from",
        "is", "are", "was", "were", "be", "been", "do", "does", "did", "have", "has", "had",
        "can", "could", "will", "would", "should", "may", "might", "must",
        "i", "you", "he", "she", "it", "we", "they", "my", "your", "his", "her", "its", "our", "their",
        "me", "him", "us", "them", "this", "that", "these", "those",
        "please", "tell", "show", "give", "how", "what", "where", "when", "why", "who",
        "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这", "请", "问", "帮我",
    })

    def __init__(self, dim: int = 384):
        self.dim = dim

    def embed(self, text: str) -> List[float]:
        """Convert input text into an L2-normalized 384-dimensional feature vector.
        Content words receive heavy weighting while grammatical stop words receive minimal weight.
        """
        if not text or not text.strip():
            return [0.0] * self.dim

        vec = [0.0] * self.dim
        clean = text.lower().strip()

        # Tokenize words, stripping punctuation
        raw_words = [re.sub(r"[^\w]", "", w) for w in clean.split()]
        words = [w for w in raw_words if w]
        content_words = [w for w in words if w not in self.STOP_WORDS]

        # If all words are stop words, fallback to raw words
        if not content_words:
            content_words = words

        # 1. Content word unigrams
        for w in content_words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[h] += 5.0

        # 2. Content word bigrams
        for i in range(len(content_words) - 1):
            bigram = f"{content_words[i]}_{content_words[i+1]}"
            h = int(hashlib.md5(bigram.encode("utf-8")).hexdigest(), 16) % self.dim
            vec[h] += 4.0

        # 3. Substring character trigrams of content words (for typo resilience)
        for w in content_words:
            for i in range(len(w) - 2):
                tri = w[i:i+3]
                h = int(hashlib.sha256(tri.encode("utf-8")).hexdigest(), 16) % self.dim
                vec[h] += 1.5

        # 4. Light signal from all words for structure
        for w in words:
            if w in self.STOP_WORDS:
                h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16) % self.dim
                vec[h] += 0.2

        # 5. L2 Normalization so dot product equals cosine similarity
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            vec = [x / norm for x in vec]

        return vec


def compute_context_hash(messages: List[Any], model: str, system: Optional[str] = None) -> str:
    """Compute deterministic SHA-256 hash across all conversation messages, model, and system prompt."""
    hasher = hashlib.sha256()
    hasher.update(model.encode("utf-8"))
    if system:
        hasher.update(b"|sys:")
        hasher.update(system.encode("utf-8"))

    for m in messages:
        if isinstance(m, dict):
            role = str(m.get("role", ""))
            content = str(m.get("content", ""))
        else:
            role = str(getattr(m, "role", ""))
            content = str(getattr(m, "content", ""))
        hasher.update(f"|{role}:{content}".encode("utf-8"))

    return hasher.hexdigest()


class SemanticCache:
    """High-performance in-memory semantic cache with LRU eviction and TTL management."""

    def __init__(
        self,
        config: Optional[SemanticCacheConfig] = None,
        embedder: Optional[LightweightEmbedder] = None,
    ):
        self.config = config or SemanticCacheConfig()
        self.embedder = embedder or LightweightEmbedder()

        # LRU cache: key -> CacheEntry
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        # Fast exact hash index: messages_hash -> key
        self._hash_index: Dict[str, str] = {}

        # Stats
        self._exact_hits: int = 0
        self._semantic_hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

    def _cleanup_expired(self) -> None:
        """Remove entries that have exceeded TTL."""
        if self.config.ttl_seconds <= 0:
            return

        now = time.time()
        expired_keys = []
        for key, entry in self._cache.items():
            if now - entry.created_at > self.config.ttl_seconds:
                expired_keys.append(key)
            else:
                break  # Insertion ordered, oldest first

        for k in expired_keys:
            entry = self._cache.pop(k, None)
            if entry and entry.messages_hash in self._hash_index:
                del self._hash_index[entry.messages_hash]
            self._evictions += 1

    def _touch(self, key: str) -> None:
        """Move key to the end of OrderedDict (most recently accessed)."""
        if key in self._cache:
            entry = self._cache[key]
            entry.last_accessed = time.time()
            self._cache.move_to_end(key)

    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate dot product of two L2-normalized vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        return float(sum(x * y for x, y in zip(a, b)))

    def get(
        self,
        query: str,
        messages: List[Any],
        model: str,
        system: Optional[str] = None,
    ) -> Optional[Tuple[CacheEntry, float, str]]:
        """Look up cached response. Returns (entry, similarity, hit_type) or None."""
        if not self.config.enabled:
            return None

        self._cleanup_expired()
        ctx_hash = compute_context_hash(messages, model, system)

        # 1. Exact Hash Match (O(1))
        if self.config.use_exact_matching and ctx_hash in self._hash_index:
            key = self._hash_index[ctx_hash]
            if key in self._cache:
                entry = self._cache[key]
                if entry.messages_hash == ctx_hash:
                    self._touch(key)
                    entry.hit_count += 1
                    self._exact_hits += 1
                    return entry, 1.0, "exact"

        # 2. Semantic Similarity Match
        # CRITICAL LESSON from 06-语义缓存:
        # If query is blank/whitespace (e.g. tool continuation turn), DO NOT match semantically!
        # An empty query would produce fixed non-zero embedding and falsely hit unrelated conversations.
        clean_query = query.strip()
        if clean_query:
            query_emb = self.embedder.embed(clean_query)
            best_key: Optional[str] = None
            best_sim = -1.0

            for key, entry in self._cache.items():
                if not entry.embedding:
                    continue
                sim = self._cosine_similarity(query_emb, entry.embedding)
                if sim > best_sim:
                    best_sim = sim
                    best_key = key

            if best_key and best_sim >= self.config.similarity_threshold:
                entry = self._cache[best_key]
                self._touch(best_key)
                entry.hit_count += 1
                self._semantic_hits += 1
                return entry, best_sim, "semantic"

        self._misses += 1
        return None

    def put(
        self,
        query: str,
        messages: List[Any],
        model: str,
        response_body: bytes,
        response_headers: Optional[Dict[str, str]] = None,
        raw_tokens: int = 0,
        system: Optional[str] = None,
    ) -> str:
        """Store response in semantic cache with LRU eviction and TTL."""
        if not self.config.enabled or not response_body:
            return ""

        self._cleanup_expired()
        ctx_hash = compute_context_hash(messages, model, system)
        key = ctx_hash

        # LRU eviction if at capacity
        while key not in self._cache and len(self._cache) >= self.config.max_entries:
            oldest_key, oldest_entry = self._cache.popitem(last=False)
            if oldest_entry.messages_hash in self._hash_index:
                del self._hash_index[oldest_entry.messages_hash]
            self._evictions += 1

        clean_query = query.strip()
        embedding: List[float] = []
        if clean_query:
            embedding = self.embedder.embed(clean_query)

        now = time.time()
        entry = CacheEntry(
            query=query,
            response_body=response_body,
            response_headers=response_headers or {},
            embedding=embedding,
            messages_hash=ctx_hash,
            raw_tokens=raw_tokens,
            created_at=now,
            last_accessed=now,
        )

        self._cache[key] = entry
        self._hash_index[ctx_hash] = key
        return key

    def get_stats(self) -> Dict[str, Any]:
        """Get telemetry metrics for semantic cache."""
        total_hits = self._exact_hits + self._semantic_hits
        total_lookups = total_hits + self._misses
        hit_rate = (total_hits / total_lookups) if total_lookups > 0 else 0.0

        return {
            "enabled": self.config.enabled,
            "entries": len(self._cache),
            "max_entries": self.config.max_entries,
            "exact_hits": self._exact_hits,
            "semantic_hits": self._semantic_hits,
            "total_hits": total_hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 4),
            "evictions": self._evictions,
            "ttl_seconds": self.config.ttl_seconds,
            "similarity_threshold": self.config.similarity_threshold,
        }

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()
        self._hash_index.clear()
        self._exact_hits = 0
        self._semantic_hits = 0
        self._misses = 0
        self._evictions = 0
