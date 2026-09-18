"""Idempotent atomic file writer for marker-isolated rule updating."""

from __future__ import annotations
import os
from pathlib import Path
import re
import tempfile
from typing import Optional

class AtomicRuleWriter:
    """Updates target rule files idempotently without breaking user manual configurations."""

    @classmethod
    def ensure_gitignore_safety(cls, target_file: Path) -> None:
        """Ensure local private rule files (like CLAUDE.local.md) are ignored in .gitignore."""
        if not target_file.name.endswith(".local.md"):
            return
        gitignore_path = target_file.parent / ".gitignore"
        entry = target_file.name
        try:
            if gitignore_path.exists():
                content = gitignore_path.read_text(encoding="utf-8")
                if entry not in content:
                    with open(gitignore_path, "a", encoding="utf-8") as f:
                        f.write(f"\n# CtxGuard local agent rules\n{entry}\n")
            else:
                gitignore_path.write_text(f"# CtxGuard local agent rules\n{entry}\n", encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def write_rules_to_file(cls, file_path: str, rendered_block: str, marker: str = "CTXGUARD_AUTO_RULES") -> bool:
        """Atomically insert or update marked rule block in the target file."""
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        cls.ensure_gitignore_safety(target)

        start_tag = f"<!-- {marker}:START -->"
        end_tag = f"<!-- {marker}:END -->"
        
        # Also support CtxGuard Engine lowercase format matching
        alt_start = f"<!-- {marker.lower().replace('_', ':')}:start -->"
        alt_end = f"<!-- {marker.lower().replace('_', ':')}:end -->"

        pattern = re.compile(
            rf"(?:{re.escape(start_tag)}|{re.escape(alt_start)}).*?(?:{re.escape(end_tag)}|{re.escape(alt_end)})",
            re.DOTALL | re.IGNORECASE,
        )

        existing_content = ""
        if target.exists():
            try:
                existing_content = target.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                existing_content = target.read_bytes().decode("utf-8", errors="replace")

        if pattern.search(existing_content):
            updated_content = pattern.sub(rendered_block.strip(), existing_content)
        elif existing_content.strip():
            updated_content = f"{existing_content.rstrip()}\n\n{rendered_block.strip()}\n"
        else:
            updated_content = f"{rendered_block.strip()}\n"

        target_dir = target.parent
        with tempfile.NamedTemporaryFile("w", dir=target_dir, delete=False, encoding="utf-8") as tf:
            tf.write(updated_content)
            temp_name = tf.name

        os.replace(temp_name, str(target))
        return True
