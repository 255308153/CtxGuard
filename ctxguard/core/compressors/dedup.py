"""Session-level SHA-256 content fingerprinting and deduplication operator."""

import fnmatch
import re
from collections import Counter
from typing import Dict, List, Optional, Tuple
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext, Message
from ctxguard.config.schema import DedupConfig
from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class DedupCompressor(BaseCompressor):
    """Detects and replaces repeated file contents and tool outputs with SHA-256 reference tags.

    SAFETY INVARIANT (2026-10-09 incident, "agent re-reads forever and never edits"):
    A ref tag carries NO payload. It is only meaningful when the very same request still
    holds another verbatim copy of that content. Folding the *last* copy leaves the model
    blind, so it re-issues the same `read` every turn and the edit never lands.

    Therefore folding is decided **per payload**, never across requests:

    * the frozen prefix is emitted first, so a verbatim copy there already satisfies the rule;
    * otherwise the FIRST occurrence in the compressible suffix is kept verbatim;
    * only the 2nd..Nth occurrence of the same text inside the SAME payload gets folded.

    Historical fingerprints stay in `session_fingerprints` for `expand_ref()` lookups, but
    they are NEVER used as the reason to replace a message.
    """

    FILE_HINT_REGEX = re.compile(r"(?:(?:File|path|file_path):\s*([a-zA-Z0-9_\-\./\\]+)|```[a-zA-Z0-9_-]*\s*#?\s*([a-zA-Z0-9_\-\./\\]+))")

    def __init__(self, config: DedupConfig, fingerprint_repo: Optional[FingerprintRepository] = None):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.session_fingerprints: Dict[str, Dict[str, str]] = {}
        # Per-request tally of content emitted *verbatim* by the frozen prefix.
        # Rewritten on every index_prefix() call: the prefix is byte-stable and may already
        # contain ref placeholders frozen in by earlier turns, so it can never be assumed
        # to carry a full copy of anything.
        self._prefix_shas: Dict[str, Counter] = {}

    @property
    def name(self) -> str:
        return "dedup_compressor"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def _is_excluded(self, text: str, filename_hint: Optional[str] = None) -> bool:
        if filename_hint:
            for pat in self.config.exclude_patterns:
                if fnmatch.fnmatch(filename_hint, pat):
                    return True
        for pat in self.config.exclude_patterns:
            if fnmatch.fnmatch(text[:200], pat):
                return True
        return False

    def compress_text(self, text: str) -> str:
        return text

    def _store_for(self, session_id: str) -> Dict[str, str]:
        if session_id not in self.session_fingerprints:
            if len(self.session_fingerprints) >= 500:
                oldest = next(iter(self.session_fingerprints))
                del self.session_fingerprints[oldest]
                self._prefix_shas.pop(oldest, None)
            self.session_fingerprints[session_id] = {}
        return self.session_fingerprints[session_id]

    def _plan(self, msg: Message) -> Optional[Tuple[str, str, Optional[str], str, bool]]:
        """Classify one message: (sha, short_sha, filename_hint, text, excluded) or None."""
        text = msg.get_text_content()
        if not text or len(text) < self.config.min_chars:
            return None

        filename_hint = None
        match = self.FILE_HINT_REGEX.search(text[:300])
        if match:
            filename_hint = match.group(1) or match.group(2)

        return (
            compute_sha256(text),
            compute_short_fingerprint(text, length=12),
            filename_hint,
            text,
            self._is_excluded(text, filename_hint),
        )

    def index_prefix(self, context: RequestContext, frozen_messages: List[Message]) -> None:
        """Index contents in frozen history without modifying frozen messages."""
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"
        fingerprint_store = self._store_for(session_id)

        # Reset every request: this describes *this* payload only.
        prefix_shas: Counter = Counter()
        self._prefix_shas[session_id] = prefix_shas

        for msg in frozen_messages:
            plan = self._plan(msg)
            if plan is None:
                continue
            sha, short_sha, _filename_hint, text, _excluded = plan

            # Emitted verbatim in the payload -> may act as the visible copy that makes
            # folding a later duplicate safe.
            prefix_shas[sha] += 1

            # Skip redundant re-indexing if already indexed in this session
            if sha in fingerprint_store:
                continue

            fingerprint_store[sha] = text
            fingerprint_store[short_sha] = text

    def process(self, context: RequestContext, target_messages: list[Message]) -> None:
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"
        fingerprint_store = self._store_for(session_id)
        prefix_shas = self._prefix_shas.get(session_id, Counter())

        # Shas that are (or will be) visible verbatim somewhere in this payload.
        # The frozen prefix comes first, so its copies count as already emitted.
        emitted: Counter = Counter(prefix_shas)

        for msg in target_messages:
            # NEVER compress system or assistant messages to prevent prompt destruction and LLM mimicry
            if msg.role in ("system", "assistant"):
                continue

            plan = self._plan(msg)
            if plan is None:
                continue
            sha, short_sha, filename_hint, text, excluded = plan

            if excluded:
                # Left verbatim by policy -> it can back a later duplicate.
                emitted[sha] += 1
                continue

            if emitted[sha] == 0:
                # Sole copy in this payload: it MUST survive. Index it instead of folding.
                emitted[sha] += 1
                fingerprint_store[sha] = text
                fingerprint_store[short_sha] = text
                continue

            # A verbatim copy is already visible in this same payload -> safe to fold.
            line_count = len(text.splitlines())
            file_label = f"File: {filename_hint} | " if filename_hint else ""
            if self.config.tool_injection.enabled:
                ref_tag = f"[Ref:sha256_{short_sha} | {file_label}{line_count} lines unchanged. Use ctx_expand('{short_sha}') if details needed]"
            else:
                ref_tag = f"<!-- [Cached duplicate context: {file_label}{line_count} lines unchanged (sha256_{short_sha})] -->"

            msg.set_text_content(ref_tag)
            if self.name not in context.applied_compressors:
                context.applied_compressors.append(self.name)

            # Only persist to SQLite when content is actually folded/compressed (single write of short_sha)
            if self.fingerprint_repo:
                self.fingerprint_repo.save_fingerprint(
                    short_sha,
                    session_id,
                    text,
                    max_records=getattr(self.config, "max_records", 1000),
                )

    def expand_ref(self, session_id: str, ref_id: str) -> Optional[str]:
        clean_ref = ref_id.replace("sha256_", "").strip()
        store = self.session_fingerprints.get(session_id, {})
        if clean_ref in store:
            return store[clean_ref]
        if self.fingerprint_repo:
            return self.fingerprint_repo.get_content(clean_ref, session_id=session_id) or self.fingerprint_repo.get_content(clean_ref)
        return None
