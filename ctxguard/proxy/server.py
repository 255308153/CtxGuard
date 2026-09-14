"""FastAPI application factory and lifecycle management."""

from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import time

from ctxguard.config.schema import AppConfig
from ctxguard.core.pipeline import CompressionPipeline
from ctxguard.proxy.upstream import UpstreamClient
from ctxguard.proxy.router import create_router
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_stats import StatsRepository
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.utils.console import Console


def create_app(config: AppConfig) -> FastAPI:
    """Create and configure FastAPI application instance with storage and pipeline."""

    db_manager = DatabaseManager(config.learn.storage_db)
    stats_repo = StatsRepository(db_manager)
    fingerprint_repo = FingerprintRepository(db_manager)

    pipeline = CompressionPipeline(config, fingerprint_repo=fingerprint_repo)
    upstream = UpstreamClient(config.upstream, timeout_seconds=config.server.timeout_seconds)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        Console.info(f"CtxGuard Gateway started on http://{config.server.host}:{config.server.port}")
        Console.info(f"Single-file SQLite storage active at: {config.learn.storage_db}")
        yield
        await upstream.close()
        Console.info("CtxGuard Gateway shut down cleanly.")

    app = FastAPI(
        title="CtxGuard Proxy Gateway",
        version="0.1.0",
        description="Ultra-lightweight LLM Context Optimization Gateway",
        lifespan=lifespan,
    )

    # CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Timing and Logging Middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000

        response.headers["X-CtxGuard-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        Console.error(f"Unhandled proxy error on {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "ctxguard_internal_error"}},
        )

    # Mount API routes
    router = create_router(
        config=config,
        pipeline=pipeline,
        upstream=upstream,
        stats_repo=stats_repo,
        fingerprint_repo=fingerprint_repo,
    )
    app.include_router(router)

    # Attach instances to app state
    app.state.config = config
    app.state.pipeline = pipeline
    app.state.upstream = upstream
    app.state.db_manager = db_manager
    app.state.stats_repo = stats_repo
    app.state.fingerprint_repo = fingerprint_repo

    return app
