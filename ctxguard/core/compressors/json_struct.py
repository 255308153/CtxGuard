"""Homogeneous JSON array structure compressor."""

import re
from typing import Any, Dict, List
import orjson

from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext
from ctxguard.config.schema import JSONCompressorConfig


class JSONStructCompressor(BaseCompressor):
    """Compresses large arrays of homogeneous dictionaries into compact schema+rows format."""

    # Matches JSON-like array blocks in text
    JSON_ARRAY_REGEX = re.compile(r"(\[\s*\{[\s\S]*?\}\s*\])")

    def __init__(self, config: JSONCompressorConfig):
        self.config = config

    @property
    def name(self) -> str:
        return "json_struct_compressor"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def _try_compress_json_array(self, raw_json_str: str) -> str:
        """Attempt to parse and compress a JSON array string."""
        try:
            parsed = orjson.loads(raw_json_str)
        except Exception:
            return raw_json_str

        if not isinstance(parsed, list) or len(parsed) < self.config.min_array_length:
            return raw_json_str

        # Check if all items are dicts with matching keys
        if not all(isinstance(item, dict) for item in parsed):
            return raw_json_str

        first_keys = list(parsed[0].keys())
        if not first_keys or len(first_keys) < 2:
            return raw_json_str

        # Check for key overlap
        first_keys_set = set(first_keys)
        for item in parsed[1:]:
            if set(item.keys()) != first_keys_set:
                return raw_json_str

        # Check ignore keys
        if any(k in self.config.ignore_keys for k in first_keys):
            return raw_json_str

        # Build schema and rows
        schema = first_keys
        rows: List[List[Any]] = []
        for item in parsed:
            rows.append([item.get(k) for k in schema])

        compact_obj = {
            "_schema": schema,
            "_rows": rows,
        }

        # Dump compact JSON
        return orjson.dumps(compact_obj).decode("utf-8")

    def compress_text(self, text: str) -> str:
        if not text or ("[" not in text and "{" not in text):
            return text

        # If the entire text is a JSON array
        stripped = text.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            compressed = self._try_compress_json_array(stripped)
            if compressed != stripped:
                return compressed

        # Otherwise find JSON array substrings
        def replace_match(match: re.Match) -> str:
            chunk = match.group(1)
            return self._try_compress_json_array(chunk)

        return self.JSON_ARRAY_REGEX.sub(replace_match, text)
