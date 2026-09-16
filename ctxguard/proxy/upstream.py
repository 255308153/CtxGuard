"""Upstream HTTP client managing connections, authentication, and streaming to LLM providers."""

import os
from typing import Any, AsyncIterator, Dict, Optional
import httpx

from ctxguard.config.schema import UpstreamConfig, ProviderConfig


class UpstreamClient:
    """High-performance async client for upstream LLM provider communication."""

    def __init__(self, config: UpstreamConfig, timeout_seconds: int = 180):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout_seconds, connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def resolve_provider(self, provider_name: Optional[str] = None) -> ProviderConfig:
        """Resolve ProviderConfig by name or default."""
        p_name = provider_name or self.config.default_provider
        if p_name in self.config.providers:
            return self.config.providers[p_name]
        return ProviderConfig(base_url="https://api.anthropic.com")

    def _resolve_api_key(self, provider: ProviderConfig, client_headers: Dict[str, str]) -> Optional[str]:
        """Resolve API key from client header, provider config, or environment variable."""
        # 1. Check client authorization header
        auth_header = client_headers.get("authorization") or client_headers.get("Authorization")
        if auth_header:
            if auth_header.startswith("Bearer "):
                return auth_header[7:].strip()
            return auth_header.strip()

        # Check x-api-key header
        x_api_key = client_headers.get("x-api-key") or client_headers.get("X-Api-Key")
        if x_api_key:
            return x_api_key.strip()

        # 2. Check provider direct api_key
        if provider.api_key:
            return provider.api_key

        # 3. Check provider api_key_env
        if provider.api_key_env and provider.api_key_env in os.environ:
            return os.environ[provider.api_key_env]

        return None

    def build_headers(
        self,
        protocol: str,
        provider: ProviderConfig,
        client_headers: Dict[str, str],
    ) -> Dict[str, str]:
        """Construct upstream request headers."""
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "CtxGuard-Proxy/0.1.0",
        }

        api_key = self._resolve_api_key(provider, client_headers)

        if protocol == "anthropic":
            if api_key:
                headers["x-api-key"] = api_key
            headers["anthropic-version"] = client_headers.get(
                "anthropic-version", "2023-06-01"
            )
            # Forward anthropic-beta if present
            beta = client_headers.get("anthropic-beta")
            if beta:
                headers["anthropic-beta"] = beta
        else:
            # OpenAI style
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        return headers

    def build_full_url(self, provider: ProviderConfig, url_path: str) -> str:
        """Construct normalized full URL avoiding duplicate /v1 segments."""
        base = provider.base_url.rstrip("/")
        path = url_path.lstrip("/")

        if base.endswith("/v1") and path.startswith("v1/"):
            path = path[3:].lstrip("/")

        return f"{base}/{path}"

    async def forward_request(
        self,
        url_path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        provider_name: Optional[str] = None,
        raw_body: Optional[bytes] = None,
    ) -> httpx.Response:
        """Send non-streaming request to upstream. If raw_body is provided, forwards raw bytes verbatim."""
        client = self.get_client()
        provider = self.resolve_provider(provider_name)
        full_url = self.build_full_url(provider, url_path)
        req_headers = headers or {}

        if raw_body is not None:
            response = await client.post(full_url, content=raw_body, headers=req_headers)
        else:
            response = await client.post(full_url, json=payload, headers=req_headers)
        return response

    async def forward_stream(
        self,
        url_path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        provider_name: Optional[str] = None,
        raw_body: Optional[bytes] = None,
    ) -> AsyncIterator[bytes]:
        """Stream request to upstream and yield raw byte chunks, ensuring errors are formatted cleanly.
        If raw_body is provided, forwards raw bytes verbatim without re-serialization.
        """
        client = self.get_client()
        provider = self.resolve_provider(provider_name)
        full_url = self.build_full_url(provider, url_path)
        req_headers = headers or {}

        try:
            req_kwargs = {"content": raw_body} if raw_body is not None else {"json": payload}
            async with client.stream("POST", full_url, headers=req_headers, **req_kwargs) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    error_text = body.decode("utf-8", errors="replace").strip()
                    error_payload = {
                        "error": {
                            "message": error_text or f"Upstream error {response.status_code}",
                            "type": "upstream_error",
                            "code": response.status_code,
                        }
                    }
                    import orjson
                    yield f"data: {orjson.dumps(error_payload).decode('utf-8')}\n\ndata: [DONE]\n\n".encode("utf-8")
                    return

                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except Exception as exc:
            import orjson
            error_payload = {
                "error": {
                    "message": f"CtxGuard stream connection error: {str(exc)}",
                    "type": "gateway_stream_error",
                    "code": 502,
                }
            }
            yield f"data: {orjson.dumps(error_payload).decode('utf-8')}\n\ndata: [DONE]\n\n".encode("utf-8")
