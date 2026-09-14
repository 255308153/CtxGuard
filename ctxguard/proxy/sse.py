"""Server-Sent Events (SSE) stream parser and transparent pass-through generator."""

from typing import AsyncIterator


class SSEStreamHandler:
    """Handles Server-Sent Events stream passing and real-time metrics collection."""

    @classmethod
    async def passthrough_stream(cls, byte_stream: AsyncIterator[bytes]) -> AsyncIterator[bytes]:
        """Stream byte chunks directly to the HTTP client with 100% transparent framing preservation."""
        async for chunk in byte_stream:
            if chunk:
                yield chunk

