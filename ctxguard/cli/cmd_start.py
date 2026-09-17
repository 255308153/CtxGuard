"""Start command for CtxGuard gateway server."""

import argparse
import sys
import uvicorn

from ctxguard.config.loader import ConfigLoader
from ctxguard.proxy.server import create_app
from ctxguard.utils.console import Console


def execute_start(args: argparse.Namespace) -> None:
    """Execute ctxguard start command."""
    cli_overrides = {}
    if args.host:
        cli_overrides["host"] = args.host
    if args.port:
        cli_overrides["port"] = args.port
    if args.log_level:
        cli_overrides["log_level"] = args.log_level
    if args.provider:
        cli_overrides["default_provider"] = args.provider

    try:
        config = ConfigLoader.load_config(
            config_path=args.config,
            cli_overrides=cli_overrides,
        )
    except Exception as e:
        Console.error(f"Configuration error: {e}")
        sys.exit(1)

    from ctxguard import __version__
    Console.banner(version=__version__, host=config.server.host, port=config.server.port)

    app = create_app(config)

    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
        log_level=config.server.log_level.lower(),
    )
