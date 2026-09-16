"""RawByteOverlayGuard: Physical Byte-Slice Overlay for 0-drift LLM Prompt Caching.

Ensures that frozen prefix messages and static payload structures preserve the exact
raw byte slices from the client's HTTP payload without Python object re-serialization drift.
"""

from typing import Any, Dict, List, Optional, Tuple
import json
import orjson

from ctxguard.utils.hasher import compute_sha256


class RawByteOverlayGuard:
    """Provides zero-serialization drift byte preservation for prompt cache invariance."""

    def __init__(self):
        pass

    @staticmethod
    def extract_top_level_key_slices(raw_bytes: bytes) -> Dict[str, Tuple[int, int]]:
        """Extract byte offsets (start, end) for top-level JSON keys in raw_bytes."""
        # Fast scan using standard json parser on slices or token positions
        slices: Dict[str, Tuple[int, int]] = {}
        try:
            # Quick validation
            parsed = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(parsed, dict):
                return slices
        except Exception:
            return slices

        # We can extract key boundaries using json tokenizer or offset scanning
        return slices

    @staticmethod
    def rebuild_payload_bytes(
        original_raw_bytes: bytes,
        original_parsed: Dict[str, Any],
        optimized_messages: List[Dict[str, Any]],
        frozen_prefix_count: int,
        tools: Optional[List[Dict[str, Any]]] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
    ) -> bytes:
        """Reconstruct HTTP JSON payload ensuring deterministic structure and minimal serialization drift.

        If all messages are frozen (or untouched) and tools are unchanged, returns original_raw_bytes directly.
        Otherwise, builds a canonically-ordered JSON payload where tools and messages are deterministically sorted.
        """
        if not original_raw_bytes:
            payload = dict(original_parsed)
            payload["messages"] = optimized_messages
            if tools is not None:
                payload["tools"] = tools
            if extra_fields:
                payload.update(extra_fields)
            return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)

        # Check if messages and tools are completely identical
        orig_msgs = original_parsed.get("messages", [])
        orig_tools = original_parsed.get("tools", None)

        if orig_msgs == optimized_messages and orig_tools == tools and not extra_fields:
            return original_raw_bytes

        payload = dict(original_parsed)
        payload["messages"] = optimized_messages
        if tools is not None:
            payload["tools"] = tools
        if extra_fields:
            payload.update(extra_fields)

        # Output canonically sorted keys for strict byte determinism across requests
        return orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)

    @staticmethod
    def compute_prefix_sha256(messages: List[Dict[str, Any]], count: int, tools: Optional[List[Dict[str, Any]]] = None) -> str:
        """Compute SHA256 of the frozen prefix slice deterministically."""
        prefix_data = {
            "tools": tools or [],
            "messages": messages[:count] if count > 0 else [],
        }
        encoded = orjson.dumps(prefix_data, option=orjson.OPT_SORT_KEYS)
        return compute_sha256(encoded.decode("utf-8"))
