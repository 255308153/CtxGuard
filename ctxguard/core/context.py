"""Unified context models for requests and responses across different LLM protocols."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class Message:
    """Unified message representation."""
    role: str                       # "system" | "user" | "assistant" | "tool"
    content: Union[str, List[Dict[str, Any]]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_text_content(self) -> str:
        """Extract plain text representation from content."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            texts = []
            for block in self.content:
                if isinstance(block, dict):
                    if "text" in block:
                        texts.append(str(block["text"]))
                    elif "content" in block and isinstance(block["content"], str):
                        texts.append(block["content"])
            return "\n".join(texts)
        return str(self.content)

    def set_text_content(self, new_text: str) -> None:
        """Update content with new text while preserving block structure if applicable."""
        if isinstance(self.content, str):
            self.content = new_text
        elif isinstance(self.content, list):
            # If single text block, update it; otherwise replace with new text
            if len(self.content) == 1 and isinstance(self.content[0], dict) and "text" in self.content[0]:
                self.content[0]["text"] = new_text
            else:
                self.content = new_text


@dataclass
class NormalizedRequest:
    """Standardized representation of incoming chat request."""
    protocol: str                   # "openai" | "anthropic"
    model: str
    messages: List[Message]
    system: Optional[str] = None    # Top-level system prompt (e.g. Anthropic)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    stream: bool = True
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)
    session_id: str = "default"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedResponse:
    """Standardized representation of outgoing chat response."""
    protocol: str
    id: str
    model: str
    content: str
    tool_calls: Optional[List[Dict[str, Any]]] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw_response: Any = None


@dataclass
class RequestContext:
    """Runtime processing context passed across pipeline stages and hooks."""
    request: NormalizedRequest
    original_tokens: int = 0
    optimized_tokens: int = 0
    compression_ratio: float = 1.0
    applied_compressors: List[str] = field(default_factory=list)
    state: Dict[str, Any] = field(default_factory=dict)
