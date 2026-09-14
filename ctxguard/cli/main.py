"""Main CLI dispatcher for CtxGuard."""

import argparse
import sys
from ctxguard import __version__
from ctxguard.cli.cmd_start import execute_start
from ctxguard.cli.cmd_config import execute_config
from ctxguard.cli.cmd_stats import execute_stats
from ctxguard.cli.cmd_learn import execute_learn
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

    # 'learn' command (Phase 3)
    learn_parser = subparsers.add_parser("learn", help="Run offline loop detection and rule update")
    learn_parser.add_argument("-c", "--config", help="Path to ctxguard.yaml config file")
    learn_parser.add_argument("--db", help="Path to custom .ctxguard.db database file")
    learn_parser.add_argument("-t", "--target", help="Explicit target rule file (e.g. .cursorrules or CLAUDE.local.md)")
    learn_parser.add_argument("--threshold", type=int, help="Loop detection sensitivity threshold")
    learn_parser.add_argument("--dry-run", action="store_true", help="Preview extracted rules without writing to files")

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
    elif args.command == "learn":
        execute_learn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
