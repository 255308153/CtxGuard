import re

_TAGS_TO_STRIP = [
    re.compile(r"\[(?:Personal Knowledge Graph Context|User Context & Preferences|Relevant User Context & Preferences|Relevant User Context Preferences|Memory Extraction Protocol)\].*?\[\/(?:Personal Knowledge Graph Context|User Context & Preferences|Relevant User Context & Preferences|Relevant User Context Preferences|Memory Extraction Protocol)\]", re.DOTALL | re.IGNORECASE),
    re.compile(r"\[Relevant User Context[^\]]*\].*?\[\/Relevant User Context[^\]]*\]", re.DOTALL | re.IGNORECASE),
]

def sanitize_message_content(content: str) -> str:
    """Remove historical injected memory and extraction protocol blocks."""
    if not isinstance(content, str):
        return content
    res = content
    for pattern in _TAGS_TO_STRIP:
        res = pattern.sub("", res)
    return res.strip()
