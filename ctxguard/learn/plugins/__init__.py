"""Plugin registry for CtxGuard Learn Engine."""

from __future__ import annotations
from typing import Dict, List, Optional
from ctxguard.learn.plugins.base import LearnPlugin
from ctxguard.learn.plugins.claude import ClaudePlugin
from ctxguard.learn.plugins.ctxguard_gateway import CtxGuardGatewayPlugin
from ctxguard.learn.plugins.gemini_codex import GeminiPlugin, CodexPlugin


class PluginRegistry:
    """Central registry of agent and traffic source plugins."""

    _plugins: Dict[str, LearnPlugin] = {}

    @classmethod
    def register(cls, plugin: LearnPlugin) -> None:
        cls._plugins[plugin.id] = plugin

    @classmethod
    def get(cls, plugin_id: str) -> Optional[LearnPlugin]:
        return cls._plugins.get(plugin_id)

    @classmethod
    def list_plugins(cls) -> List[LearnPlugin]:
        return list(cls._plugins.values())

    @classmethod
    def init_default_plugins(cls) -> None:
        if not cls._plugins:
            cls.register(ClaudePlugin())
            cls.register(CtxGuardGatewayPlugin())
            cls.register(GeminiPlugin())
            cls.register(CodexPlugin())


PluginRegistry.init_default_plugins()
