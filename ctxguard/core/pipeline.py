import asyncio
import copy
from typing import Any, Callable, Dict, List, Optional
from ctxguard.config.schema import AppConfig
from ctxguard.core.context import Message, NormalizedRequest, RequestContext
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.utils.token_counter import estimate_tokens_from_payload, estimate_tokens_from_text

HookFn = Callable[[RequestContext], RequestContext]

class CompressionPipeline:
    """Orchestrates request compression across guards, adaptive scheduler, compressors, and hooks."""

    def __init__(
        self,
        config: AppConfig,
        fingerprint_repo: Optional[FingerprintRepository] = None,
        db_manager: Optional[Any] = None,
    ):
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
        from ctxguard.core.context_tracker import ContextTracker
        from ctxguard.plugins.onnx.scorer import SemanticPruner
        from ctxguard.utils.token_counter import estimate_tokens_from_payload, estimate_tokens_from_text

        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.db_manager = db_manager
        pe_cfg = getattr(config, "proactive_expansion", None)
        self.proactive_expansion_enabled = getattr(pe_cfg, "enabled", True) if pe_cfg else True
        self.context_tracker = ContextTracker(
            relevance_threshold=getattr(pe_cfg, "relevance_threshold", 0.45) if pe_cfg else 0.45,
            max_content_chars=getattr(pe_cfg, "max_content_chars", 1200) if pe_cfg else 1200,
            max_context_age_seconds=getattr(pe_cfg, "max_context_age_seconds", 300.0) if pe_cfg else 300.0,
            max_contexts=getattr(pe_cfg, "max_contexts", 100) if pe_cfg else 100,
            blocked_keywords=getattr(pe_cfg, "blocked_keywords", None) if pe_cfg else None,
        )
        if self.fingerprint_repo is not None and getattr(self.fingerprint_repo, "context_tracker", None) is None:
            self.fingerprint_repo.context_tracker = self.context_tracker
        self.cache_guard = CacheGuard(config.cache_guard, db_manager=db_manager)
        self.thinking_manager = ThinkingManager(getattr(config, "thinking_manager", None) or getattr(config, "thinking_manager", None))
        shaper_cfg = getattr(config, "output_shaper", None)
        shaper_level = getattr(shaper_cfg, "level", 2) if shaper_cfg else 2
        self.output_shaping_enabled = getattr(shaper_cfg, "enabled", False) if shaper_cfg else False
        self.output_shaper = OutputShaper(level=shaper_level)
        self.tools_normalizer = ToolsNormalizer()
        self.adaptive_scheduler = AdaptiveScheduler(config.adaptive_pipeline)
        self.virtual_tool_injector = VirtualToolInjector(config.dedup.tool_injection)
        tool_injection_enabled = getattr(getattr(config.dedup, "tool_injection", None), "enabled", True)
        self.secret_redactor = SecretRedactor(config.structural_compression.secret_redactor)
        self.tool_delta_compressor = ToolDeltaCompressor(
            config.structural_compression.tool_delta,
            fingerprint_repo=fingerprint_repo,
            tool_injection_enabled=tool_injection_enabled,
        )
        self.log_truncator = LogTruncator(
            config.structural_compression.log_cleaner,
            fingerprint_repo=fingerprint_repo,
            tool_injection_enabled=tool_injection_enabled,
        )
        self.git_diff_compressor = GitDiffCompressor(
            config.structural_compression.git_diff,
            fingerprint_repo=fingerprint_repo,
            tool_injection_enabled=tool_injection_enabled,
        )
        self.dedup_compressor = DedupCompressor(config.dedup, fingerprint_repo=fingerprint_repo)
        self.ast_compressor = ASTCodeCompressor(
            config.structural_compression.ast_compressor,
            fingerprint_repo=fingerprint_repo,
            tool_injection_enabled=tool_injection_enabled,
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

    def apply_proactive_expansion(
        self,
        request: NormalizedRequest,
        target_messages: Optional[List[Message]] = None,
    ) -> None:
        if not self.proactive_expansion_enabled:
            return
        if not self.proactive_expansion_enabled:
            return
        """Analyze query relevance against compressed contexts and proactively expand full content.

        CRITICAL PROMPT CACHE INVARIANT:
        Never modify any historical messages that belong to !
        If  (compressible_suffix) is provided, expansion MUST ONLY be injected
        into the live zone (e.g. the latest user message or the last active tool/turn in suffix).
        Modifying an already-cached message in  will invalidate upstream KV Cache.
        """
        if not self.proactive_expansion_enabled or not self.context_tracker or not self.fingerprint_repo or not request.messages:
            return

        session_id = request.session_id or "default"
        workspace_key = request.metadata.get("workspace_key") or request.metadata.get("project_name") or ""

        pe_cfg = getattr(self.config, "proactive_expansion", None)
        if pe_cfg and getattr(pe_cfg, "skip_in_cache_mode", False) and self.cache_guard.has_compressed_history(session_id):
            return

        active_messages = target_messages if target_messages is not None else request.messages
        if not active_messages:
            return

        active_user_messages = [m for m in active_messages if m.role == "user"]
        target_msg = active_user_messages[-1] if active_user_messages else None

        if target_msg is None:
            target_msg = active_messages[-1]

        query_text = target_msg.get_text_content()
        if not query_text:
            return

        max_exp = getattr(pe_cfg, "max_expansions", 2) if pe_cfg else 2
        recs = self.context_tracker.analyze_query(
            query_text,
            session_id=session_id,
            workspace_key=workspace_key,
            max_expansions=max_exp,
        )
        if not recs:
            return

        expanded_items = []
        for r in recs:
            full_text = self.fingerprint_repo.get_content(r.hash_key)
            if full_text:
                expanded_items.append({"hash": r.hash_key, "content": full_text, "reason": r.reason})

        if expanded_items:
            expansion_block = self.context_tracker.format_proactive_expansion(
                expanded_items,
                session_id=session_id,
                workspace_key=workspace_key,
            )
            if isinstance(target_msg.content, str):
                target_msg.content += f"\n\n{expansion_block}"
            elif isinstance(target_msg.content, list):
                target_msg.content.append({"type": "text", "text": f"\n\n{expansion_block}"})

    def process_sync(self, request: NormalizedRequest) -> RequestContext:
        """Execute full optimization pipeline on the normalized request synchronously."""
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

        # 4. Partition messages via CacheGuard with dynamic token bound & cold recompact
        frozen_prefix, compressible_suffix, was_cold = self.cache_guard.partition_messages(
            request, session_id=session_id, idle_seconds=idle_seconds, provider=provider
        )

        if was_cold and "cold_recompact" not in context.applied_compressors:
            context.applied_compressors.append("cold_recompact")

        # 4.1 Manage thinking/reasoning tokens across multi-turn sessions safely:
        # - On cold recompact: clean full history to form the minimal baseline
        # - On hot turn: clean ONLY compressible_suffix to preserve frozen_prefix 100% byte stability
        if self.thinking_manager:
            if was_cold:
                reclaimed = self.thinking_manager.manage_thinking_tokens(
                    request,
                    provider=provider,
                    was_cold=True,
                )
                if reclaimed > 0 and "thinking_manager" not in context.applied_compressors:
                    context.applied_compressors.append("thinking_manager")
            elif compressible_suffix:
                reclaimed = self.thinking_manager.manage_thinking_tokens(
                    request,
                    provider=provider,
                    was_cold=False,
                    messages=compressible_suffix,
                    is_suffix_only=True,
                )
                if reclaimed > 0 and "thinking_manager" not in context.applied_compressors:
                    context.applied_compressors.append("thinking_manager")

        # 4.5 Apply Proactive Expansion strictly to live zone (compressible_suffix)
        # to ensure frozen_prefix is never modified (Prompt Cache Invariant)
        self.apply_proactive_expansion(request, target_messages=compressible_suffix)

        # Index historical content into dedup fingerprint store without modifying frozen prefix
        self.dedup_compressor.index_prefix(context, frozen_prefix)

        # 5. Apply compressors deterministically to live-zone compressible suffix (Append-Only Live Zone)
        for compressor in self.compressors:
            if compressor.is_applicable(context):
                compressor.process(context, compressible_suffix)

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

    async def process(self, request: NormalizedRequest) -> RequestContext:
        """Execute full optimization pipeline offloaded to worker thread pool to prevent blocking event loop."""
        return await asyncio.to_thread(self.process_sync, request)
