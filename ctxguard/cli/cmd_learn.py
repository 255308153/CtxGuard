"""CLI command handler for ctxguard learn."""

import argparse
import os
from pathlib import Path
import sys
from typing import List

from ctxguard.learn.engine import LearnEngine
from ctxguard.learn.models import LearnedRule
from ctxguard.learn.plugins import PluginRegistry
from ctxguard.learn.pruner import RulePruner
from ctxguard.utils.console import Console


def _load_learn_config(config_path):
    """Best-effort load of the learn section so CLI runs honour ctxguard.yaml.

    A malformed or missing config must not abort learning: the defaults are perfectly
    usable, and failing here would make `ctxguard learn` unusable in a bare project.
    """
    try:
        from ctxguard.config.loader import ConfigLoader
        return ConfigLoader.load_config(config_path).learn
    except Exception:
        return None


def resolve_target_files(args, project_path: Path, agent_type: str) -> List[Path]:
    """Resolve the write targets *before* analysis starts.

    Ordering matters: the prior rule baseline has to be read from these exact files and
    fed into the analyzer prompt. Resolving them afterwards would mean learning without
    knowing what is already installed, which is what produced duplicate rules.

    NOTE: this deliberately keeps the CLI's historical default (AGENTS.md +
    CLAUDE.local.md) and does not consult ``learn.target_files`` from ctxguard.yaml.
    Honouring that field would silently redirect writes to .cursorrules/.windsurfrules,
    and which files should receive auto-generated rules is an open decision.
    """
    target_file = getattr(args, "target", None)
    if target_file:
        return [Path(target_file).resolve()]

    target_files: List[Path] = []
    if agent_type != "auto":
        p = PluginRegistry.get(agent_type)
        if p:
            target_files.extend(p.get_default_target_files(project_path))
    if target_files:
        return target_files

    # Default to AGENTS.md and CLAUDE.local.md
    return [
        project_path / "AGENTS.md",
        project_path / "CLAUDE.local.md",
    ]


def execute_learn(args: argparse.Namespace) -> None:
    """Execute the automated self-evolution learning engine."""
    project_path = Path(getattr(args, "project", None) or os.getcwd()).resolve()
    agent_type = getattr(args, "agent", "auto") or "auto"
    apply_mode = getattr(args, "apply", False)
    dry_run = getattr(args, "dry_run", False)
    threshold = getattr(args, "threshold", 3) or 3
    model = getattr(args, "model", "claude-3-5-sonnet") or "claude-3-5-sonnet"

    learn_cfg = _load_learn_config(getattr(args, "config", None))
    max_rules = getattr(learn_cfg, "max_rules", RulePruner.MAX_RULES_BUDGET)
    marker = "CTXGUARD_AUTO_RULES"

    Console.info(f"CtxGuard Self-Evolution Learn Engine (Target: {project_path})")
    Console.info(f"Agent Ecosystem: {agent_type.upper()} | Model: {model} | Loop Threshold: {threshold}")

    engine = LearnEngine(model=model, loop_threshold=threshold, max_rules=max_rules)

    # 1. Resolve write targets first, then read the installed baseline from them.
    target_files = resolve_target_files(args, project_path, agent_type)
    prior_rules: List[LearnedRule] = engine.load_prior_rules(target_files, marker=marker)
    if prior_rules:
        Console.info(f"Loaded {len(prior_rules)} prior rule(s) as analysis baseline.")

    # 2. Learn and synthesize rules (loops are detected once, with measured waste)
    loops = engine.detect_incident_loops(
        engine.discover_sessions(
            agent_type=agent_type,
            project_path=project_path,
            lookback_hours=48,
            limit=50,
        )
    )
    rules = engine.learn_and_synthesize(
        agent_type=agent_type,
        project_path=project_path,
        lookback_hours=48,
        limit=50,
        prior_rules=prior_rules,
    )

    Console.info(f"Discovered and synthesized {len(rules)} rule(s) across {len(loops)} incident loop(s).")
    for loop in loops[:5]:
        Console.info(
            f"  loop [{loop.pattern_type}] `{loop.target_identifier}` "
            f"x{loop.occurrence_count} ~{loop.wasted_tokens} tokens wasted"
        )

    # 3. Output preview or atomic apply. The preview must reflect the merge and the
    #    capacity cap, otherwise it advertises rules that would never be persisted.
    if dry_run or not apply_mode:
        Console.warning("Dry run mode: displaying preview without writing to disk.")
        for tf in target_files:
            preview = engine.preview_rules(rules, target_file=tf, marker=marker)
            print(f"\n### Preview for: {tf}\n<!-- {marker}:START -->\n{preview}\n<!-- {marker}:END -->\n")
        Console.info("To persist rules to disk, run with `--apply`.")
        return

    for tf in target_files:
        try:
            success = engine.apply_rules(rules, target_file=tf, marker=marker)
            if success:
                Console.success(f"Successfully synchronized rules with carry-forward to: {tf}")
        except Exception as e:
            Console.error(f"Failed to write rules to {tf}: {e}")
