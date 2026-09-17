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

    def has_protected_signature(self) -> bool:
        """Check if message contains cryptographic signatures or thinking blocks that cannot be mutated."""
        if isinstance(self.content, list):
            for block in self.content:
                if isinstance(block, dict) and (block.get("type") == "thinking" or "signature" in block):
                    return True
        if self.metadata.get("reasoning_content") or self.metadata.get("signature"):
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary representation."""
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            d["name"] = self.name
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Message":
        """Reconstruct message from dictionary representation."""
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            name=d.get("name"),
            tool_call_id=d.get("tool_call_id"),
            tool_calls=d.get("tool_calls"),
            metadata=d.get("metadata", {}),
        )

    def get_text_content(self) -> str:
        """Extract plain text representation from content, strictly excluding thinking blocks and signatures."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            texts = []
            for block in self.content:
                if isinstance(block, dict):
                    # NEVER expose thinking blocks or signatures to generic text compressors
                    if block.get("type") == "thinking" or "signature" in block or "thinking" in block:
                        continue
                    if "text" in block:
                        texts.append(str(block["text"]))
                    elif "content" in block and isinstance(block["content"], str):
                        texts.append(block["content"])
            return "\n".join(texts)
        return str(self.content)

    def set_text_content(self, new_text: str) -> None:
        """Update content with new text while preserving block structure and thinking/signature blocks intact."""
        if isinstance(self.content, str):
            self.content = new_text
        elif isinstance(self.content, list):
            # Check if list contains protected blocks (e.g. thinking, signature, tool_use)
            text_block_updated = False
            for block in self.content:
                if isinstance(block, dict):
                    if block.get("type") == "thinking" or "signature" in block:
                        continue
                    if "text" in block:
                        block["text"] = new_text
                        text_block_updated = True
                        break
                    elif "content" in block and isinstance(block["content"], str):
                        block["content"] = new_text
                        text_block_updated = True
                        break

            if not text_block_updated:
                has_protected = any(
                    isinstance(b, dict) and (b.get("type") == "thinking" or "signature" in b)
                    for b in self.content
                )
                if has_protected:
                    self.content.append({"type": "text", "text": new_text})
                elif len(self.content) == 1 and isinstance(self.content[0], dict) and "text" in self.content[0]:
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
    raw_bytes: Optional[bytes] = None
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
    metadata: Dict[str, Any] = field(default_factory=dict)
