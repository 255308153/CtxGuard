"""Local interceptor and executor for virtual tools like ctx_expand."""

import json
from typing import Any, Dict, Optional, Tuple
from ctxguard.core.context import NormalizedRequest, NormalizedResponse
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class VirtualToolExecutor:
    """Intercepts and locally fulfills virtual tool calls with 0 upstream LLM tokens."""

    def __init__(self, fingerprint_repo: Optional[FingerprintRepository] = None):
        self.fingerprint_repo = fingerprint_repo

    def check_and_execute(
        self, request: NormalizedRequest
    ) -> Optional[NormalizedResponse]:
        """Check if request contains a call to ctx_expand, and if so, fulfill it locally."""
        if not request.messages:
            return None

        # Check latest message for tool calls (OpenAI) or tool_use blocks (Anthropic)
        last_msg = request.messages[-1]

        # Case 1: OpenAI tool_calls in assistant message
        if last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                fn = tc.get("function", {})
                if fn.get("name") == "ctx_expand":
                    call_id = tc.get("id", "call_ctx_expand")
                    args_str = fn.get("arguments", "{}")
                    try:
                        args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    except Exception:
                        args = {}
                    ref_id = args.get("ref_id", "")
                    content = self._expand(ref_id)
                    return self._build_openai_tool_response(request, call_id, content)

        # Case 2: Anthropic tool_use content blocks
        if isinstance(last_msg.content, list):
            for block in last_msg.content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    if block.get("name") == "ctx_expand":
                        tool_use_id = block.get("id", "toolu_ctx_expand")
                        input_data = block.get("input", {})
                        ref_id = input_data.get("ref_id", "")
                        content = self._expand(ref_id)
                        return self._build_anthropic_tool_response(request, tool_use_id, content)

        return None

    def _expand(self, ref_id: str) -> str:
        """Fetch decompressed content from fingerprint repository."""
        if not ref_id:
            return "Error: Empty ref_id provided."

        if self.fingerprint_repo:
            found = self.fingerprint_repo.get_content(ref_id)
            if found:
                return found

        return f"Error: Reference '{ref_id}' not found in fingerprint store."

    def _build_openai_tool_response(
        self, request: NormalizedRequest, call_id: str, content: str
    ) -> NormalizedResponse:
        raw_resp = {
            "id": f"chatcmpl_local_expand_{call_id}",
            "object": "chat.completion",
            "model": request.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": content,
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        return NormalizedResponse(
            protocol="openai",
            id=raw_resp["id"],
            model=request.model,
            content=content,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            raw_response=raw_resp,
        )

    def _build_anthropic_tool_response(
        self, request: NormalizedRequest, tool_use_id: str, content: str
    ) -> NormalizedResponse:
        raw_resp = {
            "id": f"msg_local_expand_{tool_use_id}",
            "type": "message",
            "role": "user",
            "model": request.model,
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": content,
                }
            ],
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
            },
        }
        return NormalizedResponse(
            protocol="anthropic",
            id=raw_resp["id"],
            model=request.model,
            content=content,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            raw_response=raw_resp,
        )
