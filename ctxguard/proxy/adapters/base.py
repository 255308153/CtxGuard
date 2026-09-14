"""Base class for bidirectional LLM protocol adapters."""

from abc import ABC, abstractmethod
from typing import Any, Dict
from ctxguard.core.context import NormalizedRequest, NormalizedResponse


class BaseAdapter(ABC):
    """Abstract protocol adapter converting between vendor JSON and NormalizedRequest/Response."""

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Protocol name identifier (e.g. 'openai', 'anthropic')."""
        pass

    @abstractmethod
    def parse_request(self, raw_body: Dict[str, Any], session_id: str = "default") -> NormalizedRequest:
        """Parse raw incoming HTTP JSON body into NormalizedRequest."""
        pass

    @abstractmethod
    def build_upstream_payload(self, request: NormalizedRequest) -> Dict[str, Any]:
        """Convert NormalizedRequest back into vendor-compliant JSON body for upstream."""
        pass

    @abstractmethod
    def parse_response(self, raw_response: Dict[str, Any]) -> NormalizedResponse:
        """Parse non-streaming upstream response JSON into NormalizedResponse."""
        pass
