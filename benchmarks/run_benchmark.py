"""Benchmark runner for CtxGuard optimization efficiency and latency."""

import asyncio
import os
from pathlib import Path
import sys
import time
from typing import List, Dict, Any

# Ensure workspace root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ctxguard.config.schema import AppConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.core.pipeline import CompressionPipeline
from benchmarks.synthetic_dataset import (
    get_coding_agent_scenario,
    get_rag_database_scenario,
    get_long_document_rag_scenario,
)


async def run_scenario_benchmark(pipeline: CompressionPipeline, scenario: Dict[str, Any]) -> Dict[str, Any]:
    name = scenario["name"]
    messages = [Message(role=m["role"], content=m["content"]) for m in scenario["messages"]]
    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=messages,
        session_id=f"benchmark_{name[:8]}",
    )

    start_t = time.perf_counter()
    ctx = await pipeline.process(req)
    latency_ms = (time.perf_counter() - start_t) * 1000

    saved_tokens = max(0, ctx.original_tokens - ctx.optimized_tokens)
    saved_percent = round((saved_tokens / max(1, ctx.original_tokens)) * 100, 2)

    return {
        "name": name,
        "raw_tokens": ctx.original_tokens,
        "optimized_tokens": ctx.optimized_tokens,
        "saved_tokens": saved_tokens,
        "saved_percent": saved_percent,
        "latency_ms": round(latency_ms, 2),
        "applied_compressors": ctx.applied_compressors,
    }


async def main():
    print("\n" + "=" * 75)
    print("                 CtxGuard Performance & Compression Benchmark             ")
    print("=" * 75 + "\n")

    config = AppConfig()
    pipeline = CompressionPipeline(config)

    scenarios = [
        get_coding_agent_scenario(),
        get_rag_database_scenario(),
        get_long_document_rag_scenario(),
    ]

    results = []
    for sc in scenarios:
        res = await run_scenario_benchmark(pipeline, sc)
        results.append(res)

    print(f"{'Scenario Name':<44} {'Raw':<8} {'Optimized':<10} {'Saved %':<10} {'Latency':<8}")
    print("-" * 84)

    total_raw = sum(r["raw_tokens"] for r in results)
    total_opt = sum(r["optimized_tokens"] for r in results)
    total_saved = sum(r["saved_tokens"] for r in results)
    avg_latency = sum(r["latency_ms"] for r in results) / len(results)

    for r in results:
        print(f"{r['name'][:42]:<44} {r['raw_tokens']:<8} {r['optimized_tokens']:<10} \033[92m{r['saved_percent']}%\033[0m     {r['latency_ms']}ms")

    print("-" * 84)
    overall_saved_pct = round((total_saved / max(1, total_raw)) * 100, 2)
    print(f"\033[1m{'TOTAL / AVERAGE':<44} {total_raw:<8} {total_opt:<10} \033[92m{overall_saved_pct}%\033[0m     {avg_latency:.2f}ms\033[0m\n")


if __name__ == "__main__":
    asyncio.run(main())
