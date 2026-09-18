"""Byte-stable Output Verbosity & Shaping Policy.
Aligned with CtxGuard Engine pure output steering specifications.
"""

from __future__ import annotations
from typing import Optional, Tuple, Dict, Any

STEERING_SENTINEL = "<ctxguard_output_shaping>"
STEERING_SUFFIX = "</ctxguard_output_shaping>"

VERBOSITY_LEVELS: Dict[int, str] = {
    1: (
        "## Output Style Guidelines\n"
        "- **Direct & Focused**: Start directly with the answer. Skip conversational openings, acknowledgments, or recaps.\n"
        "- **Clean Formatting**: Use clear headings, bullet points, and appropriate paragraph spacing for readability."
    ),
    2: (
        "## Output Style Guidelines\n"
        "- **Concise & Direct**: Skip conversational filler, preamble, and concluding summaries. Start directly with the substance.\n"
        "- **No Redundancy**: Do not echo back user prompt, full file contents, diffs, or tool outputs already present in the context. Reference them by file/line.\n"
        "- **Clear Structure**: Maintain clean markdown structure with clear bullet points, code blocks, and proper line breaks. Keep explanations tight and focused."
    ),
    3: (
        "## Output Style Guidelines\n"
        "- **High-Density**: Provide conclusions and actionable results directly. Omit intermediate rationale unless explicitly requested.\n"
        "- **Zero Echo**: Never reproduce unchanged code, logs, or context lines. Cite exact paths, line numbers, or symbol names.\n"
        "- **Precision Edits**: Prefer minimal, targeted diffs/edits over rewriting entire files.\n"
        "- **Clean Layout**: Keep responses neatly organized with bullet points and clear section headers."
    ),
    4: (
        "## Output Style Guidelines\n"
        "- **Minimal Tokens**: Provide only the direct answer and smallest possible targeted code edits.\n"
        "- **Zero Fluff**: No preamble, no postamble, no explanations, no echoing."
    ),
}

class OutputShaper:
    """Byte-stable output token shaping controller."""

    def __init__(self, level: int = 2):
        self.level = level

    @classmethod
    def get_steering_block(cls, level: int) -> Optional[str]:
        text = VERBOSITY_LEVELS.get(level)
        if not text:
            return None
        return f"{STEERING_SENTINEL}\n{text}\n{STEERING_SUFFIX}"

    @classmethod
    def shape_system_prompt(cls, existing_prompt: str, level: int = 2) -> Tuple[str, bool]:
        block = cls.get_steering_block(level)
        if not block:
            return existing_prompt, False

        start = existing_prompt.find(STEERING_SENTINEL)
        if start >= 0:
            end = existing_prompt.find(STEERING_SUFFIX, start)
            end = len(existing_prompt) if end < 0 else end + len(STEERING_SUFFIX)
            prefix = existing_prompt[:start].rstrip()
            suffix = existing_prompt[end:].lstrip("\n")
            parts = [p for p in (prefix, block, suffix) if p]
            updated = "\n\n".join(parts)
            return updated, updated != existing_prompt

        updated = f"{existing_prompt.rstrip()}\n\n{block}" if existing_prompt.strip() else block
        return updated, updated != existing_prompt

    def shape_request(self, request) -> bool:
        """Apply output shaping steering block to the request system prompt."""
        if hasattr(request, "system") and request.system:
            new_sys, changed = self.shape_system_prompt(request.system, self.level)
            request.system = new_sys
            return changed
        elif hasattr(request, "messages") and request.messages:
            for m in request.messages:
                if getattr(m, "role", "") == "system":
                    content = m.get_text_content() if hasattr(m, "get_text_content") else str(m.content)
                    new_sys, changed = self.shape_system_prompt(content, self.level)
                    m.content = new_sys
                    return changed
        return False
