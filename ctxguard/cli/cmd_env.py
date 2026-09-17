"""CLI command for outputting or injecting environment variables for agent integrations."""

import argparse
from ctxguard.utils.console import Console
from ctxguard.cli.config_patcher import AgentConfigAutoDetector

def execute_env(args: argparse.Namespace) -> None:
    """Execute ctxguard env command."""
    port = getattr(args, "port", 8787)
    auto_patch = getattr(args, "patch", False)

    if auto_patch:
        Console.info("Auto-detecting and patching local agent config files...")
        discovered = AgentConfigAutoDetector.discover_and_save_upstreams()
        for k, v in discovered.items():
            Console.success(f"Remembered original upstream for {k}: {v}")
        Console.success("All local agent configs smoothly pointed to CtxGuard!")
        return

    # Normal output
    Console.info(f"CtxGuard Agent Environment Presets (Target: {args.agent}, Port: {port})")
    print("\n# Shell Environment Exports:")
    print(f'export ANTHROPIC_BASE_URL="http://127.0.0.1:{port}/v1"')
    print(f'export OPENAI_BASE_URL="http://127.0.0.1:{port}/v1"')
    print(f'export DEEPSEEK_BASE_URL="http://127.0.0.1:{port}/v1"')
    print(f'export CTXGUARD_URL="http://127.0.0.1:{port}"')
