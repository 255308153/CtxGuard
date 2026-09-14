"""Server-Sent Events (SSE) stream parser and pass-through generator with thought isolation."""

import json
from typing import AsyncIterator


class SSEStreamHandler:
    """Handles Server-Sent Events stream passing, thought isolation, and real-time metrics collection."""

    @classmethod
    async def passthrough_stream(cls, byte_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        """Stream byte chunks directly to the HTTP client with real-time thought block separation."""
        in_thinking = False

        async for raw_bytes in byte_stream:
            text = raw_bytes.decode("utf-8", errors="replace")
            lines = text.split("\n")

            out_lines = []
            for line in lines:
                if not line.startswith("data: ") or line.strip() == "data: [DONE]":
                    out_lines.append(line)
                    continue

                json_str = line[6:].strip()
                try:
                    data = json.loads(json_str)
                    choices = data.get("choices", [])
                    if choices and isinstance(choices[0], dict):
                        delta = choices[0].get("delta", {})
                        content = delta.get("content", "")

                        if content and isinstance(content, str):
                            if "<think>" in content or "<thought>" in content:
                                in_thinking = True
                                content = content.replace("<think>", "").replace("<thought>", "")

                            if "</think>" in content or "</thought>" in content:
                                in_thinking = False
                                parts = content.replace("</thought>", "</think>").split("</think>")
                                if parts[0]:
                                    delta["reasoning_content"] = parts[0]
                                    delta.pop("content", None)
                                    out_lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
                                if len(parts) > 1 and parts[1]:
                                    data["choices"][0]["delta"] = {"content": parts[1]}
                                    out_lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
                                continue

                            if in_thinking:
                                delta["reasoning_content"] = content
                                delta.pop("content", None)
                                out_lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
                                continue

                    out_lines.append(line)
                except Exception:
                    out_lines.append(line)

            yield ("\n".join(out_lines)).encode("utf-8")
