"""Abstract base class for CtxGuard plugins and optional extensions."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BasePlugin(ABC):
    """Lifecycle interface for extension plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique plugin identifier."""
        pass

    def initialize(self, config: Dict[str, Any]) -> None:
        """Called upon gateway startup to initialize resources."""
        pass

    def shutdown(self) -> None:
        """Called upon gateway teardown to clean up resources."""
        pass
