"""Unit tests for SecretRedactor."""

import pytest
from ctxguard.config.schema import SecretRedactorConfig
from ctxguard.core.compressors.secret_redactor import SecretRedactor


def test_secret_redactor_openai_key():
    cfg = SecretRedactorConfig(enabled=True)
    redactor = SecretRedactor(cfg)

    text = "Use this API key: sk-abcdef1234567890abcdef1234567890 to call OpenAI."
    masked = redactor.mask_text(text)
    assert "sk-abcdef1234567890abcdef1234567890" not in masked
    assert "<REDACTED_OPENAI_KEY>" in masked


def test_secret_redactor_github_token():
    cfg = SecretRedactorConfig(enabled=True)
    redactor = SecretRedactor(cfg)

    text = "Clone with ghp_123456789012345678901234567890123456"
    masked = redactor.mask_text(text)
    assert "ghp_" not in masked
    assert "<REDACTED_GITHUB_TOKEN>" in masked


def test_secret_redactor_private_key():
    cfg = SecretRedactorConfig(enabled=True)
    redactor = SecretRedactor(cfg)

    text = """Here is the server key:
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0Y...
-----END RSA PRIVATE KEY-----
Ready to connect."""

    masked = redactor.mask_text(text)
    assert "MIIEowIBAAKCAQEA0Y" not in masked
    assert "<REDACTED_PRIVATE_KEY>" in masked


def test_secret_redactor_database_uri():
    cfg = SecretRedactorConfig(enabled=True)
    redactor = SecretRedactor(cfg)

    text = "Connect to postgres://postgres:SuperSecretPassword123@db.example.com:5432/main"
    masked = redactor.mask_text(text)
    assert "SuperSecretPassword123" not in masked
    assert "postgres://postgres:***@db.example.com:5432/main" in masked
