"""Server-Sent Events (SSE) stream parser and transparent pass-through generator."""

from typing import AsyncIterator, Callable, Optional
import orjson
import uuid


class SSEStreamHandler:
    """Handles Server-Sent Events stream passing, conversion, and real-time metrics collection."""

    @classmethod
    def _parse_sse_line(cls, line: str) -> tuple[int, str, int]:
        """Parse SSE line and extract token usage, finish_reason, or delta content."""
        tokens = 0
        finish_reason = ""
        cached_tokens = 0

        line_clean = line.strip()
        if not line_clean.startswith("data:"):
            return tokens, finish_reason, cached_tokens

        data_str = line_clean[5:].strip()
        if data_str == "[DONE]":
            return tokens, "stop", cached_tokens

        try:
            payload = orjson.loads(data_str)
            if not isinstance(payload, dict):
                return tokens, finish_reason, cached_tokens

            # Anthropic message_delta / usage
            if "usage" in payload and isinstance(payload["usage"], dict):
                usage = payload["usage"]
                tokens += usage.get("output_tokens", 0)
                tokens += usage.get("completion_tokens", 0)

            # OpenAI usage chunk
            if "choices" in payload and isinstance(payload["choices"], list):
                for choice in payload["choices"]:
                    if isinstance(choice, dict):
                        finish_reason = choice.get("finish_reason") or finish_reason
                        if choice.get("delta", {}).get("content"):
                            tokens += 1

            # Anthropic content_block_delta
            if payload.get("type") == "content_block_delta":
                tokens += 1

            # Anthropic message_stop
            if payload.get("type") == "message_stop":
                finish_reason = "stop"

            # Cache metrics
            if "prompt_tokens_details" in payload and isinstance(payload["prompt_tokens_details"], dict):
                cached_tokens = payload["prompt_tokens_details"].get("cached_tokens", 0)
            elif "usage" in payload and isinstance(payload["usage"], dict):
                cached_tokens = payload["usage"].get("cache_read_input_tokens", 0)

        except Exception:
            pass

        return tokens, finish_reason, cached_tokens

    @classmethod
    async def passthrough_stream(
        cls,
        byte_stream: AsyncIterator[bytes],
        on_complete: Optional[Callable[[int, str, Optional[int]], None]] = None,
        protocol: str = "openai",
        convert_to_responses: bool = False,
    ) -> AsyncIterator[bytes]:
        """Iterate over upstream byte stream, optionally convert ChatCompletions SSE to Responses SSE, and record total output tokens."""
        total_tokens = 0
        final_finish_reason = ""
        cached_tokens_total = 0
        state = {
            "created": False,
            "resp_id": f"resp_{uuid.uuid4().hex[:16]}",
            "item_id": f"item_{uuid.uuid4().hex[:16]}",
            "full_text": "",
        }

        try:
            async for chunk in byte_stream:
                if not chunk:
                    continue

                if convert_to_responses:
                    # Convert OpenAI chat.completion chunks to OpenAI Codex/Realtime responses stream
                    events = cls._transpile_chat_chunk_to_responses(chunk, state)
                    for ev in events:
                        yield ev
                else:
                    yield chunk

                # Calculate metrics in background
                text = chunk.decode("utf-8", errors="ignore")
                for line in text.split("\n"):
                    tokens, finish_reason, cached_tokens = cls._parse_sse_line(line)
                    total_tokens += tokens
                    if finish_reason:
                        final_finish_reason = finish_reason
                    if cached_tokens > 0:
                        cached_tokens_total = cached_tokens

        finally:
            if convert_to_responses and not state.get("completed_sent"):
                # Safety fallback: ensure response.completed is always sent even on abrupt finish
                comp_event = {
                    "type": "response.completed",
                    "response": {
                        "id": state["resp_id"],
                        "object": "response",
                        "status": "completed",
                        "output": [
                            {
                                "id": state["item_id"],
                                "type": "message",
                                "status": "completed",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": state.get("full_text", ""),
                                    }
                                ],
                            }
                        ],
                    },
                }
                yield f"event: response.completed\ndata: {orjson.dumps(comp_event).decode('utf-8')}\n\n".encode("utf-8")

            if on_complete:
                on_complete(total_tokens, final_finish_reason or "stop", cached_tokens_total)

    @classmethod
    def _transpile_chat_chunk_to_responses(cls, chunk_bytes: bytes, state: dict) -> list[bytes]:
        """Convert OpenAI chat.completion chunks to Codex responses SSE stream format."""
        text = chunk_bytes.decode("utf-8", errors="ignore")
        lines = text.split("\n")
        out_events: list[bytes] = []

        for line in lines:
            line_clean = line.strip()
            if not line_clean or not line_clean.startswith("data:"):
                continue

            data_str = line_clean[5:].strip()
            if data_str == "[DONE]":
                state["completed_sent"] = True
                comp_event = {
                    "type": "response.completed",
                    "response": {
                        "id": state["resp_id"],
                        "object": "response",
                        "status": "completed",
                        "output": [
                            {
                                "id": state["item_id"],
                                "type": "message",
                                "status": "completed",
                                "role": "assistant",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": state.get("full_text", ""),
                                    }
                                ],
                            }
                        ],
                    },
                }
                out_events.append(f"event: response.completed\ndata: {orjson.dumps(comp_event).decode('utf-8')}\n\n".encode("utf-8"))
                continue

            try:
                payload = orjson.loads(data_str)
                if not isinstance(payload, dict):
                    continue
            except Exception:
                continue

            if not state.get("created"):
                state["created"] = True
                if "id" in payload:
                    state["resp_id"] = payload["id"]
                # 1. response.created
                e1 = {
                    "type": "response.created",
                    "response": {
                        "id": state["resp_id"],
                        "object": "response",
                        "status": "in_progress",
                    },
                }
                out_events.append(f"event: response.created\ndata: {orjson.dumps(e1).decode('utf-8')}\n\n".encode("utf-8"))

                # 2. response.output_item.added
                e2 = {
                    "type": "response.output_item.added",
                    "response_id": state["resp_id"],
                    "output_index": 0,
                    "item": {
                        "id": state["item_id"],
                        "type": "message",
                        "status": "in_progress",
                        "role": "assistant",
                        "content": [],
                    },
                }
                out_events.append(f"event: response.output_item.added\ndata: {orjson.dumps(e2).decode('utf-8')}\n\n".encode("utf-8"))

                # 3. response.content_part.added
                e3 = {
                    "type": "response.content_part.added",
                    "response_id": state["resp_id"],
                    "item_id": state["item_id"],
                    "output_index": 0,
                    "content_index": 0,
                    "part": {"type": "output_text", "text": ""},
                }
                out_events.append(f"event: response.content_part.added\ndata: {orjson.dumps(e3).decode('utf-8')}\n\n".encode("utf-8"))

            choices = payload.get("choices", [])
            if choices and isinstance(choices, list):
                choice = choices[0]
                if isinstance(choice, dict):
                    delta = choice.get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        state["full_text"] += content
                        # response.output_text.delta
                        ed = {
                            "type": "response.output_text.delta",
                            "response_id": state["resp_id"],
                            "item_id": state["item_id"],
                            "output_index": 0,
                            "content_index": 0,
                            "delta": content,
                        }
                        out_events.append(f"event: response.output_text.delta\ndata: {orjson.dumps(ed).decode('utf-8')}\n\n".encode("utf-8"))
                        # response.text.delta (compatibility)
                        ed2 = {
                            "type": "response.text.delta",
                            "response_id": state["resp_id"],
                            "item_id": state["item_id"],
                            "output_index": 0,
                            "content_index": 0,
                            "delta": content,
                        }
                        out_events.append(f"event: response.text.delta\ndata: {orjson.dumps(ed2).decode('utf-8')}\n\n".encode("utf-8"))

        return out_events
