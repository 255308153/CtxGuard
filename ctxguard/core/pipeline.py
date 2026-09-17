"""Orchestration pipeline executing compression operators, guards, and hooks."""

import copy
from typing import Callable, Dict, List, Optional
from ctxguard.config.schema import AppConfig
from ctxguard.core.context import NormalizedRequest, RequestContext
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.utils.token_counter import estimate_tokens_from_payload, estimate_tokens_from_text

HookFn = Callable[[RequestContext], RequestContext]

class CompressionPipeline:
    """Orchestrates request compression across guards, adaptive scheduler, compressors, and hooks."""

    def __init__(self, config: AppConfig, fingerprint_repo: Optional[FingerprintRepository] = None):
        from ctxguard.core.compressors.ansi_cleaner import ANSICleaner
        from ctxguard.core.compressors.progress_merger import ProgressMerger
        from ctxguard.core.compressors.stacktrace import StacktraceFolder
        from ctxguard.core.compressors.log_truncator import LogTruncator
        from ctxguard.core.compressors.secret_redactor import SecretRedactor
        from ctxguard.core.compressors.json_struct import JSONStructCompressor
        from ctxguard.core.compressors.whitespace import WhitespaceCleaner
        from ctxguard.core.compressors.dedup import DedupCompressor
        from ctxguard.core.compressors.ast_code import ASTCodeCompressor
        from ctxguard.core.compressors.git_diff import GitDiffCompressor
        from ctxguard.core.compressors.tool_delta import ToolDeltaCompressor
        from ctxguard.core.guards.cache_guard import CacheGuard
        from ctxguard.core.guards.thinking_manager import ThinkingManager
        from ctxguard.core.guards.output_shaper import OutputShaper
        from ctxguard.core.guards.tools_normalizer import ToolsNormalizer
        from ctxguard.core.adaptive_scheduler import AdaptiveScheduler
        from ctxguard.core.virtual_tools.injector import VirtualToolInjector
        from ctxguard.plugins.onnx.scorer import SemanticPruner
        from ctxguard.utils.token_counter import estimate_tokens_from_payload, estimate_tokens_from_text

        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.cache_guard = CacheGuard(config.cache_guard)
        self.thinking_manager = ThinkingManager(getattr(config, "thinking_manager", None) or getattr(config, "thinking_manager", None))
        shaper_cfg = getattr(config, "output_shaper", None)
        shaper_level = getattr(shaper_cfg, "level", 2) if shaper_cfg else 2
        self.output_shaping_enabled = getattr(shaper_cfg, "enabled", False) if shaper_cfg else False
        self.output_shaper = OutputShaper(level=shaper_level)
        self.tools_normalizer = ToolsNormalizer()
        self.adaptive_scheduler = AdaptiveScheduler(config.adaptive_pipeline)
        self.virtual_tool_injector = VirtualToolInjector(config.dedup.tool_injection)
        self.secret_redactor = SecretRedactor(config.structural_compression.secret_redactor)
        self.tool_delta_compressor = ToolDeltaCompressor(
            config.structural_compression.tool_delta,
            fingerprint_repo=fingerprint_repo
        )
        self.log_truncator = LogTruncator(
            config.structural_compression.log_cleaner,
            fingerprint_repo=fingerprint_repo
        )
        self.git_diff_compressor = GitDiffCompressor(
            config.structural_compression.git_diff,
            fingerprint_repo=fingerprint_repo
        )
        self.dedup_compressor = DedupCompressor(config.dedup, fingerprint_repo=fingerprint_repo)
        self.ast_compressor = ASTCodeCompressor(
            config.structural_compression.ast_compressor,
            fingerprint_repo=fingerprint_repo
        )
        self.semantic_pruner = SemanticPruner(
            protected_keywords=config.adaptive_pipeline.protected_keywords,
        )

        # Standard rule-based compressors in order
        self.compressors: List[BaseCompressor] = [
            self.secret_redactor,
            self.tool_delta_compressor,
            self.git_diff_compressor,
            self.dedup_compressor,
            self.ast_compressor,
            self.log_truncator,
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

    def register_pre_compress_hook(self, fn: HookFn) -> None:
        """Register hook executed before compressor sequence."""
        self._hooks["pre_compress"].append(fn)

    def register_post_compress_hook(self, fn: HookFn) -> None:
        """Register hook executed after compressor sequence."""
        self._hooks["post_compress"].append(fn)

    def hook(self, hook_type: str) -> Callable[[HookFn], HookFn]:
        """Decorator to register a hook function."""
        def decorator(fn: HookFn) -> HookFn:
            if hook_type in self._hooks:
                self._hooks[hook_type].append(fn)
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

        session_id = request.session_id or "default"
        idle_seconds = getattr(request, "idle_seconds", 0.0)
        provider = getattr(request, "provider", "default")
        has_cache = self.cache_guard._last_cached_tokens.get(session_id, 0) > 0

        context.state["has_active_cache"] = has_cache
        context.state["last_cached_tokens"] = self.cache_guard._last_cached_tokens.get(session_id, 0)

        # 2. Adaptive scheduler tune context
        self.adaptive_scheduler.tune_pipeline_context(context)

        # 3. Run pre_compress hooks
        for hook in self._hooks["pre_compress"]:
            context = hook(context)

        # 3.1 Manage thinking/reasoning tokens across multi-turn sessions
        if self.thinking_manager:
            reclaimed = self.thinking_manager.manage_thinking_tokens(
                request,
                provider=provider,
                was_cold=bool(idle_seconds > self.cache_guard.config.cache_ttl_seconds)
            )
            if reclaimed > 0 and "thinking_manager" not in context.applied_compressors:
                context.applied_compressors.append("thinking_manager")

        # 4. Partition messages via CacheGuard with dynamic token bound & cold recompact
        frozen_prefix, compressible_suffix, was_cold = self.cache_guard.partition_messages(
            request, session_id=session_id, idle_seconds=idle_seconds
        )

        if was_cold and "cold_recompact" not in context.applied_compressors:
            context.applied_compressors.append("cold_recompact")

        # Index historical content into dedup fingerprint store without modifying frozen prefix
        self.dedup_compressor.index_prefix(context, frozen_prefix)

        # 5. Apply compressors to compressible suffix
        # Pre-calculate token count of suffix before compression for economic arbitration
        pre_tokens = sum(estimate_tokens_from_text(m.get_text_content()) for m in compressible_suffix)
        orig_suffix_copies = [copy.deepcopy(m) for m in compressible_suffix]

        for compressor in self.compressors:
            if compressor.is_applicable(context):
                compressor.process(context, compressible_suffix)

        # Economic check: If session has existing upstream cache and compression savings do not beat provider read discount,
        # revert compression to preserve upstream cache read discount (First Principle: Cache > Compression).
        # For new sessions or cold turns without prior cache, compression savings are 100% net-positive.
        if not was_cold and pre_tokens > 0 and self.cache_guard._last_cached_tokens.get(session_id, 0) > 0:
            post_tokens = sum(estimate_tokens_from_text(m.get_text_content()) for m in compressible_suffix)
            # If compression attempted on an existing prefix portion and failed economic test
            if post_tokens < pre_tokens and not self.cache_guard.should_break_cache_for_compression(pre_tokens, post_tokens, provider=provider):
                # Revert suffix to prevent breaking cache for marginal token savings
                compressible_suffix = orig_suffix_copies

        # 6. Reassemble messages and apply Anthropic prompt cache controls
        request.messages = frozen_prefix + compressible_suffix
        self.cache_guard.apply_anthropic_cache_control(request)

        # 7. Inject ctx_expand virtual tool
        self.virtual_tool_injector.inject_schema(request)

        # 7.1 Normalize tools deterministically for prompt cache stability
        if request.tools:
            request.tools = self.tools_normalizer.normalize_tools(request.tools)

        # 7.2 Apply Byte-Stable Output Shaping to steer model verbosity (if enabled)
        if self.output_shaping_enabled:
            self.output_shaper.shape_request(request)

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
