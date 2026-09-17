"""Secret and sensitive credential masking operator."""

import re
from typing import List, Pattern, Tuple
from ctxguard.config.schema import SecretRedactorConfig
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import Message, RequestContext


class SecretRedactor(BaseCompressor):
    """Detects and masks sensitive tokens, API keys, private keys, and passwords."""

    BUILTIN_PATTERNS: List[Tuple[str, Pattern[str]]] = [
        # Private Keys
        ("PRIVATE_KEY", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
        # OpenAI / generic sk- keys
        ("OPENAI_KEY", re.compile(r"\b(sk-[a-zA-Z0-9_\-]{20,})\b")),
        # Anthropic keys
        ("ANTHROPIC_KEY", re.compile(r"\b(ant-api[a-zA-Z0-9_\-]{20,})\b")),
        # GitHub Tokens
        ("GITHUB_TOKEN", re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{36,255}|github_pat_[A-Za-z0-9_]{82})\b")),
        # AWS Access Keys
        ("AWS_KEY", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
        # JWT / Bearer Tokens
        ("JWT_TOKEN", re.compile(r"\b(Bearer\s+)(ey[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)\b", re.IGNORECASE)),
        # Database URIs with credentials (e.g. postgres://user:password@host:port/db)
        ("DATABASE_URI", re.compile(r"((?:postgres|postgresql|mysql|mongodb|redis|amqp):\/\/[^\s:@\/]+:)([^\s@\/]+)(@[^\s\/]+)", re.IGNORECASE)),
    ]

    def __init__(self, config: SecretRedactorConfig):
        self.config = config
        self.compiled_custom_patterns: List[Pattern[str]] = []
        for pat_str in self.config.custom_patterns:
            try:
                self.compiled_custom_patterns.append(re.compile(pat_str))
            except Exception:
                pass

    @property
    def name(self) -> str:
        return "secret_redactor"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def mask_text(self, text: str) -> str:
        if not text:
            return text

        result = text

        # 1. Mask private keys
        for key_name, pat in self.BUILTIN_PATTERNS:
            if key_name == "PRIVATE_KEY":
                result = pat.sub("<REDACTED_PRIVATE_KEY>", result)
            elif key_name in ("OPENAI_KEY", "ANTHROPIC_KEY", "GITHUB_TOKEN", "AWS_KEY"):
                result = pat.sub(f"<REDACTED_{key_name}>", result)
            elif key_name == "JWT_TOKEN":
                result = pat.sub(r"\1<REDACTED_JWT>", result)
            elif key_name == "DATABASE_URI":
                result = pat.sub(r"\1***\3", result)

        # 2. Custom user patterns
        for custom_pat in self.compiled_custom_patterns:
            result = custom_pat.sub(self.config.mask_token, result)

        return result

    def compress_text(self, text: str) -> str:
        return self.mask_text(text)

    def process(self, context: RequestContext, target_messages: List[Message]) -> None:
        if not self.is_applicable(context):
            return

        for msg in target_messages:
            if msg.role == "assistant":
                continue  # Never mutate assistant responses

            text = msg.get_text_content()
            if not text:
                continue

            masked = self.mask_text(text)
            if masked != text:
                msg.set_text_content(masked)
                if self.name not in context.applied_compressors:
                    context.applied_compressors.append(self.name)
