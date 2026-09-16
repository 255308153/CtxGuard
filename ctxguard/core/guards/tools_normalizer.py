"""Tools & JSON Schema Deterministic Normalizer for Context / Prompt Caching.

Ensures tools and their JSON schemas have deterministic, alphabetically sorted
structures, preventing prompt cache churn across identical client requests.
"""

from typing import Any, Dict, List, Optional
from ctxguard.core.context import NormalizedRequest


class ToolsNormalizer:
    """Recursively normalizes tool lists and parameter schemas into deterministic order."""

    @classmethod
    def normalize_schema(cls, obj: Any) -> Any:
        """Recursively sort dictionary keys in schema definitions."""
        if isinstance(obj, dict):
            # Sort keys alphabetically and normalize values recursively
            return {k: cls.normalize_schema(obj[k]) for k in sorted(obj.keys())}
        elif isinstance(obj, list):
            return [cls.normalize_schema(item) for item in obj]
        else:
            return obj

    @classmethod
    def get_tool_name(cls, tool: Dict[str, Any]) -> str:
        """Extract name from tool dictionary (handles both OpenAI and Anthropic formats)."""
        if not isinstance(tool, dict):
            return ""
        # OpenAI style: tool.get("function", {}).get("name")
        if "function" in tool and isinstance(tool["function"], dict):
            return tool["function"].get("name", "")
        # Anthropic or flat style: tool.get("name")
        return tool.get("name", "")

    @classmethod
    def normalize_tools(cls, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Sort tools by name and normalize inner schemas recursively."""
        if not tools:
            return tools

        normalized_tools = []
        for t in tools:
            if isinstance(t, dict):
                normalized_tools.append(cls.normalize_schema(t))
            else:
                normalized_tools.append(t)

        # Sort tools by extracted tool name
        normalized_tools.sort(key=lambda t: cls.get_tool_name(t) if isinstance(t, dict) else "")
        return normalized_tools

    @classmethod
    def normalize(cls, tools: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
        """Alias for normalize_tools."""
        return cls.normalize_tools(tools)

    def normalize_request_tools(self, request: NormalizedRequest) -> None:
        """In-place normalizer for tools on NormalizedRequest."""
        if request.tools is not None:
            request.tools = self.normalize_tools(request.tools)
