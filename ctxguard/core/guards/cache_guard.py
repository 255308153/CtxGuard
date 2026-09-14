"""Prompt Cache guardian ensuring vendor prefix caching consistency."""

from typing import List, Tuple
from ctxguard.core.context import NormalizedRequest, Message
from ctxguard.config.schema import CacheGuardConfig


class CacheGuard:
    """Guarantees static prefix byte-level immutability for Anthropic/DeepSeek Prompt Cache."""

    def __init__(self, config: CacheGuardConfig):
        self.config = config

    def partition_messages(
        self, request: NormalizedRequest
    ) -> Tuple[List[Message], List[Message]]:
        """Split request messages into (frozen_prefix, compressible_suffix).

        Frozen prefix messages must never be altered in byte content or order.
        Compressible suffix messages can be safely cleaned and deduplicated.
        
        Rule:
        - The most recent turn (at least the last message/tool result) is ALWAYS compressible.
        - Historical turns within `freeze_prefix_rounds` are strictly frozen.
        """
        messages = request.messages
        if not messages:
            return [], []

        if len(messages) == 1:
            # Single message is the current turn, always compressible
            return [], messages

        # Handle leading system message
        start_idx = 0
        if self.config.freeze_system_prompt:
            while start_idx < len(messages) and messages[start_idx].role == "system":
                start_idx += 1

        conv_messages = messages[start_idx:]
        freeze_rounds = self.config.freeze_prefix_rounds

        # We must leave at least the latest user/tool turn compressible
        # e.g., if there are 4 conv messages and freeze_rounds=2, we freeze min(4-1, 2*2) = 3 messages
        max_freeze = max(0, len(conv_messages) - 1)
        freeze_count = min(max_freeze, freeze_rounds * 2)

        frozen_prefix = messages[: start_idx + freeze_count]
        compressible_suffix = messages[start_idx + freeze_count :]

        return frozen_prefix, compressible_suffix

    def apply_anthropic_cache_control(self, request: NormalizedRequest) -> None:
        """Inject Anthropic ephemeral cache_control marker to maximize prompt cache hits."""
        if not self.config.auto_anthropic_cache_control or request.protocol != "anthropic":
            return

        if request.messages:
            frozen_prefix, _ = self.partition_messages(request)
            target_msg = frozen_prefix[-1] if frozen_prefix else request.messages[0]

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
