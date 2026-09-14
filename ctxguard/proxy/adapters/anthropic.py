"""Anthropic messages protocol adapter."""

from typing import Any, Dict, List, Optional
from ctxguard.core.context import Message, NormalizedRequest, NormalizedResponse
from ctxguard.proxy.adapters.base import BaseAdapter


class AnthropicAdapter(BaseAdapter):
    """Adapter for Anthropic /v1/messages schema."""

    @property
    def protocol_name(self) -> str:
        return "anthropic"

    def parse_request(self, raw_body: Dict[str, Any], session_id: str = "default") -> NormalizedRequest:
        model = str(raw_body.get("model", "claude-3-5-sonnet-20241022"))
        stream = bool(raw_body.get("stream", False))
        temperature = raw_body.get("temperature")
        max_tokens = raw_body.get("max_tokens", 4096)
        system = raw_body.get("system")
        tools = raw_body.get("tools")
        tool_choice = raw_body.get("tool_choice")

        messages: List[Message] = []
        raw_msgs = raw_body.get("messages", [])
        for m in raw_msgs:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                messages.append(Message(
                    role=role,
                    content=content,
                ))

        system_str = None
        if isinstance(system, str):
            system_str = system
        elif isinstance(system, list):
            texts = [b.get("text", "") for b in system if isinstance(b, dict) and "text" in b]
            system_str = "\n".join(texts)

        return NormalizedRequest(
            protocol="anthropic",
            model=model,
            messages=messages,
            system=system_str,
            tools=tools,
            tool_choice=tool_choice,
            stream=stream,
            temperature=temperature,
            max_tokens=max_tokens,
            raw_payload=raw_body,
            session_id=session_id,
        )

    def build_upstream_payload(self, request: NormalizedRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": [],
            "max_tokens": request.max_tokens or 4096,
            "stream": request.stream,
        }

        # Handle system prompt
        if request.system:
            payload["system"] = request.system
        elif "system" in request.raw_payload:
            payload["system"] = request.raw_payload["system"]

        for m in request.messages:
            payload["messages"].append({
                "role": m.role,
                "content": m.content,
            })

        if request.tools is not None:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice
        if request.temperature is not None:
            payload["temperature"] = request.temperature

        # Retain other custom Anthropic parameters
        for k, v in request.raw_payload.items():
            if k not in payload and k not in {"messages", "system", "tools"}:
                payload[k] = v

        return payload

    def parse_response(self, raw_response: Dict[str, Any]) -> NormalizedResponse:
        resp_id = str(raw_response.get("id", ""))
        model = str(raw_response.get("model", ""))
        content_blocks = raw_response.get("content", [])
        content_text = ""
        tool_calls: List[Dict[str, Any]] = []

        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        content_text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        tool_calls.append(block)

        usage = raw_response.get("usage", {})
        prompt_tokens = usage.get("input_tokens", 0)
        completion_tokens = usage.get("output_tokens", 0)
        total_tokens = prompt_tokens + completion_tokens

        return NormalizedResponse(
            protocol="anthropic",
            id=resp_id,
            model=model,
            content=content_text,
            tool_calls=tool_calls if tool_calls else None,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw_response=raw_response,
        )
