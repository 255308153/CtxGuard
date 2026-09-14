"""OpenAI chat completion protocol adapter."""

from typing import Any, Dict, List
from ctxguard.core.context import Message, NormalizedRequest, NormalizedResponse
from ctxguard.proxy.adapters.base import BaseAdapter


class OpenAIAdapter(BaseAdapter):
    """Adapter for OpenAI /v1/chat/completions schema."""

    @property
    def protocol_name(self) -> str:
        return "openai"

    def parse_request(self, raw_body: Dict[str, Any], session_id: str = "default") -> NormalizedRequest:
        model = str(raw_body.get("model", "gpt-4o"))
        stream = bool(raw_body.get("stream", False))
        temperature = raw_body.get("temperature")
        max_tokens = raw_body.get("max_tokens") or raw_body.get("max_completion_tokens")
        tools = raw_body.get("tools")
        tool_choice = raw_body.get("tool_choice")

        messages: List[Message] = []
        raw_msgs = raw_body.get("messages", [])
        for m in raw_msgs:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                name = m.get("name")
                tool_call_id = m.get("tool_call_id")
                tool_calls = m.get("tool_calls")
                meta = {k: v for k, v in m.items() if k not in ("role", "content", "name", "tool_call_id", "tool_calls")}
                messages.append(Message(
                    role=role,
                    content=content,
                    name=name,
                    tool_call_id=tool_call_id,
                    tool_calls=tool_calls,
                    metadata=meta,
                ))

        return NormalizedRequest(
            protocol="openai",
            model=model,
            messages=messages,
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
            "stream": request.stream,
        }

        for m in request.messages:
            msg_dict: Dict[str, Any] = {
                "role": m.role,
                "content": m.content,
            }
            if m.name:
                msg_dict["name"] = m.name
            if m.tool_call_id:
                msg_dict["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                msg_dict["tool_calls"] = m.tool_calls
            if m.metadata:
                msg_dict.update(m.metadata)
            payload["messages"].append(msg_dict)

        if request.tools is not None:
            payload["tools"] = request.tools
        if request.tool_choice is not None:
            payload["tool_choice"] = request.tool_choice
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        # Preserve other custom fields from raw_payload
        for k, v in request.raw_payload.items():
            if k not in payload:
                payload[k] = v

        return payload

    def parse_response(self, raw_response: Dict[str, Any]) -> NormalizedResponse:
        resp_id = str(raw_response.get("id", ""))
        model = str(raw_response.get("model", ""))
        choices = raw_response.get("choices", [])
        content = ""
        tool_calls = None

        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message", {})
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls")

        usage = raw_response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        return NormalizedResponse(
            protocol="openai",
            id=resp_id,
            model=model,
            content=content,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw_response=raw_response,
        )
