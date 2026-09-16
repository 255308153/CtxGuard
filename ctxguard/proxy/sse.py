"""Server-Sent Events (SSE) stream parser and transparent pass-through generator."""

from typing import AsyncIterator, Callable, Optional
import orjson


class SSEStreamHandler:
    """Handles Server-Sent Events stream passing and real-time metrics collection."""

    @classmethod
    async def passthrough_stream(
        cls,
        byte_stream: AsyncIterator[bytes],
        on_complete: Optional[Callable[[int, str], None]] = None,
        protocol: str = "openai",
    ) -> AsyncIterator[bytes]:
        """Stream byte chunks directly to the HTTP client while inspecting cache usage."""
        cached_tokens = 0
        cache_type = "none"

        buffer = ""
        async for chunk in byte_stream:
            if chunk:
                if on_complete:
                    try:
                        text = chunk.decode("utf-8", errors="ignore")
                        buffer += text
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if line.startswith("data: ") and line != "data: [DONE]":
                                raw_json = line[6:]
                                try:
                                    payload = orjson.loads(raw_json)
                                    if isinstance(payload, dict):
                                        # Anthropic message_start event
                                        if payload.get("type") == "message_start":
                                            msg_obj = payload.get("message", {})
                                            usage = msg_obj.get("usage", {})
                                            read_tokens = usage.get("cache_read_input_tokens", 0)
                                            if read_tokens > 0:
                                                cached_tokens = read_tokens
                                                cache_type = "anthropic_cache"
                                        # OpenAI / DeepSeek usage
                                        usage = payload.get("usage")
                                        if isinstance(usage, dict):
                                            if "prompt_cache_hit_tokens" in usage and usage["prompt_cache_hit_tokens"] > 0:
                                                cached_tokens = usage["prompt_cache_hit_tokens"]
                                                cache_type = "deepseek_cache"
                                            elif "prompt_tokens_details" in usage:
                                                c_val = usage["prompt_tokens_details"].get("cached_tokens", 0)
                                                if c_val > 0:
                                                    cached_tokens = c_val
                                                    cache_type = "openai_cache"
                                            elif usage.get("cache_read_input_tokens", 0) > 0:
                                                cached_tokens = usage["cache_read_input_tokens"]
                                                cache_type = "anthropic_cache"
                                            elif usage.get("cachedContentTokenCount", 0) > 0:
                                                cached_tokens = usage["cachedContentTokenCount"]
                                                cache_type = "gemini_cache"

                                        # Gemini native SSE: usageMetadata
                                        usage_meta = payload.get("usageMetadata")
                                        if isinstance(usage_meta, dict):
                                            g_val = usage_meta.get("cachedContentTokenCount") or 0
                                            if g_val > 0:
                                                cached_tokens = g_val
                                                cache_type = "gemini_cache"
                                except Exception:
                                    pass
                    except Exception:
                        pass
                yield chunk

        if on_complete:
            try:
                on_complete(cached_tokens, cache_type)
            except Exception:
                pass

