"""Stats dashboard command for CtxGuard."""

import argparse
from pathlib import Path
import sys

from ctxguard.config.loader import ConfigLoader
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_stats import StatsRepository
from ctxguard.utils.console import Console


def execute_stats(args: argparse.Namespace) -> None:
    """Render real-time context optimization and token savings dashboard."""
    try:
        config = ConfigLoader.load_config(config_path=args.config if hasattr(args, "config") else None)
    except Exception:
        config = ConfigLoader.load_config()

    db_path = getattr(args, "db", None) or config.learn.storage_db
    if not Path(db_path).exists():
        Console.warning(f"No database found at '{db_path}'. Make requests through the proxy first.")
        return

    db_manager = DatabaseManager(db_path)
    stats_repo = StatsRepository(db_manager)
    summary = stats_repo.get_summary()

    # ANSI styles
    C = Console.CYAN
    G = Console.GREEN
    Y = Console.YELLOW
    B = Console.BOLD
    R = Console.RESET
    D = Console.DIM

    print(f"\n{B}{C}╔══════════════════════════════════════════════════════════════════╗{R}")
    print(f"{B}{C}║               CtxGuard Context Optimization Dashboard            ║{R}")
    print(f"{B}{C}╚══════════════════════════════════════════════════════════════════╝{R}\n")

    print(f" {B}Database:{R} {db_path}")
    print(f" {B}Total Proxied Requests:{R}  {summary['total_requests']:,}")
    print(f" {B}Total Raw Tokens In:{R}     {summary['total_raw_tokens']:,}")
    print(f" {B}Optimized Tokens Out:{R}    {summary['total_optimized_tokens']:,}")
    print(f" {B}Total Tokens Saved:{R}      {G}{B}{summary['total_saved_tokens']:,}{R} ({G}{summary['overall_saved_percent']}%{R})")
    print(f" {B}Estimated Cost Saved:{R}    {G}{B}${summary['estimated_dollars_saved']:.4f} USD{R}")
    print(f" {B}Avg Process Latency:{R}     {summary['avg_latency_ms']} ms\n")

    recent_limit = getattr(args, "limit", 5) or 5
    recent_logs = stats_repo.get_recent_requests(limit=recent_limit)
    if recent_logs:
        print(f"{B} Recent Requests (Last {len(recent_logs)}):{R}")
        print(f" {'ID':<4} {'Model':<22} {'Raw':<8} {'Optimized':<10} {'Saved %':<9} {'Latency':<9}")
        print(f" {D}{'-'*66}{R}")
        for r in recent_logs:
            model_short = (r['model'][:20] + '..') if len(r['model']) > 22 else r['model']
            saved_str = f"{r['saved_ratio']}%"
            lat_str = f"{r['latency_ms']:.1f}ms"
            print(f" {r['id']:<4} {model_short:<22} {r['raw_tokens']:<8} {r['optimized_tokens']:<10} {G}{saved_str:<9}{R} {lat_str:<9}")
        print()
    else:
        print(f"{D} No request history recorded yet.{R}\n")
