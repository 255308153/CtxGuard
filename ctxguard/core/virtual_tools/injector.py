"""Virtual tool schema injector for OpenAI and Anthropic protocols."""

from typing import Any, Dict, List, Optional
from ctxguard.config.schema import ToolInjectionConfig
from ctxguard.core.context import NormalizedRequest


class VirtualToolInjector:
    """Injects virtual tool definitions (ctx_expand, memory_save) into normalized requests."""

    def __init__(self, config: ToolInjectionConfig):
        self.config = config

    def inject_schema(self, request: NormalizedRequest) -> None:
        """Inject virtual tools schemas if enabled and not already present."""
        if not self.config.enabled:
            return

        if request.tools is None:
            request.tools = []

        existing_names = set()
        for t in request.tools:
            if isinstance(t, dict):
                name = t.get("name") or t.get("function", {}).get("name")
                if name:
                    existing_names.add(name)

        # 1. ctx_expand tool
        tool_name = self.config.tool_name
        if tool_name not in existing_names:
            if request.protocol == "anthropic":
                request.tools.append({
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
                })
            else:
                request.tools.append({
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
                })

        # 2. memory_save virtual tool (CtxGuard Engine aligned)
        if "memory_save" not in existing_names:
            if request.protocol == "anthropic":
                request.tools.append({
                    "name": "memory_save",
                    "description": "Save important user facts, technology preferences, or environment details to persistent memory.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "fact": {
                                "type": "string",
                                "description": "The atomic fact or preference to remember.",
                            },
                            "entity": {
                                "type": "string",
                                "description": "Target entity or subject (e.g. User, Python, MacOS, Project).",
                            },
                            "scope": {
                                "type": "string",
                                "enum": ["USER", "PROJECT", "SESSION"],
                                "description": "Memory scope level.",
                            },
                        },
                        "required": ["fact"],
                    },
                })
            else:
                request.tools.append({
                    "type": "function",
                    "function": {
                        "name": "memory_save",
                        "description": "Save important user facts, technology preferences, or environment details to persistent memory.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "fact": {
                                    "type": "string",
                                    "description": "The atomic fact or preference to remember.",
                                },
                                "entity": {
                                    "type": "string",
                                    "description": "Target entity or subject (e.g. User, Python, MacOS, Project).",
                                },
                                "scope": {
                                    "type": "string",
                                    "enum": ["USER", "PROJECT", "SESSION"],
                                    "description": "Memory scope level.",
                                },
                            },
                            "required": ["fact"],
                        },
                    },
                })
