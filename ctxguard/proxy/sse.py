"""Server-Sent Events (SSE) stream parser and transparent pass-through generator."""

from typing import AsyncIterator, Callable, Optional
import orjson


class SSEStreamHandler:
    """Handles Server-Sent Events stream passing and real-time metrics collection."""

    @classmethod
    def _parse_sse_line(cls, line: str) -> tuple[int, str, int]:
        """Parse a single SSE line for usage / cache tokens and total prompt tokens across providers."""
        cached_tokens = 0
        cache_type = "none"
        prompt_tokens = 0
        line = line.strip()
        if not line.startswith("data:"):
            return 0, "none", 0
        raw_json = line[5:].strip()
        if not raw_json or raw_json == "[DONE]":
            return 0, "none", 0
        try:
            payload = orjson.loads(raw_json)
            if isinstance(payload, dict):
                # Anthropic message_start event
                if payload.get("type") == "message_start":
                    msg_obj = payload.get("message", {})
                    usage = msg_obj.get("usage", {})
                    read_tokens = usage.get("cache_read_input_tokens", 0)
                    inp_tokens = usage.get("input_tokens", 0) + read_tokens + usage.get("cache_creation_input_tokens", 0)
                    if read_tokens > 0:
                        return read_tokens, "anthropic_cache", inp_tokens
                    elif inp_tokens > 0:
                        return 0, "none", inp_tokens

                # OpenAI / DeepSeek usage
                usage = payload.get("usage")
                if isinstance(usage, dict):
                    p_tok = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
                    if "prompt_cache_hit_tokens" in usage and usage["prompt_cache_hit_tokens"] > 0:
                        return usage["prompt_cache_hit_tokens"], "deepseek_cache", p_tok
                    elif "prompt_tokens_details" in usage:
                        c_val = usage["prompt_tokens_details"].get("cached_tokens", 0)
                        if c_val > 0:
                            return c_val, "openai_cache", p_tok
                    elif usage.get("cache_read_input_tokens", 0) > 0:
                        return usage["cache_read_input_tokens"], "anthropic_cache", p_tok
                    elif usage.get("cachedContentTokenCount", 0) > 0:
                        return usage["cachedContentTokenCount"], "gemini_cache", p_tok
                    elif p_tok > 0:
                        return 0, "none", p_tok

                # Gemini native SSE: usageMetadata
                usage_meta = payload.get("usageMetadata")
                if isinstance(usage_meta, dict):
                    g_val = usage_meta.get("cachedContentTokenCount") or 0
                    g_prompt = usage_meta.get("promptTokenCount") or usage_meta.get("prompt_token_count") or 0
                    if g_val > 0:
                        return g_val, "gemini_cache", g_prompt
                    elif g_prompt > 0:
                        return 0, "none", g_prompt
        except Exception:
            pass
        return cached_tokens, cache_type, prompt_tokens

    @classmethod
    async def passthrough_stream(
        cls,
        byte_stream: AsyncIterator[bytes],
        on_complete: Optional[Callable[[int, str, Optional[int]], None]] = None,
        protocol: str = "openai",
    ) -> AsyncIterator[bytes]:
        """Stream byte chunks directly to the HTTP client while inspecting cache usage."""
        cached_tokens = 0
        cache_type = "none"
        prompt_tokens = 0

        buffer = ""
        try:
            async for chunk in byte_stream:
                if chunk:
                    if on_complete:
                        try:
                            text = chunk.decode("utf-8", errors="ignore")
                            buffer += text
                            while "\n" in buffer:
                                line, buffer = buffer.split("\n", 1)
                                c_tok, c_tp, p_tok = cls._parse_sse_line(line)
                                if c_tok > 0:
                                    cached_tokens, cache_type = c_tok, c_tp
                                if p_tok > 0:
                                    prompt_tokens = p_tok
                        except Exception:
                            pass
                    yield chunk
        finally:
            if on_complete:
                try:
                    # Flush any remaining line in buffer
                    if buffer.strip():
                        c_tok, c_tp, p_tok = cls._parse_sse_line(buffer)
                        if c_tok > 0:
                            cached_tokens, cache_type = c_tok, c_tp
                        if p_tok > 0:
                            prompt_tokens = p_tok
                    on_complete(cached_tokens, cache_type, prompt_tokens if prompt_tokens > 0 else None)
                except Exception:
                    pass

