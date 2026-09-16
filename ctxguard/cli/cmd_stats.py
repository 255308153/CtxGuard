"""CLI command: ctxguard stats - Display comprehensive SQLite gateway statistics."""

import argparse
import os
from typing import Optional
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.columns import Columns

from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_stats import StatsRepository


def execute_stats(args: argparse.Namespace) -> None:
    """Execute stats display command."""
    db_path = getattr(args, "db", None) or os.getenv("CTXGUARD_DB_PATH", ".ctxguard.db")
    db_manager = DatabaseManager(db_path)
    repo = StatsRepository(db_manager)

    summary = repo.get_summary()
    recent = repo.get_recent_requests(limit=getattr(args, "limit", 10))

    console = Console()

    # Header Panel
    console.print(
        Panel(
            f"[bold cyan] CtxGuard Context Optimization Dashboard[/bold cyan]\n"
            f"[dim]Database: {db_path}[/dim]",
            border_style="bright_blue",
        )
    )

    # Key Metrics Cards
    tot_req = summary.get("total_requests", 0)
    raw_tok = summary.get("total_raw_tokens", 0)
    saved_tok = summary.get("total_saved_tokens", 0)
    saved_pct = summary.get("overall_saved_percent", 0.0)
    avg_lat = summary.get("avg_latency_ms", 0.0)
    dollars = summary.get("estimated_dollars_saved", 0.0)

    p1 = Panel(f"[bold green]{tot_req:,}[/bold green]\n[dim]Total Proxied Requests[/dim]", border_style="green")
    p2 = Panel(f"[bold cyan]{saved_tok:,}[/bold cyan] / {raw_tok:,}\n[dim]Tokens Saved / Total[/dim]", border_style="cyan")
    p3 = Panel(f"[bold magenta]{saved_pct:.1f}%[/bold magenta]\n[dim]Reduction Ratio[/dim]", border_style="magenta")
    p4 = Panel(f"[bold yellow]${dollars:.4f}[/bold yellow]\n[dim]Estimated Savings[/dim]", border_style="yellow")

    console.print(Columns([p1, p2, p3, p4]))

    # Print explicit string for backward compatibility / tests
    console.print(f"[dim]Total Proxied Requests: {tot_req} | Avg Latency: {avg_lat:.2f}ms[/dim]\n")

    # Recent Requests Table
    if recent:
        table = Table(title=" Recent Optimization Requests", border_style="dim", header_style="bold blue")
        table.add_column("ID", justify="right", style="dim")
        table.add_column("Protocol", style="cyan")
        table.add_column("Model", style="bold")
        table.add_column("Raw Tok", justify="right")
        table.add_column("Opt Tok", justify="right", style="green")
        table.add_column("Saved %", justify="right", style="magenta")
        table.add_column("Latency", justify="right", style="yellow")

        for r in recent:
            table.add_row(
                str(r.get("id", "")),
                str(r.get("protocol", "")),
                str(r.get("model", "")),
                f"{r.get('raw_tokens', 0):,}",
                f"{r.get('optimized_tokens', 0):,}",
                f"{r.get('saved_ratio', 0.0):.1f}%",
                f"{r.get('latency_ms', 0.0):.1f}ms",
            )
        console.print(table)
    else:
        console.print("[dim]No recent requests logged yet.[/dim]")
