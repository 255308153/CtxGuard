"""CLI command: ctxguard savings - Display or export financial savings ledger."""

import argparse
import json
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ctxguard.storage.savings_ledger import (
    aggregate_savings,
    resolve_savings_path,
)


def _render_progress(percent: float, width: int = 15) -> str:
    filled = int(round((percent / 100.0) * width))
    filled = max(0, min(filled, width))
    return "█" * filled + "░" * (width - filled)


def execute_savings(args: argparse.Namespace) -> None:
    """Execute savings ledger aggregation command."""
    target_path = resolve_savings_path(getattr(args, "path", None))

    if getattr(args, "reset", False):
        if target_path.exists():
            try:
                target_path.unlink()
                print(f"Savings ledger reset: {target_path}")
            except Exception as exc:
                print(f"Error resetting ledger: {exc}")
        else:
            print(f"No ledger found at: {target_path}")
        return

    report = aggregate_savings(
        target_path,
        retention_days=getattr(args, "days", 30),
    )

    if getattr(args, "as_json", False):
        print(json.dumps(report.to_dict(), indent=2))
        return

    console = Console(width=120)

    if report.lifetime["calls"] == 0:
        console.print(f"[dim]No savings recorded yet at {target_path}[/dim]")
        console.print("[dim]Use CtxGuard proxy to start recording context reductions.[/dim]")
        return

    # Header Panel
    console.print(
        Panel(
            f"[bold cyan] CtxGuard Financial Savings & Cost Reduction Ledger[/bold cyan]\n"
            f"[dim]Ledger: {target_path} | Window: Last {args.days if hasattr(args, 'days') else 30} Days[/dim]",
            border_style="bright_blue",
        )
    )

    # Time Windows Table
    win_table = Table(title=" Savings by Time Window", border_style="dim", header_style="bold green")
    win_table.add_column("Window", style="bold", no_wrap=True)
    win_table.add_column("Requests", justify="right")
    win_table.add_column("Tokens Saved", justify="right", style="cyan")
    win_table.add_column("Tokens Total", justify="right", style="dim")
    win_table.add_column("Reduction %", justify="left", no_wrap=True)
    win_table.add_column("Cost Avoided", justify="right", style="bold green")

    windows = [
        ("Today", report.windows.get("today", {})),
        ("Last 7 days", report.windows.get("last_7_days", {})),
        ("Last 30 days", report.windows.get("last_30_days", {})),
    ]

    for label, win in windows:
        saved_tok = win.get("tokens_saved", 0)
        before_tok = win.get("tokens_before", 0)
        pct = win.get("savings_percent", 0.0)
        cost = win.get("cost_usd", 0.0)
        calls = win.get("calls", 0)
        bar = _render_progress(pct, width=10)
        win_table.add_row(
            label,
            f"{calls:,}",
            f"{saved_tok:,}",
            f"{before_tok:,}",
            f"{bar} {pct:>5.1f}%",
            f"${cost:.4f}",
        )

    console.print(win_table)

    # Model Breakdown Table
    if report.by_model:
        m_table = Table(title="Cost avoided per model:", border_style="dim", header_style="bold magenta")
        m_table.add_column("Model Name", style="bold")
        m_table.add_column("Calls", justify="right")
        m_table.add_column("Saved Tokens", justify="right", style="cyan")
        m_table.add_column("Savings %", justify="right")
        m_table.add_column("Cost Avoided ($)", justify="right", style="bold green")

        for m in report.by_model:
            m_table.add_row(
                m["model"],
                f"{m['calls']:,}",
                f"{m['tokens_saved']:,}",
                f"{m['savings_percent']:.1f}%",
                f"${m['cost_usd']:.4f}",
            )
        console.print(m_table)

    # Client Breakdown Table
    if report.by_client:
        c_table = Table(title="Savings by client:", border_style="dim", header_style="bold yellow")
        c_table.add_column("Client Agent", style="bold")
        c_table.add_column("Calls", justify="right")
        c_table.add_column("Tokens Saved", justify="right", style="cyan")
        c_table.add_column("Cost Avoided ($)", justify="right", style="bold green")

        for c in report.by_client:
            c_table.add_row(
                c["client"],
                f"{c['calls']:,}",
                f"{c['tokens_saved']:,}",
                f"${c['cost_usd']:.4f}",
            )
        console.print(c_table)
