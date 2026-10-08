"""Virtual tool schema injector for OpenAI and Anthropic protocols."""

from typing import Any, Dict, List, Sequence, Tuple
from ctxguard.config.schema import ToolInjectionConfig
from ctxguard.core.context import NormalizedRequest


#: Scope values the memory tools advertise. Kept in sync with MemoryScope.PROJECT etc.;
#: a value offered here but unrepresentable in storage is a silent mis-filing bug.
_MEMORY_SCOPE_ENUM = ["USER", "PROJECT", "SESSION"]


class VirtualToolInjector:
    """Injects virtual tool definitions (ctx_expand, memory_save, memory_search) into requests."""

    def __init__(self, config: ToolInjectionConfig):
        self.config = config

    @staticmethod
    def _define(
        protocol: str,
        name: str,
        description: str,
        properties: Dict[str, Any],
        required: Sequence[str],
    ) -> Dict[str, Any]:
        """Render one tool definition in the shape the given protocol expects.

        Both protocols differ only in where the schema lives (``input_schema`` at the top
        level for Anthropic versus ``parameters`` nested under ``function`` for OpenAI),
        so the definition is built once here. Three hand-written copies of this structure
        is how the tools drifted apart in the first place.
        """
        schema = {
            "type": "object",
            "properties": properties,
            "required": list(required),
        }
        if protocol == "anthropic":
            return {"name": name, "description": description, "input_schema": schema}
        return {
            "type": "function",
            "function": {"name": name, "description": description, "parameters": schema},
        }

    def _ctx_expand_schema(self, protocol: str) -> Dict[str, Any]:
        return self._define(
            protocol,
            self.config.tool_name,
            self.config.description,
            {
                "ref_id": {
                    "type": "string",
                    "description": "The sha256 reference hash identifier to expand.",
                }
            },
            ["ref_id"],
        )

    @staticmethod
    def _memory_save_schema(protocol: str) -> Dict[str, Any]:
        return VirtualToolInjector._define(
            protocol,
            "memory_save",
            "Save important user facts, technology preferences, or environment details to persistent memory.",
            {
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
                    "enum": list(_MEMORY_SCOPE_ENUM),
                    "description": "Memory scope level.",
                },
            },
            ["fact"],
        )

    @staticmethod
    def _memory_search_schema(protocol: str) -> Dict[str, Any]:
        return VirtualToolInjector._define(
            protocol,
            "memory_search",
            "Search previously saved memories and preferences before asking the user to repeat themselves.",
            {
                "query": {
                    "type": "string",
                    "description": "Keyword or phrase to look up in persistent memory.",
                },
                "scope": {
                    "type": "string",
                    "enum": list(_MEMORY_SCOPE_ENUM),
                    "description": "Optional scope filter; omit to search every scope.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matches to return (default 5).",
                },
            },
            ["query"],
        )

    def _tool_builders(self) -> List[Tuple[str, Any]]:
        """(name, builder) pairs, in injection order.

        The name is listed separately from the builder so the already-injected check uses
        the same string that ends up in the payload — deriving it from the rendered dict
        would silently skip a tool whose name differs per protocol.
        """
        return [
            (self.config.tool_name, self._ctx_expand_schema),
            ("memory_save", self._memory_save_schema),
            ("memory_search", self._memory_search_schema),
        ]

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

        for name, builder in self._tool_builders():
            if not name or name in existing_names:
                continue
            request.tools.append(builder(request.protocol))
