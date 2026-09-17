"""Thinking and Reasoning CoT Lifecycle Manager for multi-turn conversations."""

import re
from typing import Any, Dict, List, Optional
from ctxguard.config.schema import ThinkingManagerConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.utils.token_counter import estimate_tokens_from_text


class ThinkingManager:
    """Manages reasoning/thinking tokens across multi-turn sessions for DeepSeek, Gemini, and Claude."""

    THINK_TAG_REGEX = re.compile(r"<think(?:ing)?>[\s\S]*?<\/think(?:ing)?>", re.IGNORECASE)

    def __init__(self, config: ThinkingManagerConfig):
        self.config = config

    def manage_thinking_tokens(
        self,
        request: NormalizedRequest,
        provider: str = "default",
        was_cold: bool = False
    ) -> int:
        """Process and manage thinking blocks across historical conversation messages.

        Returns the number of thinking tokens stripped/reclaimed.
        """
        if not self.config.enabled or not request.messages:
            return 0

        provider_lower = provider.lower()
        model_lower = request.model.lower() if request.model else ""
        is_deepseek = "deepseek" in provider_lower or "deepseek" in model_lower or "r1" in model_lower
        is_gemini = "gemini" in provider_lower or "google" in provider_lower or "gemini" in model_lower
        is_anthropic = "anthropic" in provider_lower or "claude" in model_lower

        tokens_reclaimed = 0

        # 1. DeepSeek-R1 Protocol: Strip historical reasoning content from multi-turn messages
        if self.config.strip_deepseek_reasoning and (is_deepseek or not (is_anthropic or is_gemini)):
            for i, msg in enumerate(request.messages[:-1]):
                if msg.role == "assistant":
                    # Remove reasoning_content metadata
                    if "reasoning_content" in msg.metadata:
                        r_text = str(msg.metadata.pop("reasoning_content", ""))
                        tokens_reclaimed += estimate_tokens_from_text(r_text)
                    # Strip <think> tags if embedded in content string
                    if isinstance(msg.content, str) and "<think" in msg.content:
                        cleaned = self.THINK_TAG_REGEX.sub("", msg.content).strip()
                        if cleaned != msg.content:
                            tokens_reclaimed += estimate_tokens_from_text(msg.content) - estimate_tokens_from_text(cleaned)
                            msg.content = cleaned

        # 2. Google Gemini Protocol: Strip historical thought parts
        if self.config.strip_gemini_thought and is_gemini:
            for i, msg in enumerate(request.messages[:-1]):
                if msg.role == "assistant":
                    if isinstance(msg.content, str) and "<thought" in msg.content:
                        cleaned = re.sub(r"<thought>[\s\S]*?<\/thought>", "", msg.content, flags=re.IGNORECASE).strip()
                        if cleaned != msg.content:
                            tokens_reclaimed += estimate_tokens_from_text(msg.content) - estimate_tokens_from_text(cleaned)
                            msg.content = cleaned

        # 3. Anthropic Protocol: Adaptive lifecycle management
        if is_anthropic:
            total_thinking_tokens = 0
            thinking_blocks_found = []

            for m_idx, msg in enumerate(request.messages[:-1]):
                if msg.role == "assistant" and isinstance(msg.content, list):
                    for b_idx, block in enumerate(msg.content):
                        if isinstance(block, dict) and block.get("type") == "thinking":
                            th_text = str(block.get("thinking", ""))
                            toks = estimate_tokens_from_text(th_text)
                            total_thinking_tokens += toks
                            thinking_blocks_found.append((m_idx, b_idx, toks))

            # Trigger compaction if accumulated thinking exceeds configured limit or on cold recompact
            if was_cold or total_thinking_tokens > self.config.anthropic_max_thinking_tokens:
                for m_idx, msg in enumerate(request.messages[:-1]):
                    if msg.role == "assistant" and isinstance(msg.content, list):
                        new_content = []
                        for block in msg.content:
                            if isinstance(block, dict) and block.get("type") == "thinking":
                                continue
                            new_content.append(block)
                        msg.content = new_content
                tokens_reclaimed += total_thinking_tokens

        return tokens_reclaimed
