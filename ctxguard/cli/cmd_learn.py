"""Learn command for offline failure analysis and idempotent rule updating."""

import argparse
from pathlib import Path
import sys

from ctxguard.config.loader import ConfigLoader
from ctxguard.learn.scanner import LogScanner, LogEvent
from ctxguard.learn.digest import DigestBuilder
from ctxguard.learn.pivot_analyzer import PivotAnalyzer
from ctxguard.learn.loop_detector import LoopDetector
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.rule_renderer import RuleRenderer
from ctxguard.learn.atomic_writer import AtomicRuleWriter
from ctxguard.learn.pruner import RulePruner
from ctxguard.storage.db import DatabaseManager
from ctxguard.utils.console import Console


def execute_learn(args: argparse.Namespace) -> None:
    """Run offline failure analysis, success correlation, and rule update."""
    try:
        config = ConfigLoader.load_config(config_path=args.config if hasattr(args, "config") else None)
    except Exception:
        config = ConfigLoader.load_config()

    threshold = getattr(args, "threshold", None) or config.learn.detect_loop_threshold
    detector = LoopDetector(threshold=threshold)
    pivot_analyzer = PivotAnalyzer()
    extractor = CausalityExtractor()
    digest_builder = DigestBuilder(token_budget=80000)

    # 1. Multi-source event collection
    raw_events = []
    source_dir = getattr(args, "source", None)
    if source_dir:
        Console.info(f"Scanning Agent conversation logs from source: {source_dir}")
        raw_events.extend(LogScanner.scan_claude_logs(Path(source_dir)))
    else:
        # Default scan Claude logs
        claude_events = LogScanner.scan_claude_logs()
        if claude_events:
            Console.info(f"Found {len(claude_events)} events from Claude Code conversation history.")
            raw_events.extend(claude_events)

    db_path = getattr(args, "db", None) or config.learn.storage_db
    if Path(db_path).exists():
        Console.info(f"Scanning interaction logs from database: {db_path}")
        db_events = LogScanner.scan_ctxguard_db(Path(db_path))
        raw_events.extend(db_events)

    # 2. Digest builder (Token budget & episode condensation)
    condensed_events = digest_builder.build_digest(raw_events)
    Console.info(f"Processing {len(condensed_events)} critical failure/recovery events after digest condensation.")

    # 3. Success Correlation & Loop Mining
    pivots = pivot_analyzer.analyze_events(condensed_events)
    loop_incidents = detector.detect_loops_from_events(condensed_events)

    # 4. Synthesize 5-category rules with Headroom Pruner Budget Cap
    raw_rules = extractor.extract_rules(incidents=loop_incidents, pivots=pivots)
    rules = RulePruner.prune_and_merge_rules(raw_rules, max_budget=10)

    marker = "CTXGUARD_AUTO_RULES"
    rendered_block = RuleRenderer.render_markdown_block(rules, marker=marker)

    # Check execution mode: default is DRY-RUN unless --apply is explicitly passed
    is_apply = getattr(args, "apply", False) and not getattr(args, "dry_run", False)

    Console.info("=" * 60)
    Console.info(f" Discovered Pivots: {len(pivots)} | Loops: {len(loop_incidents)} | Total Rules: {len(rules)}")
    Console.info("=" * 60)

    if not is_apply:
        Console.info("--- [DRY RUN PREVIEW] Rules (Run with '--apply' to persist) ---")
        print(rendered_block)
        Console.info("=" * 60)
        Console.info(" To apply and persist these rules, run:")
        Console.info("   ctxguard learn --apply")
        return

    # Determine target files
    target_files = []
    if getattr(args, "target", None):
        target_files.append((args.target, marker))
    else:
        for tf in config.learn.target_files:
            target_files.append((tf.path, tf.marker))

    # Safe fallback if no target files configured
    if not target_files:
        target_files.append(("CLAUDE.local.md", marker))

    for path_str, _ in target_files:
        AtomicRuleWriter.write_rules_to_file(path_str, rendered_block)
        Console.success(f"Atomically updated rule file: {path_str} (Protected by .gitignore)")
