"""Thinking and Reasoning CoT Lifecycle Manager for multi-turn conversations across all frontier reasoning models (Claude 3.7+, DeepSeek-R1/R2, OpenAI o1/o3, Gemini 2.0/2.5, Grok 3, QwQ, Kimi, Doubao)."""

import re
from typing import Any, Dict, List, Optional
from ctxguard.config.schema import ThinkingManagerConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.utils.token_counter import estimate_tokens_from_text


class ThinkingManager:
    """Manages reasoning/thinking tokens across multi-turn sessions for all modern reasoning models."""

    # Matches <think>, <thinking>, <thought>, and similar XML CoT wrappers
    THINK_TAG_REGEX = re.compile(
        r"<(?:think|thinking|thought)>[\s\S]*?<\/(?:think|thinking|thought)>",
        re.IGNORECASE
    )

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
        is_anthropic = "anthropic" in provider_lower or "claude" in model_lower

        tokens_reclaimed = 0

        # 1. Universal OpenAI-compatible / Open-Source Reasoning Protocol:
        # Handles DeepSeek-R1/R2, OpenAI o1/o3/o3-mini, Gemini 2.0/2.5, Grok 3 Think, QwQ, Qwen-Max, Kimi, Doubao
        if self.config.strip_deepseek_reasoning or self.config.strip_gemini_thought:
            for i, msg in enumerate(request.messages[:-1]):
                if msg.role == "assistant":
                    # Remove reasoning_content metadata / attributes across all OpenAI-compatible endpoints
                    if "reasoning_content" in msg.metadata:
                        r_text = str(msg.metadata.pop("reasoning_content", ""))
                        tokens_reclaimed += estimate_tokens_from_text(r_text)
                    if hasattr(msg, "reasoning_content") and getattr(msg, "reasoning_content", None):
                        r_text = str(getattr(msg, "reasoning_content"))
                        tokens_reclaimed += estimate_tokens_from_text(r_text)
                        setattr(msg, "reasoning_content", None)

                    # Strip <think>, <thinking>, <thought> tags if embedded in text content
                    if isinstance(msg.content, str) and any(tag in msg.content.lower() for tag in ["<think", "<thought"]):
                        cleaned = self.THINK_TAG_REGEX.sub("", msg.content).strip()
                        if cleaned != msg.content:
                            tokens_reclaimed += estimate_tokens_from_text(msg.content) - estimate_tokens_from_text(cleaned)
                            msg.content = cleaned

                    # Handle list content (e.g. multi-modal or structured parts)
                    elif isinstance(msg.content, list):
                        new_content = []
                        for part in msg.content:
                            if isinstance(part, dict):
                                # Gemini thought part
                                if part.get("thought") is True:
                                    th_text = str(part.get("text", ""))
                                    tokens_reclaimed += estimate_tokens_from_text(th_text)
                                    continue
                                # Text block containing think/thought tags
                                if part.get("type") == "text" and isinstance(part.get("text"), str):
                                    text_val = part["text"]
                                    if "<think" in text_val.lower() or "<thought" in text_val.lower():
                                        cleaned_text = self.THINK_TAG_REGEX.sub("", text_val).strip()
                                        tokens_reclaimed += estimate_tokens_from_text(text_val) - estimate_tokens_from_text(cleaned_text)
                                        part["text"] = cleaned_text
                            new_content.append(part)
                        msg.content = new_content

        # 2. Anthropic Hybrid Extended Thinking Protocol (Claude 3.7 Sonnet / Claude 4)
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
