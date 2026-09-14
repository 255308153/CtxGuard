"""Orchestration pipeline executing compression operators, guards, and hooks."""

from typing import Callable, Dict, List, Optional
from ctxguard.config.schema import AppConfig
from ctxguard.core.context import NormalizedRequest, RequestContext
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.compressors.ansi_cleaner import ANSICleaner
from ctxguard.core.compressors.progress_merger import ProgressMerger
from ctxguard.core.compressors.stacktrace import StacktraceFolder
from ctxguard.core.compressors.json_struct import JSONStructCompressor
from ctxguard.core.compressors.whitespace import WhitespaceCleaner
from ctxguard.core.compressors.dedup import DedupCompressor
from ctxguard.core.guards.cache_guard import CacheGuard
from ctxguard.core.adaptive_scheduler import AdaptiveScheduler
from ctxguard.core.virtual_tools.injector import VirtualToolInjector
from ctxguard.plugins.onnx.scorer import SemanticPruner
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.utils.token_counter import estimate_tokens_from_payload, estimate_tokens_from_text


HookFn = Callable[[RequestContext], RequestContext]


class CompressionPipeline:
    """Orchestrates request compression across guards, adaptive scheduler, compressors, and hooks."""

    def __init__(self, config: AppConfig, fingerprint_repo: Optional[FingerprintRepository] = None):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.cache_guard = CacheGuard(config.cache_guard)
        self.adaptive_scheduler = AdaptiveScheduler(config.adaptive_pipeline)
        self.virtual_tool_injector = VirtualToolInjector(config.dedup.tool_injection)
        self.dedup_compressor = DedupCompressor(config.dedup, fingerprint_repo=fingerprint_repo)
        self.semantic_pruner = SemanticPruner(
            protected_keywords=config.adaptive_pipeline.protected_keywords,
        )

        # Standard rule-based compressors in order
        self.compressors: List[BaseCompressor] = [
            self.dedup_compressor,
            ANSICleaner(config.structural_compression.log_cleaner),
            ProgressMerger(config.structural_compression.log_cleaner),
            StacktraceFolder(config.structural_compression.log_cleaner),
            JSONStructCompressor(config.structural_compression.json_compressor),
            WhitespaceCleaner(),
            self.semantic_pruner,
        ]

        self._hooks: Dict[str, List[HookFn]] = {
            "pre_compress": [],
            "post_compress": [],
        }

    def hook(self, hook_name: str) -> Callable[[HookFn], HookFn]:
        """Register a decorator hook for pre_compress or post_compress."""
        def decorator(fn: HookFn) -> HookFn:
            if hook_name in self._hooks:
                self._hooks[hook_name].append(fn)
            return fn
        return decorator

    async def process(self, request: NormalizedRequest) -> RequestContext:
        """Execute full optimization pipeline on the normalized request."""
        # 1. Estimate initial tokens
        if request.raw_payload and "messages" in request.raw_payload:
            raw_token_count = estimate_tokens_from_payload(request.raw_payload)
        else:
            raw_token_count = sum(
                estimate_tokens_from_text(m.get_text_content()) for m in request.messages
            )
            if request.system:
                raw_token_count += estimate_tokens_from_text(request.system)

        context = RequestContext(
            request=request,
            original_tokens=max(1, raw_token_count),
        )

        # 2. Adaptive scheduler tune context
        self.adaptive_scheduler.tune_pipeline_context(context)

        # 3. Run pre_compress hooks
        for hook in self._hooks["pre_compress"]:
            context = hook(context)

        # 4. Partition messages via CacheGuard to isolate frozen prefix
        frozen_prefix, compressible_suffix = self.cache_guard.partition_messages(request)

        # Index historical content into dedup fingerprint store without modifying frozen prefix
        self.dedup_compressor.index_prefix(context, frozen_prefix)

        # 5. Apply compressors to compressible suffix
        for compressor in self.compressors:
            if compressor.is_applicable(context):
                compressor.process(context, compressible_suffix)

        # 6. Reassemble messages and apply Anthropic prompt cache controls
        request.messages = frozen_prefix + compressible_suffix
        self.cache_guard.apply_anthropic_cache_control(request)

        # 7. Inject ctx_expand virtual tool
        self.virtual_tool_injector.inject_schema(request)

        # 8. Re-estimate optimized tokens and compression ratio
        optimized_text_tokens = sum(
            estimate_tokens_from_text(m.get_text_content()) for m in request.messages
        )
        if request.system:
            optimized_text_tokens += estimate_tokens_from_text(request.system)

        context.optimized_tokens = max(1, optimized_text_tokens)
        context.compression_ratio = round(context.optimized_tokens / max(1, context.original_tokens), 4)

        # 9. Run post_compress hooks
        for hook in self._hooks["post_compress"]:
            context = hook(context)

        return context
