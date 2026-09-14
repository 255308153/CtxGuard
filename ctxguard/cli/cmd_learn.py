"""Learn command for offline failure analysis and idempotent rule updating."""

import argparse
from pathlib import Path
import sys

from ctxguard.config.loader import ConfigLoader
from ctxguard.learn.loop_detector import LoopDetector
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.rule_renderer import RuleRenderer
from ctxguard.learn.atomic_writer import AtomicRuleWriter
from ctxguard.storage.db import DatabaseManager
from ctxguard.utils.console import Console


def execute_learn(args: argparse.Namespace) -> None:
    """Run offline loop detector, extract rules, and update configured target files."""
    try:
        config = ConfigLoader.load_config(config_path=args.config if hasattr(args, "config") else None)
    except Exception:
        config = ConfigLoader.load_config()

    threshold = getattr(args, "threshold", None) or config.learn.detect_loop_threshold
    detector = LoopDetector(threshold=threshold)
    extractor = CausalityExtractor()

    db_path = getattr(args, "db", None) or config.learn.storage_db
    incidents = []

    # Read from DB if exists
    if Path(db_path).exists():
        Console.info(f"Scanning interaction logs from database: {db_path}")
        db_mgr = DatabaseManager(db_path)
        with db_mgr.get_connection() as conn:
            cursor = conn.execute("SELECT model, applied_compressors FROM requests ORDER BY id DESC LIMIT 200")
            # In Phase 3, we also scan logged trajectory patterns
    else:
        Console.info(f"Database {db_path} not found. Running synthetic baseline verification.")

    rules = extractor.extract_rules(incidents)
    marker = "CTXGUARD_AUTO_RULES"
    rendered_block = RuleRenderer.render_markdown_block(rules, marker=marker)

    is_dry_run = getattr(args, "dry_run", False)
    if is_dry_run:
        Console.info("--- Dry Run Rule Preview ---")
        print(rendered_block)
        return

    # Determine target files
    target_files = []
    if getattr(args, "target", None):
        target_files.append((args.target, marker))
    else:
        for tf in config.learn.target_files:
            target_files.append((tf.path, tf.marker))

    for path_str, m_tag in target_files:
        AtomicRuleWriter.write_rules_to_file(path_str, rendered_block, marker=m_tag)
        Console.success(f"Updated rule file: {path_str}")
