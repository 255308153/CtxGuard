"""Prompt Cache guardian ensuring vendor prefix caching consistency and safety.

100% Aligned with Headroom Prefix Cache Tracker & Session Tracker Store.
Follows the First Principle of Prompt Caching:
'Compression is a byproduct; what you really must protect is Prefix Caching.'
"""

import copy
import orjson
from typing import Any, Dict, List, Optional, Tuple

from ctxguard.core.context import NormalizedRequest, Message
from ctxguard.config.schema import CacheGuardConfig
from ctxguard.utils.token_counter import estimate_tokens_from_text
from ctxguard.core.guards.prefix_tracker import (
    _PROVIDER_READ_DISCOUNT,
    _PROVIDER_CACHE_TTL_SECONDS,
    PrefixFreezeConfig,
    PrefixCacheTracker,
    _canonicalize_for_prefix_compare,
    RELATION_EXACT,
    RELATION_MESSAGE_APPEND,
    RELATION_BLOCK_APPEND,
    classify_history_relation,
    segment_fingerprint,
    overlay_cached_prefix as headroom_overlay_cached_prefix,
    normalize_message_cache_control,
    SessionTrackerStore,
)


class CacheGuard:
    """Guarantees static prefix byte-level immutability for Anthropic/DeepSeek/OpenAI/Grok Prompt Cache.

    Headroom-aligned prefix tracking, overlay caching, and economic arbitration:
    1. Canonical Message & Block Equivalence Checking (strips transient transport noise)
    2. Overlay Cached Prefix (replays byte-exact previous forwarded representation)
    3. Multi-lineage Cross-turn Continuity (SessionTrackerStore & PrefixCacheTracker)
    4. Economic Savings Arbitrator (savings_fraction > provider read_discount)
    5. Cache Miss Attribution & TTL Expiry Detection
    """

    def __init__(self, config: CacheGuardConfig, db_manager: Optional[Any] = None):
        self.config = config
        self.db = db_manager

        # Headroom Session Tracker Store
        self._freeze_config = PrefixFreezeConfig(
            enabled=True,
            min_cached_tokens=getattr(config, "min_cacheable_tokens", 1024),
            force_compress_threshold=0.5,
        )
        self.tracker_store = SessionTrackerStore(default_config=self._freeze_config)

        # Lineage tracker resolved for the in-flight request of a session
        # (partition_messages -> record_forwarded_turn handoff). Keyed by
        # session id; consumed and popped by record_forwarded_turn.
        self._pending_trackers: Dict[str, Optional[PrefixCacheTracker]] = {}

        # In-memory hot L1 cache: stores last forwarded messages per session
        self._last_forwarded_messages: Dict[str, List[Message]] = {}
        self._last_original_messages: Dict[str, List[Message]] = {}
        self._last_cached_tokens: Dict[str, int] = {}
        self._frozen_system_prompts: Dict[str, Optional[str]] = {}
        self._frozen_system_messages: Dict[str, List[Message]] = {}

    def _sync_session_from_db(self, session_id: str, force: bool = False) -> None:
        """Load session prefix and cache state from persistent SQLite into memory."""
        if not self.db:
            return
        try:
            with self.db.get_connection() as conn:
                row = conn.execute(
                    "SELECT frozen_system_prompt, frozen_system_messages, last_forwarded_messages, last_original_messages, last_cached_tokens FROM session_cache WHERE session_id = ? LIMIT 1",
                    (session_id,),
                ).fetchone()
                if row:
                    if row["frozen_system_prompt"]:
                        self._frozen_system_prompts[session_id] = row["frozen_system_prompt"]
                    if row["frozen_system_messages"]:
                        raw_sys = orjson.loads(row["frozen_system_messages"])
                        self._frozen_system_messages[session_id] = [Message.from_dict(m) for m in raw_sys]
                    if row["last_forwarded_messages"]:
                        raw_fwd = orjson.loads(row["last_forwarded_messages"])
                        db_msgs = [Message.from_dict(m) for m in raw_fwd]
                        curr_msgs = self._last_forwarded_messages.get(session_id)
                        if force or curr_msgs is None or len(db_msgs) >= len(curr_msgs):
                            self._last_forwarded_messages[session_id] = db_msgs
                    if "last_original_messages" in row.keys() and row["last_original_messages"]:
                        raw_orig = orjson.loads(row["last_original_messages"])
                        self._last_original_messages[session_id] = [Message.from_dict(m) for m in raw_orig]
                    if row["last_cached_tokens"] is not None:
                        self._last_cached_tokens[session_id] = int(row["last_cached_tokens"])
        except Exception:
            pass

    def has_compressed_history(self, session_id: str) -> bool:
        """Check whether the session has established historical turns, syncing from DB if needed."""
        self._sync_session_from_db(session_id)
        return bool(self._last_forwarded_messages.get(session_id))

    def get_previous_turn_snapshot(self, session_id: str) -> Optional[Dict[str, Any]]:
        """返回缓存零诊断所需的上一轮已转发快照。"""
        self._sync_session_from_db(session_id)
        messages = self._last_original_messages.get(session_id) or self._last_forwarded_messages.get(session_id)
        if not messages:
            return None
        return {
            "messages": copy.deepcopy(messages),
            "forwarded_messages": copy.deepcopy(self._last_forwarded_messages.get(session_id, [])),
            "cached_tokens": self._last_cached_tokens.get(session_id, 0),
        }

    def _sync_session_to_db(self, session_id: str) -> None:
        """Persist session prefix and cache state to SQLite to synchronize across worker processes."""
        if not self.db:
            return
        try:
            sys_prompt = self._frozen_system_prompts.get(session_id)
            sys_msgs = self._frozen_system_messages.get(session_id)
            fwd_msgs = self._last_forwarded_messages.get(session_id)
            orig_msgs = self._last_original_messages.get(session_id)
            cached_toks = self._last_cached_tokens.get(session_id, 0)

            raw_sys_msgs = orjson.dumps([m.to_dict() for m in sys_msgs]).decode("utf-8") if sys_msgs else None
            raw_fwd_msgs = orjson.dumps([m.to_dict() for m in fwd_msgs]).decode("utf-8") if fwd_msgs else None
            raw_orig_msgs = orjson.dumps([m.to_dict() for m in orig_msgs]).decode("utf-8") if orig_msgs else None

            with self.db.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO session_cache (session_id, frozen_system_prompt, frozen_system_messages, last_forwarded_messages, last_original_messages, last_cached_tokens, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(session_id) DO UPDATE SET
                        frozen_system_prompt = coalesce(excluded.frozen_system_prompt, session_cache.frozen_system_prompt),
                        frozen_system_messages = coalesce(excluded.frozen_system_messages, session_cache.frozen_system_messages),
                        last_forwarded_messages = coalesce(excluded.last_forwarded_messages, session_cache.last_forwarded_messages),
                        last_original_messages = coalesce(excluded.last_original_messages, session_cache.last_original_messages),
                        last_cached_tokens = excluded.last_cached_tokens,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (session_id, sys_prompt, raw_sys_msgs, raw_fwd_msgs, raw_orig_msgs, cached_toks),
                )
                conn.commit()
        except Exception:
            pass

    def get_cache_ttl(self, provider: str = "default", model: str = "") -> int:
        """Resolve effective prompt cache TTL in seconds for a provider and model family."""
        provider_lower = (provider or "default").lower()
        model_lower = (model or "").lower()
        ttls = getattr(self.config, "provider_cache_ttls", {}) or {}

        # 1. Model keyword matching
        if "gemini" in model_lower and "gemini" in ttls:
            return ttls["gemini"]
        if "google" in model_lower and "google" in ttls:
            return ttls["google"]
        if ("claude" in model_lower or "anthropic" in model_lower) and "anthropic" in ttls:
            return ttls["anthropic"]
        if "deepseek" in model_lower and "deepseek" in ttls:
            return ttls["deepseek"]
        if ("grok" in model_lower or "xai" in model_lower) and "grok" in ttls:
            return ttls["grok"]
        if any(k in model_lower for k in ("gpt", "o1", "o3")) and "openai" in ttls:
            return ttls["openai"]

        # 2. Direct provider match
        if provider_lower in ttls:
            return ttls[provider_lower]

        # 3. Headroom default provider table lookup
        if provider_lower in _PROVIDER_CACHE_TTL_SECONDS:
            return _PROVIDER_CACHE_TTL_SECONDS[provider_lower]

        return ttls.get("default", self.config.cache_ttl_seconds)

    def should_cold_recompact(
        self,
        idle_seconds: float,
        provider: str = "default",
        model: str = "",
    ) -> bool:
        """Determine whether the upstream cache has naturally expired and cold recompact should fire."""
        if not self.config.cold_recompact_enabled:
            return False
        ttl = self.get_cache_ttl(provider=provider, model=model)
        return idle_seconds > ttl

    def should_break_cache_for_compression(
        self,
        raw_tokens: int,
        compressed_tokens: int,
        provider: str = "default"
    ) -> bool:
        """Arbitrate whether compression savings outweigh losing upstream prompt cache read discount."""
        if raw_tokens <= 0:
            return False
        savings_fraction = (raw_tokens - compressed_tokens) / float(raw_tokens)
        discounts = self.config.provider_read_discounts
        provider_lower = (provider or "default").lower()
        if provider_lower in discounts:
            read_discount = discounts[provider_lower]
        elif provider_lower in _PROVIDER_READ_DISCOUNT:
            read_discount = _PROVIDER_READ_DISCOUNT[provider_lower]
        else:
            read_discount = discounts.get("default", 0.5)
        return savings_fraction > read_discount

    def normalize_message_for_comparison(self, msg: Any) -> Any:
        """Create a sanitized semantic representation of a message solely for comparison."""
        if isinstance(msg, Message):
            d = msg.to_dict()
        elif isinstance(msg, dict):
            d = msg
        else:
            return str(msg)
        return _canonicalize_for_prefix_compare(d)

    def is_prefix_stable(self, session_id: str, current_messages: List[Message]) -> bool:
        """Compare current messages with last forwarded messages using Headroom canonical projection."""
        self._sync_session_from_db(session_id)
        prev = self._last_forwarded_messages.get(session_id)
        if not prev:
            return True
        if len(current_messages) < len(prev):
            return False

        prev_dicts = [m.to_dict() if isinstance(m, Message) else m for m in prev]
        curr_dicts = [m.to_dict() if isinstance(m, Message) else m for m in current_messages[:len(prev)]]

        # Use Headroom history relation classification
        relation = classify_history_relation(prev_dicts, curr_dicts)
        return relation.kind in (RELATION_EXACT, RELATION_MESSAGE_APPEND, RELATION_BLOCK_APPEND)

    def _resolve_lineage_tracker(
        self,
        request: NormalizedRequest,
        session_id: str,
        provider: str,
    ) -> Optional[PrefixCacheTracker]:
        """Resolve the per-conversation lineage tracker for this request.

        Wraps SessionTrackerStore.resolve_tracker (Headroom #2085): parallel
        conversations sharing one session id (e.g. Claude Code and its
        subagents) get distinct trackers keyed by conversation lineage, so
        their frozen-prefix states never cross-contaminate. Lineage matching
        runs on the RAW client messages; the affinity fingerprint covers the
        provider's non-message cache-key segments (model / tools / tool_choice).
        Any resolution failure degrades gracefully to None (session-wide state).
        """
        try:
            messages = [
                m.to_dict() if isinstance(m, Message) else m
                for m in request.messages
            ]
            affinity = segment_fingerprint({
                "model": getattr(request, "model", ""),
                "tools": getattr(request, "tools", None),
                "tool_choice": getattr(request, "tool_choice", None),
            })
            return self.tracker_store.resolve_tracker(
                session_id,
                provider,
                messages=messages,
                cache_affinity=affinity,
            )
        except Exception:
            return None

    def partition_messages(
        self,
        request: NormalizedRequest,
        session_id: str = "default",
        idle_seconds: float = 0.0,
        provider: str = "default",
    ) -> Tuple[List[Message], List[Message], bool]:
        """Split request messages into (frozen_prefix, compressible_suffix, was_cold_recompacted)."""
        messages = request.messages
        if not messages:
            return [], [], False

        self._sync_session_from_db(session_id)

        model = getattr(request, "model", "")
        req_provider = getattr(request, "provider", provider)

        # 0. Multi-lineage resolution (Headroom #2085): pick the tracker for
        # THIS conversation within the session id, and register it for the
        # matching record_forwarded_turn call downstream.
        lineage_tracker = self._resolve_lineage_tracker(request, session_id, req_provider)
        self._pending_trackers[session_id] = lineage_tracker

        # 1. Cold Recompact Check (fires when cache TTL expired)
        if self.should_cold_recompact(idle_seconds, provider=req_provider, model=model):
            self._frozen_system_prompts.pop(session_id, None)
            self._frozen_system_messages.pop(session_id, None)
            if self.db:
                try:
                    with self.db.get_connection() as conn:
                        conn.execute("DELETE FROM session_cache WHERE session_id = ?", (session_id,))
                        conn.commit()
                except Exception:
                    pass
            return [], messages, True

        if len(messages) == 1:
            return [], messages, False

        # System Prompt / Leading Instructions Immutability Freeze (Session-Level Snapshot)
        if self.config.freeze_system_prompt:
            if session_id not in self._frozen_system_prompts and request.system is not None:
                self._frozen_system_prompts[session_id] = request.system
                self._sync_session_to_db(session_id)
            elif session_id in self._frozen_system_prompts and request.system is not None:
                request.system = self._frozen_system_prompts[session_id]

            leading_sys = [m for m in messages if m.role in ("system", "developer")]
            if session_id not in self._frozen_system_messages and leading_sys:
                self._frozen_system_messages[session_id] = [copy.deepcopy(m) for m in leading_sys]
                self._sync_session_to_db(session_id)
            elif session_id in self._frozen_system_messages:
                frozen_sys = self._frozen_system_messages[session_id]
                for s_i, f_msg in enumerate(frozen_sys):
                    if s_i < len(messages) and messages[s_i].role in ("system", "developer"):
                        messages[s_i] = copy.deepcopy(f_msg)

        # 2. Dynamic Token-to-Message Bound Reverse Mapping & Historical Replay
        last_cached = self._last_cached_tokens.get(session_id, 0)
        # State source: the primary (first) lineage stays on the session-wide
        # dicts, which the session_cache table keeps in sync across worker
        # processes. Only derived lineages (parallel conversations sharing the
        # session id) fall back to their in-memory tracker state — the session
        # wide dict would hold whichever sibling forwarded last.
        tracker_fwd = None
        if (
            lineage_tracker is not None
            and lineage_tracker._turn_number > 0
            and not self.tracker_store.is_primary_lineage(session_id, lineage_tracker)
        ):
            tracker_fwd = lineage_tracker.get_last_forwarded_messages()
        prev_forwarded = tracker_fwd or self._last_forwarded_messages.get(session_id)
        frozen_count = 0

        # Primary Protection: If session already has previously forwarded messages
        if prev_forwarded and len(messages) > 1:
            frozen_count = min(len(messages) - 1, len(prev_forwarded))
        elif last_cached >= self.config.min_cacheable_tokens:
            accumulated = 0
            for i, msg in enumerate(messages):
                tok_count = estimate_tokens_from_text(msg.get_text_content())
                accumulated += max(1, tok_count)
                if accumulated <= last_cached:
                    frozen_count = i + 1
                else:
                    break
        else:
            if self.config.freeze_prefix_rounds > 0:
                frozen_count = min(len(messages), self.config.freeze_prefix_rounds * 2)

        # Fallback to system prompt freeze if dynamic count is below leading system messages
        start_idx = 0
        if self.config.freeze_system_prompt:
            while start_idx < len(messages) and messages[start_idx].role in ("system", "developer"):
                start_idx += 1
            frozen_count = max(frozen_count, start_idx)

        # 3. Strict turn protection: Ensure latest turn is ALWAYS compressible
        max_freeze = max(0, len(messages) - 1)
        final_frozen = min(max_freeze, frozen_count)

        frozen_prefix = messages[:final_frozen]
        compressible_suffix = messages[final_frozen:]

        # 4. Headroom overlay_cached_prefix: Replay exact previous forwarded representations
        frozen_prefix = self.overlay_cached_prefix(
            session_id=session_id,
            current_frozen_prefix=frozen_prefix,
            current_original_messages=getattr(request, "_raw_original_messages", None),
            tracker=lineage_tracker,
        )

        return frozen_prefix, compressible_suffix, False

    def overlay_cached_prefix(
        self,
        session_id: str,
        current_frozen_prefix: List[Message],
        current_original_messages: Optional[List[Any]] = None,
        tracker: Optional[PrefixCacheTracker] = None,
    ) -> List[Message]:
        """Replay exact previously forwarded message representations using Headroom overlay_cached_prefix algorithm.

        State source priority: for a derived (non-primary) lineage with
        recorded turns, use the lineage tracker's own state — the session-wide
        dicts may belong to a sibling conversation sharing the session id.
        Otherwise (primary lineage / DB-restored sessions) use the session-wide
        dicts, which are kept in sync across worker processes.
        """
        prev_forwarded = None
        prev_orig = None
        if (
            tracker is not None
            and tracker._turn_number > 0
            and not self.tracker_store.is_primary_lineage(session_id, tracker)
        ):
            prev_forwarded = tracker.get_last_forwarded_messages() or None
            prev_orig = tracker.get_last_original_messages() or None
        if prev_forwarded is None:
            prev_forwarded = self._last_forwarded_messages.get(session_id)
            prev_orig = self._last_original_messages.get(session_id)
        if not prev_forwarded or not current_frozen_prefix:
            return current_frozen_prefix

        # Convert to dict format for Headroom pure function
        prev_fwd_dicts = [m.to_dict() if isinstance(m, Message) else m for m in prev_forwarded]
        curr_prefix_dicts = [m.to_dict() if isinstance(m, Message) else m for m in current_frozen_prefix]

        prev_orig = self._last_original_messages.get(session_id)
        prev_orig_dicts = [m.to_dict() if isinstance(m, Message) else m for m in prev_orig] if prev_orig else prev_fwd_dicts

        if current_original_messages:
            curr_orig_dicts = [m.to_dict() if isinstance(m, Message) else m for m in current_original_messages[:len(current_frozen_prefix)]]
        else:
            curr_orig_dicts = curr_prefix_dicts

        try:
            overlaid_dicts = headroom_overlay_cached_prefix(
                optimized_messages=curr_prefix_dicts,
                current_original_messages=curr_orig_dicts,
                previous_original_messages=prev_orig_dicts,
                previous_forwarded_messages=prev_fwd_dicts,
                confirmed_frozen_count=len(curr_prefix_dicts),
            )
            return [Message.from_dict(d) for d in overlaid_dicts]
        except Exception:
            # Safe fallback to current frozen prefix
            return current_frozen_prefix

    def record_forwarded_turn(
        self,
        session_id: str,
        forwarded_messages: List[Message],
        cached_tokens: int = 0,
        original_messages: Optional[List[Any]] = None,
    ) -> None:
        """Store the exact forwarded messages and cache token response after upstream returns."""
        # Feed the per-lineage tracker resolved during partition_messages
        # (Headroom contract: read tokens drive next-turn frozen counts).
        tracker = self._pending_trackers.pop(session_id, None)
        is_secondary = (
            tracker is not None
            and not self.tracker_store.is_primary_lineage(session_id, tracker)
        )

        # Session-wide dicts + DB persistence only carry the primary lineage:
        # a derived lineage's bytes must never become the shared replay state.
        if not is_secondary:
            self._last_forwarded_messages[session_id] = copy.deepcopy(forwarded_messages)
            if original_messages:
                self._last_original_messages[session_id] = copy.deepcopy(original_messages)
            # 保存当前轮真实结果，0 也要写回，避免把更早的命中误认为上一轮命中。
            self._last_cached_tokens[session_id] = max(0, int(cached_tokens or 0))

        if tracker is not None:
            try:
                fwd_dicts = [
                    m.to_dict() if isinstance(m, Message) else m
                    for m in forwarded_messages
                ]
                orig_dicts = (
                    [m.to_dict() if isinstance(m, Message) else m for m in original_messages]
                    if original_messages
                    else None
                )
                tracker.update_from_response(
                    cache_read_tokens=max(0, int(cached_tokens or 0)),
                    cache_write_tokens=0,
                    messages=fwd_dicts,
                    original_messages=orig_dicts,
                )
            except Exception:
                pass

        if not is_secondary:
            self._sync_session_to_db(session_id)

    def classify_cache_miss(
        self,
        expected_cached: int,
        actual_cached: int,
        idle_seconds: float,
        prefix_stable: bool,
        provider: str = "default",
        model: str = "",
    ) -> str:
        """Diagnose root cause of cache misses following the Headroom 'TTL wins tie-breaker' principle."""
        if expected_cached <= 0:
            return "cold_start"
        if actual_cached > 0:
            return "hit"
        ttl = self.get_cache_ttl(provider=provider, model=model)
        if idle_seconds > ttl:
            return "ttl_expiry"
        if not prefix_stable:
            return "prefix_change"
        return "provider_eviction"

    def apply_anthropic_cache_control(self, request: NormalizedRequest) -> None:
        """Inject Anthropic ephemeral cache_control marker on the last stable frozen block using Headroom rules."""
        if not self.config.auto_anthropic_cache_control or request.protocol != "anthropic":
            return

        if not request.messages:
            return

        msg_dicts = [m.to_dict() for m in request.messages]
        try:
            normalized_dicts = normalize_message_cache_control(msg_dicts, max_breakpoints=4)
            request.messages = [Message.from_dict(d) for d in normalized_dicts]
        except Exception:
            pass

    @staticmethod
    def derive_prompt_cache_key(session_id: str, model: str = "") -> str:
        """Derive a deterministic prompt_cache_key per session and model family (Headroom PR-E4)."""
        clean_sid = session_id.strip() if session_id else "default"
        clean_model = model.strip().lower() if model else "default"
        model_family = clean_model.split("-")[0] if "-" in clean_model else clean_model
        return f"{clean_sid}_{model_family}"

    def apply_prompt_cache_key(self, payload: Dict[str, Any], session_id: str, model: str = "") -> None:
        """Inject prompt_cache_key into OpenAI-compatible payload if missing (Headroom PR-E4)."""
        if not getattr(self.config, "inject_prompt_cache_key", True):
            return
        if not session_id or session_id == "default":
            return
        if "prompt_cache_key" not in payload or not payload.get("prompt_cache_key"):
            payload["prompt_cache_key"] = self.derive_prompt_cache_key(session_id, model)
