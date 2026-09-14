"""Integration test executing synthetic benchmark scenarios."""

import asyncio
from ctxguard.config.schema import AppConfig
from ctxguard.core.pipeline import CompressionPipeline
from benchmarks.run_benchmark import run_scenario_benchmark
from benchmarks.synthetic_dataset import (
    get_coding_agent_scenario,
    get_rag_database_scenario,
    get_long_document_rag_scenario,
)


def test_benchmark_scenarios_execution():
    async def _test():
        config = AppConfig()
        pipeline = CompressionPipeline(config)

        scenarios = [
            get_coding_agent_scenario(),
            get_rag_database_scenario(),
            get_long_document_rag_scenario(),
        ]

        for sc in scenarios:
            res = await run_scenario_benchmark(pipeline, sc)
            assert res["raw_tokens"] > 0
            assert res["optimized_tokens"] <= res["raw_tokens"]
            assert res["latency_ms"] >= 0.0
            assert res["saved_percent"] >= 0.0

    asyncio.run(_test())
