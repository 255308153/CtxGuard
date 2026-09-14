"""Console formatting and logging output utilities."""

import sys
from typing import Optional


class Console:
    """Lightweight ANSI console logger with zero heavy dependencies."""

    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"

    @classmethod
    def info(cls, msg: str) -> None:
        sys.stdout.write(f"{cls.CYAN}[CtxGuard]{cls.RESET} {msg}\n")
        sys.stdout.flush()

    @classmethod
    def success(cls, msg: str) -> None:
        sys.stdout.write(f"{cls.GREEN}[CtxGuard]{cls.RESET} {cls.BOLD}{msg}{cls.RESET}\n")
        sys.stdout.flush()

    @classmethod
    def warning(cls, msg: str) -> None:
        sys.stdout.write(f"{cls.YELLOW}[CtxGuard:WARN]{cls.RESET} {msg}\n")
        sys.stdout.flush()

    @classmethod
    def error(cls, msg: str) -> None:
        sys.stderr.write(f"{cls.RED}[CtxGuard:ERROR]{cls.RESET} {msg}\n")
        sys.stderr.flush()

    @classmethod
    def banner(cls, version: str = "0.1.0", host: str = "127.0.0.1", port: int = 8787) -> None:
        banner_text = rf"""
{cls.CYAN}{cls.BOLD}  ____ _        ____                 _ 
 / ___| |_ _  _/ ___|_   _  __ _ _ __| |
| |   | __\ \/ / |  _| | | |/ _` | '__| |
| |___| |_ >  <| |_| | |_| | (_| | |  |_|
 \____|\__/_/\_\\____|\__,_|\__,_|_|  (_)
{cls.RESET}
{cls.BOLD}CtxGuard v{version}{cls.RESET} - Ultra-lightweight LLM Context Optimization Gateway
Listening on {cls.GREEN}http://{host}:{port}{cls.RESET}
Ready to optimize context for Cursor, Claude Code, and Agent SDKs.
"""
        sys.stdout.write(banner_text)
        sys.stdout.flush()
