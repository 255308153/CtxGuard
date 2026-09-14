"""Idempotent atomic file writer for marker-isolated rule updating."""

import os
from pathlib import Path
import re
import tempfile
from typing import Optional


class AtomicRuleWriter:
    """Updates target rule files idempotently without breaking user manual configurations."""

    @classmethod
    def write_rules_to_file(cls, file_path: str, rendered_block: str, marker: str = "CTXGUARD_AUTO_RULES") -> bool:
        """Atomically insert or update marked rule block in the target file."""
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        marker_pattern = re.compile(
            rf"<!-- {re.escape(marker)}:START -->[\s\S]*?<!-- {re.escape(marker)}:END -->",
            re.MULTILINE,
        )

        existing_content = ""
        if target.is_file():
            existing_content = target.read_text(encoding="utf-8")

        if marker_pattern.search(existing_content):
            # Replace existing block
            new_content = marker_pattern.sub(rendered_block, existing_content)
        else:
            # Append block
            if existing_content.strip():
                new_content = f"{existing_content.rstrip()}\n\n{rendered_block}\n"
            else:
                new_content = f"{rendered_block}\n"

        # Atomic write via temp file
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), prefix=".tmp_rules_")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(new_content)
            os.replace(tmp_path, target)
            return True
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
