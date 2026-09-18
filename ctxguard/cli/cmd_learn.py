"""CLI command handler for ctxguard learn."""

import argparse
import os
from pathlib import Path
import sys
from typing import List

from ctxguard.learn.engine import LearnEngine
from ctxguard.learn.plugins import PluginRegistry
from ctxguard.utils.console import Console


def execute_learn(args: argparse.Namespace) -> None:
    """Execute the automated self-evolution learning engine."""
    project_path = Path(getattr(args, "project", None) or os.getcwd()).resolve()
    agent_type = getattr(args, "agent", "auto") or "auto"
    target_file = getattr(args, "target", None)
    apply_mode = getattr(args, "apply", False)
    dry_run = getattr(args, "dry_run", False)
    threshold = getattr(args, "threshold", 3) or 3
    model = getattr(args, "model", "claude-3-5-sonnet") or "claude-3-5-sonnet"

    Console.info(f"CtxGuard Self-Evolution Learn Engine (Target: {project_path})")
    Console.info(f"Agent Ecosystem: {agent_type.upper()} | Model: {model} | Loop Threshold: {threshold}")

    engine = LearnEngine(model=model, loop_threshold=threshold)

    # 1. Learn and synthesize rules
    rules = engine.learn_and_synthesize(
        agent_type=agent_type,
        project_path=project_path,
        lookback_hours=48,
        limit=50,
    )

    Console.info(f"Discovered and synthesized {len(rules)} rule(s) across incident loops.")

    # 2. Determine target files
    target_files: List[Path] = []
    if target_file:
        target_files.append(Path(target_file).resolve())
    else:
        # Resolve defaults based on agent
        if agent_type != "auto":
            p = PluginRegistry.get(agent_type)
            if p:
                target_files.extend(p.get_default_target_files(project_path))
        if not target_files:
            # Default to AGENTS.md and CLAUDE.local.md
            target_files = [
                project_path / "AGENTS.md",
                project_path / "CLAUDE.local.md",
            ]

    # 3. Output preview or atomic apply
    marker = "CTXGUARD_AUTO_RULES"
    rendered_preview = engine.writer.render_body(rules)

    if dry_run or not apply_mode:
        Console.warning("Dry run mode: displaying preview without writing to disk.")
        print(f"\n<!-- {marker}:START -->\n{rendered_preview}\n<!-- {marker}:END -->\n")
        Console.info("To persist rules to disk, run with `--apply`.")
        return

    for tf in target_files:
        try:
            success = engine.apply_rules(rules, target_file=tf, marker=marker)
            if success:
                Console.success(f"Successfully synchronized rules with carry-forward to: {tf}")
        except Exception as e:
            Console.error(f"Failed to write rules to {tf}: {e}")
