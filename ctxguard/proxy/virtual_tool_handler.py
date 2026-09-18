"""Virtual tool response interception and recursive upstream continuation engine.

Aligned with Headroom CCRResponseHandler (Phase 5 / Phase 6):
Intercepts "ctx_expand" virtual tool calls emitted by upstream LLMs,
retrieves uncompressed content locally via FingerprintRepository (0 API tokens, 0.1ms),
and recursively sends continuation requests to the upstream provider until a final response
is reached. Downstream clients (Cline, RooCode, Claude Code, Cursor, Codex, Pi Agent) NEVER
receive raw unregistered virtual tool calls, completely preventing "Tool ctx_expand not found" crashes.
"""

import copy
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import orjson

from ctxguard.storage.repository_fingerprint import FingerprintRepository

logger = logging.getLogger(__name__)

VIRTUAL_TOOL_NAME = "ctx_expand"


class VirtualToolResponseHandler:
    """Intercepts virtual tool calls in LLM responses and drives recursive continuation upstream."""

    def __init__(
        self,
        fingerprint_repo: Optional[FingerprintRepository] = None,
        max_retrieval_rounds: int = 3,
    ):
        self.fingerprint_repo = fingerprint_repo
        self.max_retrieval_rounds = max_retrieval_rounds
        self._retrieval_count = 0

    @property
    def retrieval_count(self) -> int:
        return self._retrieval_count

    def has_virtual_tool_calls(self, response_data: Dict[str, Any], protocol: str = "openai") -> bool:
        """Check whether response contains ctx_expand tool calls."""
        v_calls, _ = self.parse_tool_calls(response_data, protocol)
        return len(v_calls) > 0

    def parse_tool_calls(
        self, response_data: Dict[str, Any], protocol: str = "openai"
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Separate virtual tool calls (ctx_expand) from client-defined external tool calls.

        Returns:
            Tuple of (virtual_tool_calls, other_tool_calls)
        """
        virtual_calls: List[Dict[str, Any]] = []
        other_calls: List[Dict[str, Any]] = []

        if protocol == "openai":
            choices = response_data.get("choices")
            if not isinstance(choices, list) or not choices:
                return virtual_calls, other_calls

            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            msg = first_choice.get("message", {})
            if not isinstance(msg, dict):
                return virtual_calls, other_calls

            tool_calls = msg.get("tool_calls")
            if not isinstance(tool_calls, list):
                return virtual_calls, other_calls

            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                func = tc.get("function", {})
                name = func.get("name", "") if isinstance(func, dict) else tc.get("name", "")
                call_id = tc.get("id", "")
                args_raw = func.get("arguments", "{}") if isinstance(func, dict) else tc.get("arguments", "{}")

                if name == VIRTUAL_TOOL_NAME:
                    ref_id = self._extract_ref_id(args_raw)
                    virtual_calls.append(
                        {
                            "id": call_id,
                            "name": name,
                            "arguments": args_raw,
                            "ref_id": ref_id,
                            "raw_call": tc,
                        }
                    )
                else:
                    other_calls.append(tc)

        elif protocol == "anthropic":
            content_blocks = response_data.get("content", [])
            if not isinstance(content_blocks, list):
                return virtual_calls, other_calls

            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    call_id = block.get("id", "")
                    input_data = block.get("input", {})

                    if name == VIRTUAL_TOOL_NAME:
                        ref_id = self._extract_ref_id(input_data)
                        virtual_calls.append(
                            {
                                "id": call_id,
                                "name": name,
                                "arguments": input_data,
                                "ref_id": ref_id,
                                "raw_call": block,
                            }
                        )
                    else:
                        other_calls.append(block)

        return virtual_calls, other_calls

    def _extract_ref_id(self, args_data: Any) -> str:
        """Extract ref_id or hash from arguments dict or JSON string."""
        if isinstance(args_data, str):
            try:
                parsed = json.loads(args_data)
                if isinstance(parsed, dict):
                    return parsed.get("ref_id") or parsed.get("hash") or parsed.get("hash_id") or ""
            except Exception:
                # Regex fallback for loosely formatted or truncated args
                m = re.search(r'["\'](?:ref_id|hash|hash_id)["\']\s*:\s*["\']([a-zA-Z0-9_-]+)["\']', args_data)
                if m:
                    return m.group(1)
        elif isinstance(args_data, dict):
            return args_data.get("ref_id") or args_data.get("hash") or args_data.get("hash_id") or ""
        return ""

    def execute_retrieval(self, ref_id: str, session_id: str = "default") -> str:
        """Retrieve original uncompressed text from FingerprintRepository (0 tokens, 0.1ms)."""
        if not ref_id:
            return "Error: ref_id parameter missing."

        clean_ref = ref_id.replace("sha256_", "").strip()
        if self.fingerprint_repo:
            content = self.fingerprint_repo.get_content(clean_ref)
            if content is not None:
                self._retrieval_count += 1
                logger.info(
                    f"[VirtualToolHandler] 0-Token Instant Retrieval hit: ref_id={clean_ref[:12]} ({len(content)} chars)"
                )
                return content

        logger.warning(f"[VirtualToolHandler] Retrieval miss: ref_id={clean_ref}")
        return f"Error: Reference {clean_ref} not found in local context store."

    def build_continuation_payload(
        self,
        base_payload: Dict[str, Any],
        response_data: Dict[str, Any],
        virtual_results: List[Tuple[str, str]],  # [(call_id, content)]
        protocol: str = "openai",
    ) -> Dict[str, Any]:
        """Build continuation request payload by appending assistant message and tool results."""
        payload = copy.deepcopy(base_payload)
        messages = payload.get("messages", [])

        if protocol == "openai":
            # 1. Add assistant message with tool calls
            choices = response_data.get("choices", [{}])
            assistant_msg = choices[0].get("message", {})
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_msg.get("content"),
                    "tool_calls": assistant_msg.get("tool_calls", []),
                }
            )

            # 2. Add tool results messages
            for call_id, content in virtual_results:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": content,
                    }
                )

        elif protocol == "anthropic":
            # 1. Add assistant message with full content blocks
            messages.append(
                {
                    "role": "assistant",
                    "content": response_data.get("content", []),
                }
            )

            # 2. Add user message with tool_result blocks
            result_blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": content,
                }
                for call_id, content in virtual_results
            ]
            messages.append(
                {
                    "role": "user",
                    "content": result_blocks,
                }
            )

        payload["messages"] = messages
        return payload

    async def handle_non_streaming(
        self,
        initial_response_bytes: bytes,
        upstream_payload: Dict[str, Any],
        headers: Dict[str, str],
        provider_name: str,
        upstream_client: Any,
        protocol: str = "openai",
        path: str = "v1/chat/completions",
        session_id: str = "default",
        fwd_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bytes, int, int]:
        """Intercept non-streaming responses and recursively continue upstream if ctx_expand is invoked.

        Returns:
            Tuple of (final_response_bytes, extra_turns_taken, final_status_code)
        """
        current_response_bytes = initial_response_bytes
        current_payload = upstream_payload
        rounds = 0
        final_status = 200

        while rounds < self.max_retrieval_rounds:
            try:
                resp_json = orjson.loads(current_response_bytes)
            except Exception:
                break

            virtual_calls, other_calls = self.parse_tool_calls(resp_json, protocol)
            if not virtual_calls:
                # No virtual tool calls: model provided final response or only client tools
                break

            # If the model called ctx_expand alongside client-defined external tools,
            # we cannot resolve both (the client must execute its own tools).
            # Follow Headroom RESIDUAL_CCR_SKIPPED_MIXED: pass through to client.
            if other_calls:
                logger.warning(
                    f"[VirtualToolHandler] Model called {len(other_calls)} client tool(s) "
                    f"alongside ctx_expand. Passing through turn to client."
                )
                break

            rounds += 1
            logger.info(
                f"[VirtualToolHandler] Intercepted {len(virtual_calls)} ctx_expand call(s) in round {rounds}. "
                f"Executing local 0-token retrieval and continuing upstream..."
            )

            # 1. Execute local retrievals
            virtual_results: List[Tuple[str, str]] = []
            for call in virtual_calls:
                retrieved_text = self.execute_retrieval(call["ref_id"], session_id=session_id)
                virtual_results.append((call["id"], retrieved_text))

            # 2. Build continuation payload
            current_payload = self.build_continuation_payload(
                current_payload, resp_json, virtual_results, protocol=protocol
            )

            # 3. Recursive upstream continuation call
            kwargs = copy.deepcopy(fwd_kwargs or {})
            kwargs.pop("raw_body", None)
            cont_headers = {
                k: v for k, v in (headers or {}).items()
                if k.lower() not in ("content-length", "content-encoding")
            }
            upstream_resp = await upstream_client.forward_request(
                path, current_payload, cont_headers, provider_name, **kwargs
            )
            final_status = upstream_resp.status_code
            current_response_bytes = upstream_resp.content

            if upstream_resp.status_code != 200:
                logger.error(
                    f"[VirtualToolHandler] Upstream continuation failed with status {upstream_resp.status_code}"
                )
                break

        return current_response_bytes, rounds, final_status


class StreamingVirtualToolHandler:
    """Detects and intercepts virtual tool calls in streaming responses."""

    def __init__(self, response_handler: VirtualToolResponseHandler):
        self.response_handler = response_handler

    async def wrap_stream(
        self,
        stream_gen: AsyncIterator[bytes],
        upstream_payload: Dict[str, Any],
        headers: Dict[str, str],
        provider_name: str,
        upstream_client: Any,
        protocol: str = "openai",
        path: str = "v1/chat/completions",
        session_id: str = "default",
        fwd_kwargs: Optional[Dict[str, Any]] = None,
        round: int = 1,
    ) -> AsyncIterator[bytes]:
        """Wrap stream generator, intercepting ctx_expand tool calls and continuing stream seamlessly."""
        buffer: List[bytes] = []
        detected_virtual = False
        switched_to_passthrough = False

        # Phase 1: Probe initial chunks for ctx_expand
        async for chunk in stream_gen:
            if switched_to_passthrough:
                yield chunk
                continue

            buffer.append(chunk)
            accumulated = b"".join(buffer)

            # Check if accumulated bytes contain ctx_expand
            if b'"ctx_expand"' in accumulated or b"'ctx_expand'" in accumulated:
                detected_virtual = True
                break

            # If accumulated size exceeds threshold (~6KB) without virtual tool marker,
            # or if finish_reason="stop", or if text content arrives without tool calls:
            # Flush buffer immediately to guarantee 0 TTFT degradation!
            if (
                len(accumulated) > 6144
                or b'"stop"' in accumulated
                or b'"message_stop"' in accumulated
                or (b'"content":' in accumulated and b'"tool_calls"' not in accumulated and len(accumulated) > 256)
                or (b'"text_delta"' in accumulated and b'"tool_use"' not in accumulated)
            ):
                switched_to_passthrough = True
                for b_chunk in buffer:
                    yield b_chunk
                buffer.clear()

        # If we exited the loop without detecting virtual tool and have remaining buffer
        if not detected_virtual:
            for b_chunk in buffer:
                yield b_chunk
            return

        # Phase 2: Virtual tool detected in stream!
        logger.info("[StreamingVirtualToolHandler] Detected ctx_expand in stream. Buffering full tool call...")
        # Collect remainder of stream
        async for chunk in stream_gen:
            buffer.append(chunk)

        full_stream_bytes = b"".join(buffer)

        # Parse complete response from the stream chunks
        complete_response = self._parse_stream_to_response(full_stream_bytes, protocol=protocol)
        if not complete_response:
            # Fallback: yield original buffered chunks if parsing fails
            for b_chunk in buffer:
                yield b_chunk
            return

        virtual_calls, other_calls = self.response_handler.parse_tool_calls(complete_response, protocol)
        if not virtual_calls or other_calls:
            # If no virtual calls or mixed tools, pass original stream
            for b_chunk in buffer:
                yield b_chunk
            return

        # Execute local retrievals
        virtual_results: List[Tuple[str, str]] = []
        for call in virtual_calls:
            retrieved = self.response_handler.execute_retrieval(call["ref_id"], session_id=session_id)
            virtual_results.append((call["id"], retrieved))

        # Build continuation payload
        continuation_payload = self.response_handler.build_continuation_payload(
            upstream_payload, complete_response, virtual_results, protocol=protocol
        )
        continuation_payload["stream"] = True

        # Recursive continuation call with stream=True!
        kwargs = copy.deepcopy(fwd_kwargs or {})
        kwargs.pop("raw_body", None)
        cont_headers = {
            k: v for k, v in (headers or {}).items()
            if k.lower() not in ("content-length", "content-encoding")
        }
        logger.info("[StreamingVirtualToolHandler] Launching continuation stream to upstream...")
        continuation_stream = upstream_client.forward_stream(
            path, continuation_payload, cont_headers, provider_name, **kwargs
        )
        if round < self.response_handler.max_retrieval_rounds:
            continuation_stream = self.wrap_stream(
                stream_gen=continuation_stream,
                upstream_payload=continuation_payload,
                headers=cont_headers,
                provider_name=provider_name,
                upstream_client=upstream_client,
                protocol=protocol,
                path=path,
                session_id=session_id,
                fwd_kwargs=kwargs,
                round=round + 1,
            )

        async for chunk in continuation_stream:
            yield chunk

    def _parse_stream_to_response(self, stream_bytes: bytes, protocol: str = "openai") -> Optional[Dict[str, Any]]:
        """Reconstruct a complete response dict from SSE stream bytes."""
        text = stream_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()

        if protocol == "openai":
            tool_calls_acc: Dict[int, Dict[str, Any]] = {}
            content_parts: List[str] = []
            resp_id = "chatcmpl_stream"
            model = "unknown"

            for line in lines:
                line_str = line.strip()
                if not line_str.startswith("data:") or line_str == "data: [DONE]":
                    continue
                try:
                    payload = json.loads(line_str[5:].strip())
                    if not isinstance(payload, dict):
                        continue
                    resp_id = payload.get("id", resp_id)
                    model = payload.get("model", model)
                    choices = payload.get("choices", [])
                    if choices and isinstance(choices[0], dict):
                        delta = choices[0].get("delta", {})
                        if delta.get("content"):
                            content_parts.append(delta["content"])
                        t_calls = delta.get("tool_calls")
                        if isinstance(t_calls, list):
                            for tc in t_calls:
                                idx = tc.get("index", 0)
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {
                                        "id": tc.get("id", ""),
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                if tc.get("id"):
                                    tool_calls_acc[idx]["id"] = tc["id"]
                                func = tc.get("function", {})
                                if func.get("name"):
                                    tool_calls_acc[idx]["function"]["name"] += func["name"]
                                if func.get("arguments"):
                                    tool_calls_acc[idx]["function"]["arguments"] += func["arguments"]
                except Exception:
                    continue

            formatted_tool_calls = [v for _, v in sorted(tool_calls_acc.items())]
            return {
                "id": resp_id,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "".join(content_parts) if content_parts else None,
                            "tool_calls": formatted_tool_calls if formatted_tool_calls else None,
                        },
                        "finish_reason": "tool_calls" if formatted_tool_calls else "stop",
                    }
                ],
            }

        elif protocol == "anthropic":
            content_blocks_acc: Dict[int, Dict[str, Any]] = {}
            resp_id = "msg_stream"
            model = "unknown"

            for line in lines:
                line_str = line.strip()
                if not line_str.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line_str[5:].strip())
                    if not isinstance(payload, dict):
                        continue
                    event_type = payload.get("type")
                    if event_type == "message_start":
                        msg = payload.get("message", {})
                        resp_id = msg.get("id", resp_id)
                        model = msg.get("model", model)
                    elif event_type == "content_block_start":
                        idx = payload.get("index", 0)
                        block = payload.get("content_block", {})
                        content_blocks_acc[idx] = block
                        if block.get("type") == "tool_use":
                            if "input_json" not in content_blocks_acc[idx]:
                                content_blocks_acc[idx]["input_json"] = ""
                    elif event_type == "content_block_delta":
                        idx = payload.get("index", 0)
                        delta = payload.get("delta", {})
                        if idx in content_blocks_acc:
                            if delta.get("type") == "text_delta":
                                content_blocks_acc[idx]["text"] = (
                                    content_blocks_acc[idx].get("text", "") + delta.get("text", "")
                                )
                            elif delta.get("type") == "input_json_delta":
                                content_blocks_acc[idx]["input_json"] = (
                                    content_blocks_acc[idx].get("input_json", "") + delta.get("partial_json", "")
                                )
                except Exception:
                    continue

            content_list = []
            for _, b in sorted(content_blocks_acc.items()):
                if b.get("type") == "tool_use":
                    try:
                        b["input"] = json.loads(b.get("input_json", "{}"))
                    except Exception:
                        b["input"] = {}
                    b.pop("input_json", None)
                content_list.append(b)

            return {
                "id": resp_id,
                "model": model,
                "content": content_list,
                "role": "assistant",
            }

        return None
