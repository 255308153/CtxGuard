"""Main CLI dispatcher for CtxGuard."""

import argparse
import sys
from ctxguard import __version__
from ctxguard.cli.cmd_start import execute_start
from ctxguard.cli.cmd_config import execute_config
from ctxguard.cli.cmd_stats import execute_stats
from ctxguard.cli.cmd_learn import execute_learn
from ctxguard.cli.cmd_savings import execute_savings
from ctxguard.cli.cmd_env import execute_env
from ctxguard.cli.cmd_wrap import execute_wrap
from ctxguard.utils.console import Console


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ctxguard",
        description="CtxGuard: Ultra-lightweight LLM Context Optimization & Guardian Proxy",
    )
    parser.add_argument("-v", "--version", action="version", version=f"CtxGuard {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 'start' command
    start_parser = subparsers.add_parser("start", help="Start the CtxGuard proxy gateway server")
    start_parser.add_argument("-c", "--config", help="Path to custom ctxguard.yaml config file")
    start_parser.add_argument("-p", "--port", type=int, help="Override server listening port")
    start_parser.add_argument("--host", help="Override server listening host")
    start_parser.add_argument("--provider", help="Override default upstream provider (anthropic | openai | deepseek)")
    start_parser.add_argument("--log-level", help="Override log level (DEBUG | INFO | WARNING | ERROR)")

    # 'config' command
    config_parser = subparsers.add_parser("config", help="Manage configuration files")
    config_parser.add_argument(
        "action",
        choices=["init", "validate", "show"],
        help="Action: init (generate default yaml), validate (check syntax), show (display active config)",
    )
    config_parser.add_argument("-c", "--config", help="Path to ctxguard.yaml config file to validate/show")
    config_parser.add_argument("-f", "--force", action="store_true", help="Force overwrite existing config file in init")

    # 'stats' command (Phase 2)
    stats_parser = subparsers.add_parser("stats", help="View real-time Token savings metrics dashboard")
    stats_parser.add_argument("-c", "--config", help="Path to ctxguard.yaml config file")
    stats_parser.add_argument("--db", help="Path to custom .ctxguard.db database file")
    stats_parser.add_argument("-n", "--limit", type=int, default=5, help="Number of recent request logs to display")

    # 'savings' command (Durable Append-Only Savings Ledger)
    savings_parser = subparsers.add_parser("savings", help="Show durable context compression and cache savings over time")
    savings_parser.add_argument("--json", dest="as_json", action="store_true", help="Emit raw report as JSON")
    savings_parser.add_argument("--days", type=int, default=30, help="Retention and lookback window in days (default: 30)")
    savings_parser.add_argument("--reset", action="store_true", help="Delete/reset the savings ledger")
    savings_parser.add_argument("--path", help="Path to custom savings_events.jsonl ledger file")

    # 'learn' command (Phase 3: Offline Self-Evolution)
    learn_parser = subparsers.add_parser("learn", help="Run offline failure analysis, success correlation, and rule update")
    learn_parser.add_argument("-c", "--config", help="Path to ctxguard.yaml config file")
    learn_parser.add_argument("--db", help="Path to custom .ctxguard.db database file")
    learn_parser.add_argument("-t", "--target", help="Explicit target rule file (e.g. .cursorrules or CLAUDE.local.md)")
    learn_parser.add_argument("-s", "--source", "--scan-dir", dest="source", help="Directory containing Claude Code jsonl logs or project logs")
    learn_parser.add_argument("--threshold", type=int, help="Loop detection sensitivity threshold")
    learn_parser.add_argument("--apply", action="store_true", help="Atomically write extracted rules to target files (defaults to dry-run preview)")
    learn_parser.add_argument("--dry-run", action="store_true", help="Preview extracted rules without writing to files")

    # 'env' command: one-click setup for agent environments
    env_parser = subparsers.add_parser("env", help="One-click environment injection for Claude Code / Pi Agent / Cursor / GPT")
    env_parser.add_argument("agent", nargs="?", default="all", choices=["claude", "pi", "cursor", "gpt", "all"], help="Target agent ecosystem")
    env_parser.add_argument("-p", "--port", type=int, default=8787, help="CtxGuard proxy gateway port (default: 8787)")
    env_parser.add_argument("--patch", action="store_true", help="Auto-detect and remember agent original upstreams and patch configs")
    env_parser.add_argument("--eval", action="store_true", help="Output shell export commands for eval $(ctxguard env)")

    # 'wrap' command: auto-spawn proxy and launch target agent directly
    wrap_parser = subparsers.add_parser("wrap", help="Start proxy automatically and launch target agent (claude | pi | codex | aider)")
    wrap_parser.add_argument("agent", help="Target agent command to run (e.g. claude, pi, codex, aider)")
    wrap_parser.add_argument("-p", "--port", type=int, default=8787, help="CtxGuard proxy port (default: 8787)")
    wrap_parser.add_argument("extra_args", nargs="*", help="Extra arguments passed directly to the target agent")

    return parser


def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "start":
        execute_start(args)
    elif args.command == "config":
        execute_config(args)
    elif args.command == "stats":
        execute_stats(args)
    elif args.command == "savings":
        execute_savings(args)
    elif args.command == "learn":
        execute_learn(args)
    elif args.command == "env":
        execute_env(args)
    elif args.command == "wrap":
        execute_wrap(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
