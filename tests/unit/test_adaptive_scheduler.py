"""Unit tests for adaptive multi-tier compression scheduler."""

from ctxguard.config.schema import AdaptivePipelineConfig, LevelConfig
from ctxguard.core.adaptive_scheduler import AdaptiveScheduler
from ctxguard.core.context import Message, NormalizedRequest, RequestContext


def test_adaptive_scheduler_level_selection():
    config = AdaptivePipelineConfig(
        enabled=True,
        levels=[
            LevelConfig(name="level_1", max_tokens=16384, compression_mode="lossless", prune_ratio=1.0),
            LevelConfig(name="level_2", max_tokens=65536, compression_mode="lightweight", prune_ratio=0.85),
            LevelConfig(name="level_3", max_tokens=200000, compression_mode="deep", prune_ratio=0.60),
        ],
    )
    scheduler = AdaptiveScheduler(config)

    # Short context
    lvl1 = scheduler.select_level(5000)
    assert lvl1.name == "level_1"
    assert lvl1.compression_mode == "lossless"

    # Medium context
    lvl2 = scheduler.select_level(30000)
    assert lvl2.name == "level_2"
    assert lvl2.prune_ratio == 0.85

    # Long context
    lvl3 = scheduler.select_level(100000)
    assert lvl3.name == "level_3"
    assert lvl3.compression_mode == "deep"


def test_adaptive_scheduler_tune_context():
    config = AdaptivePipelineConfig(enabled=True)
    scheduler = AdaptiveScheduler(config)

    # 80k tokens is within level_1 (< 128k, lossless)
    req1 = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[])
    ctx1 = RequestContext(request=req1, original_tokens=80000)
    scheduler.tune_pipeline_context(ctx1)
    assert ctx1.state["active_level"] == "level_1"
    assert ctx1.state["target_prune_ratio"] == 1.0

    # 200k tokens reaches level_2 (128k ~ 512k, lightweight)
    req2 = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[])
    ctx2 = RequestContext(request=req2, original_tokens=200000)
    scheduler.tune_pipeline_context(ctx2)
    assert ctx2.state["active_level"] == "level_2"
    assert ctx2.state["target_prune_ratio"] == 0.90
