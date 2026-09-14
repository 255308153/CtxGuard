"""Virtual tool schema injector for OpenAI and Anthropic protocols."""

from typing import Any, Dict, List, Optional
from ctxguard.config.schema import ToolInjectionConfig
from ctxguard.core.context import NormalizedRequest


class VirtualToolInjector:
    """Injects virtual tool definitions into normalized requests."""

    def __init__(self, config: ToolInjectionConfig):
        self.config = config

    def inject_schema(self, request: NormalizedRequest) -> None:
        """Inject ctx_expand tool schema if enabled and tools are present."""
        if not self.config.enabled:
            return

        # Only inject if client has tools defined
        if not request.tools:
            return

        tool_name = self.config.tool_name

        if request.tools:
            for t in request.tools:
                if isinstance(t, dict):
                    if t.get("name") == tool_name or t.get("function", {}).get("name") == tool_name:
                        return

        if request.protocol == "anthropic":
            tool_def = {
                "name": tool_name,
                "description": self.config.description,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ref_id": {
                            "type": "string",
                            "description": "The sha256 reference hash identifier to expand.",
                        }
                    },
                    "required": ["ref_id"],
                },
            }
        else:
            # OpenAI format
            tool_def = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": self.config.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ref_id": {
                                "type": "string",
                                "description": "The sha256 reference hash identifier to expand.",
                            }
                        },
                        "required": ["ref_id"],
                    },
                },
            }

        if request.tools is None:
            request.tools = []
        request.tools.append(tool_def)
