"""API route definitions for OpenAI and Anthropic proxy endpoints with persistence & virtual tools."""

import time
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
import orjson

from ctxguard.config.schema import AppConfig
from ctxguard.core.pipeline import CompressionPipeline
from ctxguard.core.virtual_tools.executor import VirtualToolExecutor
from ctxguard.proxy.adapters.openai import OpenAIAdapter
from ctxguard.proxy.adapters.anthropic import AnthropicAdapter
from ctxguard.proxy.upstream import UpstreamClient
from ctxguard.proxy.sse import SSEStreamHandler
from ctxguard.storage.repository_stats import StatsRepository
from ctxguard.storage.repository_fingerprint import FingerprintRepository


def create_router(
    config: AppConfig,
    pipeline: CompressionPipeline,
    upstream: UpstreamClient,
    stats_repo: Optional[StatsRepository] = None,
    fingerprint_repo: Optional[FingerprintRepository] = None,
) -> APIRouter:
    router = APIRouter()

    openai_adapter = OpenAIAdapter()
    anthropic_adapter = AnthropicAdapter()
    virtual_tool_executor = VirtualToolExecutor(fingerprint_repo=fingerprint_repo)

    @router.get("/health")
    async def health_check() -> Dict[str, str]:
        return {"status": "ok", "service": "CtxGuard", "version": "0.1.0"}

    @router.get("/v1/models")
    async def list_models() -> Dict[str, Any]:
        """Simple model list endpoint for OpenAI client compatibility."""
        return {
            "object": "list",
            "data": [
                {"id": "claude-3-5-sonnet-20241022", "object": "model", "owned_by": "anthropic"},
                {"id": "claude-3-5-haiku-20241022", "object": "model", "owned_by": "anthropic"},
                {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
                {"id": "gpt-4o-mini", "object": "model", "owned_by": "openai"},
                {"id": "deepseek-chat", "object": "model", "owned_by": "deepseek"},
                {"id": "deepseek-coder", "object": "model", "owned_by": "deepseek"},
            ],
        }

    @router.post("/v1/chat/completions")
    async def openai_chat_completions(request: Request) -> Response:
        """Handle OpenAI chat completions proxy."""
        start_time = time.perf_counter()
        body_bytes = await request.body()
        raw_body: Dict[str, Any] = orjson.loads(body_bytes) if body_bytes else {}

        session_id = request.headers.get("x-session-id", "default")
        norm_req = openai_adapter.parse_request(raw_body, session_id=session_id)

        # 1. Virtual tool local execution check (0 upstream tokens!)
        local_tool_resp = virtual_tool_executor.check_and_execute(norm_req)
        if local_tool_resp:
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="openai",
                    model=norm_req.model,
                    raw_tokens=0,
                    optimized_tokens=0,
                    latency_ms=duration_ms,
                    applied_compressors=["virtual_tool_local_expand"],
                )
            return JSONResponse(
                content=local_tool_resp.raw_response,
                headers={
                    "X-CtxGuard-Virtual-Tool": "true",
                    "X-CtxGuard-Process-Time-Ms": f"{duration_ms:.2f}",
                },
            )

        # 2. Process through Compression Pipeline
        req_ctx = await pipeline.process(norm_req)

        # 3. Build upstream payload
        upstream_payload = openai_adapter.build_upstream_payload(req_ctx.request)
        client_headers = dict(request.headers)

        provider_name = "deepseek" if "deepseek" in norm_req.model.lower() else "openai"
        provider = upstream.resolve_provider(provider_name)
        headers = upstream.build_headers("openai", provider, client_headers)

        if norm_req.stream:
            stream_gen = upstream.forward_stream("v1/chat/completions", upstream_payload, headers, provider_name)
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="openai",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                )
            return StreamingResponse(
                SSEStreamHandler.passthrough_stream(stream_gen),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio),
                },
            )
        else:
            resp = await upstream.forward_request("v1/chat/completions", upstream_payload, headers, provider_name)
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="openai",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json",
                headers={"X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio)},
            )

    @router.post("/v1/messages")
    async def anthropic_messages(request: Request) -> Response:
        """Handle Anthropic messages proxy."""
        start_time = time.perf_counter()
        body_bytes = await request.body()
        raw_body: Dict[str, Any] = orjson.loads(body_bytes) if body_bytes else {}

        session_id = request.headers.get("x-session-id", "default")
        norm_req = anthropic_adapter.parse_request(raw_body, session_id=session_id)

        # 1. Virtual tool local execution check (0 upstream tokens!)
        local_tool_resp = virtual_tool_executor.check_and_execute(norm_req)
        if local_tool_resp:
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="anthropic",
                    model=norm_req.model,
                    raw_tokens=0,
                    optimized_tokens=0,
                    latency_ms=duration_ms,
                    applied_compressors=["virtual_tool_local_expand"],
                )
            return JSONResponse(
                content=local_tool_resp.raw_response,
                headers={
                    "X-CtxGuard-Virtual-Tool": "true",
                    "X-CtxGuard-Process-Time-Ms": f"{duration_ms:.2f}",
                },
            )

        # 2. Process through Compression Pipeline
        req_ctx = await pipeline.process(norm_req)

        # 3. Build upstream payload
        upstream_payload = anthropic_adapter.build_upstream_payload(req_ctx.request)
        client_headers = dict(request.headers)

        provider_name = "anthropic"
        provider = upstream.resolve_provider(provider_name)
        headers = upstream.build_headers("anthropic", provider, client_headers)

        if norm_req.stream:
            stream_gen = upstream.forward_stream("v1/messages", upstream_payload, headers, provider_name)
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="anthropic",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                )
            return StreamingResponse(
                SSEStreamHandler.passthrough_stream(stream_gen),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio),
                },
            )
        else:
            resp = await upstream.forward_request("v1/messages", upstream_payload, headers, provider_name)
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="anthropic",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type="application/json",
                headers={"X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio)},
            )

    return router
