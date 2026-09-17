"""Tool Delta & Shadow State Compressor operator."""

import re
from typing import Dict, List, Optional, Set
from ctxguard.config.schema import ToolDeltaConfig
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import Message, RequestContext
from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class ToolDeltaCompressor(BaseCompressor):
    """Session-scoped shadow state engine that computes and emits set deltas for repetitive tool outputs."""

    CODE_BLOCK_REGEX = re.compile(
        r"(```([a-zA-Z0-9_\-\+]*)\n([\s\S]*?)```)",
        re.MULTILINE
    )

    def __init__(
        self,
        config: ToolDeltaConfig,
        fingerprint_repo: Optional[FingerprintRepository] = None
    ):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        # session_id -> { category_key -> Set[item_line] }
        self.session_snapshots: Dict[str, Dict[str, Set[str]]] = {}
        self.session_fingerprints: Dict[str, Dict[str, str]] = {}

    @property
    def name(self) -> str:
        return "tool_delta_compressor"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def _is_list_like_text(self, lines: List[str]) -> bool:
        """Heuristic to detect if text looks like a directory listing, file search, or item list."""
        if len(lines) < self.config.min_items:
            return False

        # Check if lines have common list/path patterns (e.g. paths with slashes, bullets, sizes, or single identifiers)
        path_or_item_count = 0
        for line in lines[:30]:
            l_str = line.strip()
            if "/" in l_str or "\\" in l_str or l_str.startswith(("-", "*", "+", "[", "{")) or len(l_str.split()) <= 4:
                path_or_item_count += 1

        return path_or_item_count >= min(10, len(lines[:30]))

    def _derive_category_key(self, lines: List[str]) -> str:
        """Derive a canonical category key for the listing."""
        dirs = set()
        for l in lines:
            if "/" in l:
                dirs.add(l.rsplit("/", 1)[0])
            elif "\\" in l:
                dirs.add(l.rsplit("\\", 1)[0])
        if dirs:
            top_dirs = sorted(list(dirs))[:3]
            return compute_short_fingerprint("::".join(top_dirs), length=16)
        return "general_list"

    def _diff_and_compress(self, text: str, session_id: str = "default") -> Optional[str]:
        if not text:
            return None

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not self._is_list_like_text(lines):
            return None

        current_set = set(lines)

        if session_id not in self.session_snapshots:
            self.session_snapshots[session_id] = {}
        sess_store = self.session_snapshots[session_id]

        # Robust snapshot matching via Jaccard similarity
        best_key = None
        best_overlap = 0.0
        for key, prev_set in sess_store.items():
            intersection = len(current_set & prev_set)
            union = len(current_set | prev_set)
            overlap = intersection / max(1, union)
            if overlap > best_overlap:
                best_overlap = overlap
                best_key = key

        # If no matching snapshot with >= 50% overlap, record as new snapshot and pass through
        if not best_key or best_overlap < 0.5:
            cat_key = self._derive_category_key(lines) + f"_{len(sess_store)}"
            sess_store[cat_key] = current_set
            return None

        prev_set = sess_store[best_key]
        sess_store[best_key] = current_set

        # Calculate set differences
        added = sorted(list(current_set - prev_set))
        removed = sorted(list(prev_set - current_set))
        total_changes = len(added) + len(removed)
        total_items = len(current_set)

        # Store in fingerprint repository for reversible retrieval
        sha = compute_sha256(text)
        short_sha = compute_short_fingerprint(text, length=12)

        if session_id not in self.session_fingerprints:
            self.session_fingerprints[session_id] = {}
        self.session_fingerprints[session_id][sha] = text
        self.session_fingerprints[session_id][short_sha] = text

        if self.fingerprint_repo:
            self.fingerprint_repo.save_fingerprint(sha, session_id, text)
            self.fingerprint_repo.save_fingerprint(short_sha, session_id, text)

        # Case 1: Unchanged state
        if total_changes == 0:
            return f"[CtxGuard Tool Delta: State unchanged ({total_items} items identical to previous check). Use ctx_expand('{short_sha}') for full output]"

        # Case 2: Small delta within thresholds
        delta_ratio = total_changes / max(1, total_items)
        if total_changes <= self.config.max_delta_items and delta_ratio <= self.config.max_delta_ratio:
            unchanged_count = total_items - len(added)
            delta_lines = [
                f"[CtxGuard Tool Delta: {total_items} total items. Showing changes since previous check:]"
            ]
            if added:
                delta_lines.append(f"+ Added ({len(added)}):")
                for item in added:
                    delta_lines.append(f"  + {item}")
            if removed:
                delta_lines.append(f"- Removed ({len(removed)}):")
                for item in removed:
                    delta_lines.append(f"  - {item}")
            delta_lines.append(f"({unchanged_count} items unchanged. Use ctx_expand('{short_sha}') for full output)")
            return "\n".join(delta_lines)

        # Massive changes: pass through
        return None

    def compress_text(self, text: str) -> str:
        res = self._diff_and_compress(text, session_id="default")
        return res if res is not None else text

    def process(self, context: RequestContext, target_messages: List[Message]) -> None:
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"

        for msg in target_messages:
            if msg.role == "assistant":
                continue  # Never mutate assistant messages

            text = msg.get_text_content()
            if not text:
                continue

            # Case 1: Code block containing listing
            if "```" in text:
                def replace_block(match: re.Match) -> str:
                    full_block = match.group(1)
                    lang = (match.group(2) or "").strip()
                    body = match.group(3)
                    compressed = self._diff_and_compress(body, session_id=session_id)
                    if compressed:
                        return f"```{lang}\n{compressed}\n```"
                    return full_block

                optimized = self.CODE_BLOCK_REGEX.sub(replace_block, text)
                if optimized != text:
                    msg.set_text_content(optimized)
                    if self.name not in context.applied_compressors:
                        context.applied_compressors.append(self.name)
            else:
                # Case 2: Plain text tool output
                compressed = self._diff_and_compress(text, session_id=session_id)
                if compressed and compressed != text:
                    msg.set_text_content(compressed)
                    if self.name not in context.applied_compressors:
                        context.applied_compressors.append(self.name)
