"""Plugins subsystem for CtxGuard."""

from ctxguard.plugins.base import BasePlugin
from ctxguard.plugins.onnx.scorer import SemanticPruner

__all__ = [
    "BasePlugin",
    "SemanticPruner",
]
