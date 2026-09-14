"""Config management command for CtxGuard."""

import argparse
from pathlib import Path
import sys
import yaml
from dataclasses import asdict

from ctxguard.config.loader import ConfigLoader
from ctxguard.config.validator import validate_config
from ctxguard.utils.console import Console


def execute_config(args: argparse.Namespace) -> None:
    """Execute ctxguard config commands (init, validate, show)."""
    subaction = args.action

    if subaction == "init":
        target = Path.cwd() / "ctxguard.yaml"
        if target.exists() and not args.force:
            Console.warning(f"File {target} already exists. Use --force to overwrite.")
            return

        example_file = Path(__file__).resolve().parent.parent.parent / "ctxguard.yaml.example"
        if example_file.exists():
            content = example_file.read_text(encoding="utf-8")
        else:
            default_cfg = ConfigLoader.load_config()
            content = yaml.dump(asdict(default_cfg), sort_keys=False)

        target.write_text(content, encoding="utf-8")
        Console.success(f"Initialized configuration file at {target}")

    elif subaction == "validate":
        try:
            config = ConfigLoader.load_config(config_path=args.config)
            warnings = validate_config(config)
            Console.success("Configuration is valid!")
            for w in warnings:
                Console.warning(w)
        except Exception as e:
            Console.error(f"Configuration validation failed:\n{e}")
            sys.exit(1)

    elif subaction == "show":
        try:
            config = ConfigLoader.load_config(config_path=args.config)
            cfg_dict = asdict(config)
            print(yaml.dump(cfg_dict, sort_keys=False))
        except Exception as e:
            Console.error(f"Failed to load configuration: {e}")
            sys.exit(1)
    else:
        Console.info("Use: ctxguard config [init|validate|show]")
