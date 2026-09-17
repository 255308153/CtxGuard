"""Server-Sent Events (SSE) stream parser and transparent pass-through generator."""

from typing import AsyncIterator, Callable, Optional
import codecs
import orjson
import uuid


class SSEStreamHandler:
    """Handles Server-Sent Events stream passing, conversion, and real-time metrics collection."""

    @classmethod
    def _parse_sse_line(cls, line: str) -> tuple[int, str, int, str, Optional[int]]:
        """Parse SSE line and extract (completion_tokens, finish_reason, cached_tokens, cache_type, prompt_tokens)."""
        tokens = 0
        finish_reason = ""
        cached_tokens = 0
        cache_type = "none"
        prompt_tokens: Optional[int] = None

        line_clean = line.strip()
        if not line_clean.startswith("data:"):
            return tokens, finish_reason, cached_tokens, cache_type, prompt_tokens

        data_str = line_clean[5:].strip()
        if data_str == "[DONE]":
            return tokens, "stop", cached_tokens, cache_type, prompt_tokens

        try:
            payload = orjson.loads(data_str)
            if not isinstance(payload, dict):
                return tokens, finish_reason, cached_tokens, cache_type, prompt_tokens

            # 1. Choices: delta content & finish_reason
            if "choices" in payload and isinstance(payload["choices"], list):
                for choice in payload["choices"]:
                    if isinstance(choice, dict):
                        finish_reason = choice.get("finish_reason") or finish_reason
                        delta = choice.get("delta", {})
                        if isinstance(delta, dict) and delta.get("content"):
                            tokens += 1

            # 2. Anthropic delta events
            if payload.get("type") == "content_block_delta":
                tokens += 1
            elif payload.get("type") in ("message_stop", "message_delta"):
                finish_reason = payload.get("stop_reason") or finish_reason or "stop"

            # 3. Usage dictionary (OpenAI, DeepSeek, Anthropic, vLLM, OneAPI, Codex Responses)
            usage = payload.get("usage")
            if not isinstance(usage, dict) and isinstance(payload.get("response"), dict):
                usage = payload["response"].get("usage")
            if isinstance(usage, dict):
                comp_tok = usage.get("completion_tokens") or usage.get("output_tokens")
                if comp_tok is not None:
                    tokens = int(comp_tok)

                p_tok = usage.get("prompt_tokens") or usage.get("input_tokens")
                if p_tok is not None:
                    prompt_tokens = int(p_tok)

                # 3a. DeepSeek: prompt_cache_hit_tokens
                if "prompt_cache_hit_tokens" in usage:
                    val = usage.get("prompt_cache_hit_tokens") or 0
                    if val > 0:
                        cached_tokens = val
                        cache_type = "deepseek_cache"

                # 3b. Anthropic: cache_read_input_tokens
                if cached_tokens == 0 and "cache_read_input_tokens" in usage:
                    val = usage.get("cache_read_input_tokens") or 0
                    if val > 0:
                        cached_tokens = val
                        cache_type = "anthropic_cache"
                    if prompt_tokens is not None:
                        prompt_tokens += val + (usage.get("cache_creation_input_tokens") or 0)

                # 3c. OpenAI / Gemini (via OpenAI compatibility) / Codex Responses: prompt_tokens_details or input_token_details
                if cached_tokens == 0:
                    details = (
                        usage.get("prompt_tokens_details")
                        or usage.get("input_token_details")
                        or usage.get("input_tokens_details")
                    )
                    if isinstance(details, dict):
                        val = details.get("cached_tokens") or details.get("cache_read_input_tokens") or 0
                        if val > 0:
                            cached_tokens = val
                            cache_type = "openai_cache"

                # 3d. Gemini direct usage field: cachedContentTokenCount
                if cached_tokens == 0:
                    val = usage.get("cachedContentTokenCount") or 0
                    if val > 0:
                        cached_tokens = val
                        cache_type = "gemini_cache"

            # 4. Anthropic native message_start event
            if payload.get("type") == "message_start":
                msg = payload.get("message", {})
                if isinstance(msg, dict):
                    m_usage = msg.get("usage", {})
                    if isinstance(m_usage, dict):
                        val = m_usage.get("cache_read_input_tokens") or 0
                        if val > 0:
                            cached_tokens = val
                            cache_type = "anthropic_cache"
                        inp = m_usage.get("input_tokens") or 0
                        prompt_tokens = inp + val + (m_usage.get("cache_creation_input_tokens") or 0)

            # 5. Gemini native API format: usageMetadata
            usage_meta = payload.get("usageMetadata")
            if isinstance(usage_meta, dict):
                if prompt_tokens is None:
                    g_p = usage_meta.get("promptTokenCount") or usage_meta.get("prompt_token_count")
                    if g_p is not None:
                        prompt_tokens = int(g_p)
                if cached_tokens == 0:
                    val = usage_meta.get("cachedContentTokenCount") or 0
                    if val > 0:
                        cached_tokens = val
                        cache_type = "gemini_cache"

        except Exception:
            pass

        return tokens, finish_reason, cached_tokens, cache_type, prompt_tokens

    @classmethod
    async def passthrough_stream(
        cls,
        byte_stream: AsyncIterator[bytes],
        on_complete: Optional[Callable[[int, str, Optional[int]], None]] = None,
        protocol: str = "openai",
        convert_to_responses: bool = False,
    ) -> AsyncIterator[bytes]:
        """Iterate over upstream byte stream, optionally convert ChatCompletions SSE to Responses SSE, and record metrics."""
        total_tokens = 0
        final_finish_reason = ""
        cached_tokens_total = 0
        cache_type_total = "none"
        prompt_tokens_total: Optional[int] = None
        state = {
            "created": False,
            "resp_id": f"resp_{uuid.uuid4().hex[:16]}",
            "item_id": f"item_{uuid.uuid4().hex[:16]}",
            "full_text": "",
        }
        pending = b""
        metrics_pending = ""
        metrics_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        try:
            async for chunk in byte_stream:
                if not chunk:
                    continue

                if convert_to_responses:
                    # SSE 事件可能跨越多个网络分块，必须按完整事件组装后再解析。
                    pending += chunk
                    frames = pending.split(b"\n\n")
                    pending = frames.pop()
                    events = []
                    for frame in frames:
                        events.extend(cls._transpile_chat_chunk_to_responses(frame + b"\n\n", state))
                    for ev in events:
                        yield ev
                else:
                    yield chunk

                # Calculate metrics in background with line buffering for split TCP chunks
                text = metrics_decoder.decode(chunk, final=False)
                if text:
                    metrics_pending += text
                    lines = metrics_pending.split("\n")
                    metrics_pending = lines.pop()  # Keep incomplete trailing line in buffer
                    for line in lines:
                        tokens, finish_reason, cached_tokens, cache_type, prompt_tokens = cls._parse_sse_line(line)
                        if tokens > 0:
                            total_tokens += tokens
                        if finish_reason:
                            final_finish_reason = finish_reason
                        if cached_tokens > 0:
                            cached_tokens_total = cached_tokens
                        if cache_type != "none":
                            cache_type_total = cache_type
                        if prompt_tokens is not None:
                            prompt_tokens_total = prompt_tokens

            # Flush any remaining decoder output and trailing line
            final_text = metrics_decoder.decode(b"", final=True)
            if final_text:
                metrics_pending += final_text
            if metrics_pending:
                for line in metrics_pending.split("\n"):
                    tokens, finish_reason, cached_tokens, cache_type, prompt_tokens = cls._parse_sse_line(line)
                    if tokens > 0:
                        total_tokens += tokens
                    if finish_reason:
                        final_finish_reason = finish_reason
                    if cached_tokens > 0:
                        cached_tokens_total = cached_tokens
                    if cache_type != "none":
                        cache_type_total = cache_type
                    if prompt_tokens is not None:
                        prompt_tokens_total = prompt_tokens

            if convert_to_responses and pending.strip():
                for ev in cls._transpile_chat_chunk_to_responses(pending, state):
                    yield ev
        finally:
            if convert_to_responses and not state.get("completed_sent"):
                for ev in cls._build_closing_events(state):
                    yield ev

            if on_complete:
                on_complete(cached_tokens_total, cache_type_total, prompt_tokens_total)

    @classmethod
    def _build_closing_events(cls, state: dict) -> list[bytes]:
        """Build all completion and done events required by Codex Responses API client."""
        closing_events: list[bytes] = []
        if state.get("completed_sent") or state.get("is_native_responses"):
            return closing_events
        if not state.get("created"):
            return closing_events
        # Never synthesize a fake empty completion if no content or tools were generated
        if not state.get("full_text") and not state.get("tool_calls"):
            return closing_events
        state["completed_sent"] = True

        # 1. Close message item if created and not yet closed
        if state.get("created") and not state.get("msg_done_sent"):
            state["msg_done_sent"] = True
            text_content = state.get("full_text", "")
            out_done = {
                "type": "response.output_text.done",
                "response_id": state["resp_id"],
                "item_id": state["item_id"],
                "output_index": 0,
                "content_index": 0,
                "text": text_content,
            }
            closing_events.append(f"event: response.output_text.done\ndata: {orjson.dumps(out_done).decode('utf-8')}\n\n".encode("utf-8"))

            part_done = {
                "type": "response.content_part.done",
                "response_id": state["resp_id"],
                "item_id": state["item_id"],
                "output_index": 0,
                "content_index": 0,
                "part": {"type": "output_text", "text": text_content},
            }
            closing_events.append(f"event: response.content_part.done\ndata: {orjson.dumps(part_done).decode('utf-8')}\n\n".encode("utf-8"))

            item_done = {
                "type": "response.output_item.done",
                "response_id": state["resp_id"],
                "output_index": 0,
                "item": {
                    "id": state["item_id"],
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": text_content}],
                },
            }
            closing_events.append(f"event: response.output_item.done\ndata: {orjson.dumps(item_done).decode('utf-8')}\n\n".encode("utf-8"))

        # 2. Close tool call items
        for tc in state.get("tool_calls", {}).values():
            if not tc.get("done_sent"):
                tc["done_sent"] = True
                arg_done = {
                    "type": "response.function_call_arguments.done",
                    "response_id": state["resp_id"],
                    "item_id": tc["id"],
                    "output_index": tc["output_index"],
                    "call_id": tc["call_id"],
                    "arguments": tc["arguments"],
                }
                closing_events.append(f"event: response.function_call_arguments.done\ndata: {orjson.dumps(arg_done).decode('utf-8')}\n\n".encode("utf-8"))

                item_done = {
                    "type": "response.output_item.done",
                    "response_id": state["resp_id"],
                    "output_index": tc["output_index"],
                    "item": {
                        "id": tc["id"],
                        "type": "function_call",
                        "call_id": tc["call_id"],
                        "name": tc["name"],
                        "arguments": tc["arguments"],
                        "status": "completed",
                    },
                }
                closing_events.append(f"event: response.output_item.done\ndata: {orjson.dumps(item_done).decode('utf-8')}\n\n".encode("utf-8"))

        # 3. Assemble response.completed output items
        output_items = [
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
        ]
        for tc in state.get("tool_calls", {}).values():
            output_items.append({
                "id": tc["id"],
                "type": "function_call",
                "call_id": tc["call_id"],
                "name": tc["name"],
                "arguments": tc["arguments"],
                "status": "completed",
            })

        comp_event = {
            "type": "response.completed",
            "response": {
                "id": state["resp_id"],
                "object": "response",
                "status": "completed",
                "output": output_items,
            },
        }
        closing_events.append(f"event: response.completed\ndata: {orjson.dumps(comp_event).decode('utf-8')}\n\n".encode("utf-8"))
        closing_events.append(b"data: [DONE]\n\n")
        return closing_events

    @classmethod
    def _transpile_chat_chunk_to_responses(cls, chunk_bytes: bytes, state: dict) -> list[bytes]:
        """Convert OpenAI chat.completion chunks to Codex responses SSE stream format."""
        text = chunk_bytes.decode("utf-8", errors="ignore")
        lines = text.split("\n")
        out_events: list[bytes] = []

        # 原生 Responses API 流无需转换，完整保留中转站的事件名称与扩展字段。
        for line in lines:
            line_clean = line.strip()
            if not line_clean.startswith("data:"):
                continue
            try:
                payload = orjson.loads(line_clean[5:].strip())
            except Exception:
                continue
            if isinstance(payload, dict) and (
                "response" in payload
                or payload.get("type", "").startswith("response.")
                or payload.get("type", "").startswith("codex.")
                or "item" in payload
            ):
                state["is_native_responses"] = True
                if payload.get("type") == "response.completed":
                    state["completed_sent"] = True
                return [chunk_bytes]

        for line in lines:
            line_clean = line.strip()
            if not line_clean or not line_clean.startswith("data:"):
                continue

            data_str = line_clean[5:].strip()
            if data_str == "[DONE]":
                out_events.extend(cls._build_closing_events(state))
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

                    tool_calls = delta.get("tool_calls")
                    if tool_calls and isinstance(tool_calls, list):
                        if "tool_calls" not in state:
                            state["tool_calls"] = {}
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue
                            idx = tc.get("index", 0)
                            if idx not in state["tool_calls"]:
                                fn = tc.get("function", {})
                                fn_name = fn.get("name", "")
                                call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:16]}"
                                item_id = f"item_{uuid.uuid4().hex[:16]}"
                                out_idx = len(state["tool_calls"]) + 1
                                state["tool_calls"][idx] = {
                                    "id": item_id,
                                    "call_id": call_id,
                                    "name": fn_name,
                                    "arguments": "",
                                    "output_index": out_idx,
                                }
                                fn_added = {
                                    "type": "response.output_item.added",
                                    "response_id": state["resp_id"],
                                    "output_index": out_idx,
                                    "item": {
                                        "id": item_id,
                                        "type": "function_call",
                                        "call_id": call_id,
                                        "name": fn_name,
                                        "arguments": "",
                                    },
                                }
                                out_events.append(f"event: response.output_item.added\ndata: {orjson.dumps(fn_added).decode('utf-8')}\n\n".encode("utf-8"))

                            tc_state = state["tool_calls"][idx]
                            fn = tc.get("function", {})
                            if isinstance(fn, dict):
                                if fn.get("name") and not tc_state["name"]:
                                    tc_state["name"] = fn["name"]
                                args_delta = fn.get("arguments", "")
                                if args_delta:
                                    tc_state["arguments"] += args_delta
                                    fn_arg_delta = {
                                        "type": "response.function_call_arguments.delta",
                                        "response_id": state["resp_id"],
                                        "item_id": tc_state["id"],
                                        "output_index": tc_state["output_index"],
                                        "call_id": tc_state["call_id"],
                                        "delta": args_delta,
                                    }
                                    out_events.append(f"event: response.function_call_arguments.delta\ndata: {orjson.dumps(fn_arg_delta).decode('utf-8')}\n\n".encode("utf-8"))

        return out_events
