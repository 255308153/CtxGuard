"""Abstract base class for all CtxGuard compression and cleaning operators."""

from abc import ABC, abstractmethod
from ctxguard.core.context import RequestContext, Message


class BaseCompressor(ABC):
    """Unified compressor interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique operator identifier."""
        pass

    @abstractmethod
    def is_applicable(self, context: RequestContext) -> bool:
        """Evaluate if the compressor should run for this request."""
        pass

    @abstractmethod
    def compress_text(self, text: str) -> str:
        """Apply operator logic to a single text string."""
        pass

    def process(self, context: RequestContext, target_messages: list[Message]) -> None:
        """Process target messages in place."""
        for msg in target_messages:
            text = msg.get_text_content()
            if text:
                optimized = self.compress_text(text)
                if optimized != text:
                    msg.set_text_content(optimized)
                    if self.name not in context.applied_compressors:
                        context.applied_compressors.append(self.name)
