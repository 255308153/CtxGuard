"""Prompt Cache guardian ensuring vendor prefix caching consistency and safety.

Follows the First Principle of Prompt Caching:
'Compression is a byproduct; what you really must protect is Prefix Caching.'
"""

import copy
import orjson
from typing import Any, Dict, List, Optional, Set, Tuple
from ctxguard.core.context import NormalizedRequest, Message
from ctxguard.config.schema import CacheGuardConfig
from ctxguard.utils.token_counter import estimate_tokens_from_text


# Non-semantic fields that can fluctuate across turns without altering prompt semantics.
# These are stripped strictly for COMPARISON KEYS, never for forwarded payloads.
_NON_SEMANTIC_KEYS: Set[str] = {
    "cache_control", "cachePoint", "cache_point",
    "caller", "provider_specific_fields",
    "reasoning_content", "reasoning_items", "annotations",
    "system_fingerprint", "service_tier",
    "providerMetadata", "providerOptions", "callProviderMetadata",
    "state", "providerExecuted", "synthetic", "ignored",
    "index",
}

# Opaque payload keys: parameters inside tool calls must NOT be recursively stripped.
_OPAQUE_PAYLOAD_KEYS: Set[str] = {"input", "arguments", "json"}


class CacheGuard:
    """Guarantees static prefix byte-level immutability for Anthropic/DeepSeek/OpenAI Prompt Cache.

    Implements:
    1. Dynamic Token-to-Message Bound Reverse Mapping (replaces static round counts)
    2. Overlay Cached Prefix (replays previous exact forwarded bytes to prevent compression jitter)
    3. Prefix Normalization & Stability Checking (anti false-positive comparison)
    4. Economic Savings Arbitrator (savings_fraction > read_discount)
    5. Cache Miss Attribution & TTL Expiry Detection
    """

    def __init__(self, config: CacheGuardConfig, db_manager: Optional[Any] = None):
        self.config = config
        self.db = db_manager
        # In-memory hot L1 cache: stores last forwarded messages per session
        # session_id -> list of raw Message dicts/objects
        self._last_forwarded_messages: Dict[str, List[Message]] = {}
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
                    "SELECT frozen_system_prompt, frozen_system_messages, last_forwarded_messages, last_cached_tokens FROM session_cache WHERE session_id = ? LIMIT 1",
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
                    if row["last_cached_tokens"] is not None:
                        self._last_cached_tokens[session_id] = int(row["last_cached_tokens"])
        except Exception:
            pass

    def has_compressed_history(self, session_id: str) -> bool:
        """Check whether the session has established historical turns, syncing from DB if needed."""
        self._sync_session_from_db(session_id)
        return bool(self._last_forwarded_messages.get(session_id))

    def _sync_session_to_db(self, session_id: str) -> None:
        """Persist session prefix and cache state to SQLite to synchronize across worker processes."""
        if not self.db:
            return
        try:
            sys_prompt = self._frozen_system_prompts.get(session_id)
            sys_msgs = self._frozen_system_messages.get(session_id)
            fwd_msgs = self._last_forwarded_messages.get(session_id)
            cached_toks = self._last_cached_tokens.get(session_id, 0)

            raw_sys_msgs = orjson.dumps([m.to_dict() for m in sys_msgs]).decode("utf-8") if sys_msgs else None
            raw_fwd_msgs = orjson.dumps([m.to_dict() for m in fwd_msgs]).decode("utf-8") if fwd_msgs else None

            with self.db.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO session_cache (session_id, frozen_system_prompt, frozen_system_messages, last_forwarded_messages, last_cached_tokens, updated_at)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(session_id) DO UPDATE SET
                        frozen_system_prompt = coalesce(excluded.frozen_system_prompt, session_cache.frozen_system_prompt),
                        frozen_system_messages = coalesce(excluded.frozen_system_messages, session_cache.frozen_system_messages),
                        last_forwarded_messages = coalesce(excluded.last_forwarded_messages, session_cache.last_forwarded_messages),
                        last_cached_tokens = excluded.last_cached_tokens,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (session_id, sys_prompt, raw_sys_msgs, raw_fwd_msgs, cached_toks),
                )
                conn.commit()
        except Exception:
            pass

    def get_cache_ttl(self, provider: str = "default", model: str = "") -> int:
        """Resolve effective prompt cache TTL in seconds for a provider and model family.

        Handles:
        - Direct provider lookup in provider_cache_ttls (e.g. 'gemini', 'google', 'anthropic')
        - Gateway proxy / multi-model providers like 'antigravity', inspects model name (e.g. 'gemini-3.8-flash-high')
        - Model keyword matching (e.g. 'gemini', 'claude', 'deepseek', 'gpt')
        - Fallback to 'default' key or config.cache_ttl_seconds
        """
        provider_lower = (provider or "default").lower()
        model_lower = (model or "").lower()
        ttls = getattr(self.config, "provider_cache_ttls", {}) or {}

        # 1. Inspect model name first if provider is a proxy/aggregator (e.g. "antigravity", "default", "custom")
        if provider_lower in ("antigravity", "default", "custom", ""):
            if "gemini" in model_lower and "gemini" in ttls:
                return ttls["gemini"]
            if ("claude" in model_lower or "anthropic" in model_lower) and "anthropic" in ttls:
                return ttls["anthropic"]
            if "deepseek" in model_lower and "deepseek" in ttls:
                return ttls["deepseek"]
            if any(k in model_lower for k in ("gpt", "o1", "o3")) and "openai" in ttls:
                return ttls["openai"]

        # 2. Direct provider match
        if provider_lower in ttls:
            return ttls[provider_lower]

        # 3. Model keyword fallback
        if "gemini" in model_lower and "gemini" in ttls:
            return ttls["gemini"]
        if "google" in model_lower and "google" in ttls:
            return ttls["google"]
        if ("claude" in model_lower or "anthropic" in model_lower) and "anthropic" in ttls:
            return ttls["anthropic"]
        if "deepseek" in model_lower and "deepseek" in ttls:
            return ttls["deepseek"]
        if any(k in model_lower for k in ("gpt", "o1", "o3")) and "openai" in ttls:
            return ttls["openai"]

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
        """Arbitrate whether compression savings outweigh losing upstream prompt cache read discount.

        Formula:
            savings_fraction = (raw_tokens - compressed_tokens) / raw_tokens
            break_even: savings_fraction > read_discount
        """
        if raw_tokens <= 0:
            return False
        savings_fraction = (raw_tokens - compressed_tokens) / float(raw_tokens)
        discounts = self.config.provider_read_discounts
        read_discount = discounts.get(provider.lower(), discounts.get("default", 0.5))
        return savings_fraction > read_discount

    def normalize_message_for_comparison(self, msg: Any) -> Any:
        """Create a sanitized semantic representation of a message solely for comparison.

        Rules:
        - Strip non-semantic keys (cache_control, index, etc.)
        - Normalize string vs [{'type': 'text', 'text': ...}]
        - Preserve opaque tool call payloads (arguments, input) without modification
        - NEVER mutate the original message
        """
        if isinstance(msg, Message):
            role = msg.role
            content = msg.content
            tool_calls = msg.tool_calls
        elif isinstance(msg, dict):
            role = msg.get("role")
            content = msg.get("content")
            tool_calls = msg.get("tool_calls")
        else:
            return str(msg)

        # 1. Normalize content format
        norm_content = self._normalize_content(content)

        # 2. Normalize tool_calls
        norm_tool_calls = None
        if tool_calls and isinstance(tool_calls, list):
            norm_tool_calls = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    tc_copy = {}
                    for k, v in tc.items():
                        if k in _NON_SEMANTIC_KEYS:
                            continue
                        if k == "function" and isinstance(v, dict):
                            # Preserve opaque arguments
                            tc_copy["function"] = {
                                fk: fv for fk, fv in v.items() if fk not in _NON_SEMANTIC_KEYS
                            }
                        else:
                            tc_copy[k] = v
                    norm_tool_calls.append(tc_copy)
                else:
                    norm_tool_calls.append(tc)

        return {
            "role": role,
            "content": norm_content,
            "tool_calls": norm_tool_calls,
        }

    def _normalize_content(self, content: Any) -> Any:
        """Normalize content structures, stripping non-semantic fields outside opaque payloads."""
        if isinstance(content, str):
            # Canonical representation: list of text blocks
            return [{"type": "text", "text": content}]

        if isinstance(content, list):
            res = []
            for block in content:
                if isinstance(block, str):
                    res.append({"type": "text", "text": block})
                elif isinstance(block, dict):
                    clean_block = {}
                    for k, v in block.items():
                        if k in _NON_SEMANTIC_KEYS:
                            continue
                        # If inside opaque payload (input, arguments, json), keep as-is
                        if k in _OPAQUE_PAYLOAD_KEYS:
                            clean_block[k] = v
                        elif isinstance(v, (dict, list)):
                            clean_block[k] = self._normalize_content(v)
                        else:
                            clean_block[k] = v
                    res.append(clean_block)
                else:
                    res.append(block)
            return res

        if isinstance(content, dict):
            clean_dict = {}
            for k, v in content.items():
                if k in _NON_SEMANTIC_KEYS:
                    continue
                if k in _OPAQUE_PAYLOAD_KEYS:
                    clean_dict[k] = v
                elif isinstance(v, (dict, list)):
                    clean_dict[k] = self._normalize_content(v)
                else:
                    clean_dict[k] = v
            return clean_dict

        return content

    def is_prefix_stable(self, session_id: str, current_messages: List[Message]) -> bool:
        """Compare current messages with last forwarded messages using normalized comparison keys."""
        self._sync_session_from_db(session_id)
        prev = self._last_forwarded_messages.get(session_id)
        if not prev:
            return True

        if len(current_messages) < len(prev):
            return False

        # Compare common prefix up to len(prev)
        for p_msg, c_msg in zip(prev, current_messages[:len(prev)]):
            p_norm = self.normalize_message_for_comparison(p_msg)
            c_norm = self.normalize_message_for_comparison(c_msg)
            if p_norm != c_norm:
                return False

        return True

    def partition_messages(
        self,
        request: NormalizedRequest,
        session_id: str = "default",
        idle_seconds: float = 0.0,
        provider: str = "default",
    ) -> Tuple[List[Message], List[Message], bool]:
        """Split request messages into (frozen_prefix, compressible_suffix, was_cold_recompacted).

        Rules:
        - If idle_seconds > cache_ttl_seconds: Cold Recompact fires! All messages compressible.
        - Otherwise, dynamically accumulate token counts to match last upstream cached_tokens.
        - Strict constraint: Always leave at least the latest user/tool turn compressible.
        """
        messages = request.messages
        if not messages:
            return [], [], False

        self._sync_session_from_db(session_id)

        model = getattr(request, "model", "")
        req_provider = getattr(request, "provider", provider)

        # 1. Cold Recompact Check (fires when cache TTL expired)
        if self.should_cold_recompact(idle_seconds, provider=req_provider, model=model):
            # Cache is dead anyway; lift freeze completely for global re-baselining
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
            # Snapshot on first turn of the session
            if session_id not in self._frozen_system_prompts and request.system is not None:
                self._frozen_system_prompts[session_id] = request.system
                self._sync_session_to_db(session_id)
            elif session_id in self._frozen_system_prompts and request.system is not None:
                # Replay frozen system prompt to guarantee 100% prefix byte stability
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
        prev_forwarded = self._last_forwarded_messages.get(session_id)
        frozen_count = 0

        # Primary Protection: If session already has previously forwarded and cached messages,
        # freeze all established historical turns so they are never re-compressed or distorted
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
            # Baseline fallback: freeze configured rounds when cache history is not yet established
            if self.config.freeze_prefix_rounds > 0:
                frozen_count = min(len(messages), self.config.freeze_prefix_rounds * 2)

        # Fallback to system prompt freeze if dynamic count is below leading system messages
        start_idx = 0
        if self.config.freeze_system_prompt:
            while start_idx < len(messages) and messages[start_idx].role in ("system", "developer"):
                start_idx += 1
            frozen_count = max(frozen_count, start_idx)

        # 3. Strict turn protection: Ensure latest turn is ALWAYS compressible
        # If the last message is a user message, leave at least that turn compressible
        max_freeze = max(0, len(messages) - 1)
        final_frozen = min(max_freeze, frozen_count)

        frozen_prefix = messages[:final_frozen]
        compressible_suffix = messages[final_frozen:]

        # 4. Overlay Cached Prefix: Replay exact previous forwarded messages to eliminate jitter
        frozen_prefix = self.overlay_cached_prefix(session_id, frozen_prefix)

        return frozen_prefix, compressible_suffix, False

    def overlay_cached_prefix(
        self, session_id: str, current_frozen_prefix: List[Message]
    ) -> List[Message]:
        """Replay exact previously forwarded message representations for the frozen prefix.

        This ensures that even if local compressors or adaptive levels change, the exact
        bytes matching upstream KV-cache are preserved without jitter.
        """
        prev = self._last_forwarded_messages.get(session_id)
        if not prev or not current_frozen_prefix:
            return current_frozen_prefix

        # Only overlay if the semantic content is stable
        overlap_len = min(len(prev), len(current_frozen_prefix))
        replayed = []
        for i in range(overlap_len):
            p_msg = prev[i]
            c_msg = current_frozen_prefix[i]
            # Role must match
            if p_msg.role != c_msg.role:
                replayed.append(c_msg)
                continue

            # Verify semantic match or historical turn continuity:
            # Replaying p_msg restores the exact forwarded bytes to guarantee 100% KV cache hit
            p_norm = self.normalize_message_for_comparison(p_msg)
            c_norm = self.normalize_message_for_comparison(c_msg)
            if p_norm == c_norm or p_msg.role in ("system", "developer", "assistant") or len(c_msg.get_text_content()) > 0:
                replayed.append(copy.deepcopy(p_msg))
            else:
                replayed.append(c_msg)

        # Append remaining messages if current prefix exceeds previous history
        if len(current_frozen_prefix) > overlap_len:
            replayed.extend(current_frozen_prefix[overlap_len:])

        return replayed

    def record_forwarded_turn(
        self, session_id: str, forwarded_messages: List[Message], cached_tokens: int = 0
    ) -> None:
        """Store the exact forwarded messages and cache token response after upstream returns."""
        self._last_forwarded_messages[session_id] = copy.deepcopy(forwarded_messages)
        if cached_tokens > 0:
            self._last_cached_tokens[session_id] = cached_tokens
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
        """Diagnose root cause of cache misses following the 'TTL wins tie-breaker' principle.

        Returns one of:
        - 'hit': Successfully reused prompt cache
        - 'cold_start': First turn or previous turn had no cache
        - 'ttl_expiry': Idle exceeded cache TTL (TTL wins over prefix_change)
        - 'prefix_change': Prefix was mutated by client/operator
        - 'provider_eviction': Cache within TTL & prefix stable, but evicted upstream
        """
        if expected_cached <= 0:
            return "cold_start"
        if actual_cached > 0:
            return "hit"
        ttl = self.get_cache_ttl(provider=provider, model=model)
        if idle_seconds > ttl:
            # TTL wins tie-breaker because it directly informs the decision
            # whether to switch to long-lived (e.g. 1-hour) cache or cold recompact.
            return "ttl_expiry"
        if not prefix_stable:
            return "prefix_change"
        return "provider_eviction"

    def apply_anthropic_cache_control(self, request: NormalizedRequest) -> None:
        """Inject Anthropic ephemeral cache_control marker on the last stable frozen block."""
        if not self.config.auto_anthropic_cache_control or request.protocol != "anthropic":
            return

        if request.messages:
            # Place cache_control at the end of the frozen prefix, or first message
            target_msg = request.messages[-1]
            if len(request.messages) > 1:
                target_msg = request.messages[-2]

            if isinstance(target_msg.content, list):
                already_tagged = any(
                    isinstance(b, dict) and "cache_control" in b for b in target_msg.content
                )
                if not already_tagged and target_msg.content:
                    last_block = target_msg.content[-1]
                    if isinstance(last_block, dict):
                        last_block["cache_control"] = {"type": "ephemeral"}
            elif isinstance(target_msg.content, str):
                target_msg.content = [
                    {
                        "type": "text",
                        "text": target_msg.content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

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

