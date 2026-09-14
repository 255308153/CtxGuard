"""High-performance hashing utilities for CtxGuard."""

import hashlib
from typing import Union


def compute_sha256(content: Union[str, bytes]) -> str:
    """Compute standard full SHA-256 hexadecimal hash."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def compute_short_fingerprint(content: Union[str, bytes], length: int = 12) -> str:
    """Compute short SHA-256 fingerprint for concise token references."""
    full_hash = compute_sha256(content)
    return full_hash[:length]
