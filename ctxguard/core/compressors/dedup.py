"""Session-level SHA-256 content fingerprinting and deduplication operator."""

import fnmatch
import re
from typing import Dict, List, Optional
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext, Message
from ctxguard.config.schema import DedupConfig
from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class DedupCompressor(BaseCompressor):
    """Detects and replaces repeated file contents and tool outputs with SHA-256 reference tags."""

    FILE_HINT_REGEX = re.compile(r"(?:(?:File|path|file_path):\s*([a-zA-Z0-9_\-\./\\]+)|```[a-zA-Z0-9_-]*\s*#?\s*([a-zA-Z0-9_\-\./\\]+))")

    def __init__(self, config: DedupConfig, fingerprint_repo: Optional[FingerprintRepository] = None):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.session_fingerprints: Dict[str, Dict[str, str]] = {}

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

    def index_prefix(self, context: RequestContext, frozen_messages: List[Message]) -> None:
        """Index contents in frozen history without modifying frozen messages."""
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"
        if session_id not in self.session_fingerprints:
            if len(self.session_fingerprints) >= 500:
                oldest = next(iter(self.session_fingerprints))
                del self.session_fingerprints[oldest]
            self.session_fingerprints[session_id] = {}

        fingerprint_store = self.session_fingerprints[session_id]

        for msg in frozen_messages:
            text = msg.get_text_content()
            if not text or len(text) < self.config.min_chars:
                continue

            sha = compute_sha256(text)
            short_sha = compute_short_fingerprint(text, length=12)

            # Skip redundant re-indexing and disk writes if already indexed in this session
            if sha in fingerprint_store:
                continue

            fingerprint_store[sha] = text
            fingerprint_store[short_sha] = text
            if self.fingerprint_repo:
                self.fingerprint_repo.save_fingerprint(sha, session_id, text)
                self.fingerprint_repo.save_fingerprint(short_sha, session_id, text)

    def process(self, context: RequestContext, target_messages: list[Message]) -> None:
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"
        if session_id not in self.session_fingerprints:
            if len(self.session_fingerprints) >= 500:
                oldest = next(iter(self.session_fingerprints))
                del self.session_fingerprints[oldest]
            self.session_fingerprints[session_id] = {}

        fingerprint_store = self.session_fingerprints[session_id]

        for msg in target_messages:
            # NEVER compress system or assistant messages to prevent prompt destruction and LLM mimicry
            if msg.role in ("system", "assistant"):
                continue

            text = msg.get_text_content()
            if not text or len(text) < self.config.min_chars:
                continue

            filename_hint = None
            match = self.FILE_HINT_REGEX.search(text[:300])
            if match:
                filename_hint = match.group(1) or match.group(2)

            if self._is_excluded(text, filename_hint):
                continue

            sha = compute_sha256(text)
            short_sha = compute_short_fingerprint(text, length=12)
            # STORAGE INVARIANT 2: Deduplication must strictly be scoped to the current session (session_id).
            # Never query cross-session global storage to mark content as duplicate, as new LLM conversation contexts
            # have never seen files from previous sessions and would be completely blinded.
            is_duplicate = (sha in fingerprint_store)

            if is_duplicate:
                line_count = len(text.splitlines())
                file_label = f"File: {filename_hint} | " if filename_hint else ""
                if self.config.tool_injection.enabled:
                    ref_tag = f"[Ref:sha256_{short_sha} | {file_label}{line_count} lines unchanged. Use ctx_expand('{short_sha}') if details needed]"
                else:
                    ref_tag = f"<!-- [Cached duplicate context: {file_label}{line_count} lines unchanged (sha256_{short_sha})] -->"

                msg.set_text_content(ref_tag)
                if self.name not in context.applied_compressors:
                    context.applied_compressors.append(self.name)
            else:
                fingerprint_store[sha] = text
                fingerprint_store[short_sha] = text
                if self.fingerprint_repo:
                    self.fingerprint_repo.save_fingerprint(sha, session_id, text)
                    self.fingerprint_repo.save_fingerprint(short_sha, session_id, text)

    def expand_ref(self, session_id: str, ref_id: str) -> Optional[str]:
        clean_ref = ref_id.replace("sha256_", "").strip()
        store = self.session_fingerprints.get(session_id, {})
        if clean_ref in store:
            return store[clean_ref]
        if self.fingerprint_repo:
            return self.fingerprint_repo.get_content(clean_ref)
        return None
