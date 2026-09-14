"""Adaptive multi-tier compression scheduler."""

from typing import List, Tuple
from ctxguard.config.schema import AdaptivePipelineConfig, LevelConfig
from ctxguard.core.context import RequestContext


class AdaptiveScheduler:
    """Selects and tunes compression operators dynamically based on context token length."""

    def __init__(self, config: AdaptivePipelineConfig):
        self.config = config

    def select_level(self, total_tokens: int) -> LevelConfig:
        """Select active LevelConfig based on current token size."""
        if not self.config.enabled or not self.config.levels:
            return LevelConfig(name="default_lossless", max_tokens=1000000, compression_mode="lossless", prune_ratio=1.0)

        # Levels are sorted by max_tokens ascending
        for lvl in self.config.levels:
            if total_tokens <= lvl.max_tokens:
                return lvl

        # If exceeds all configured levels, return the highest level
        return self.config.levels[-1]

    def tune_pipeline_context(self, context: RequestContext) -> LevelConfig:
        """Evaluate context and annotate state with active level."""
        active_level = self.select_level(context.original_tokens)
        context.state["active_level"] = active_level.name
        context.state["compression_mode"] = active_level.compression_mode
        context.state["target_prune_ratio"] = active_level.prune_ratio
        return active_level
