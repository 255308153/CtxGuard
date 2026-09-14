"""Unit tests for FastTokenizer."""

from ctxguard.plugins.onnx.tokenizer import FastTokenizer


def test_fast_tokenizer_roundtrip():
    text = "const maxRetries: number = 3; // Retry limit\n"
    tokens = FastTokenizer.tokenize(text)
    assert len(tokens) > 5
    assert "const" in tokens
    assert "maxRetries" in tokens
    reconstructed = FastTokenizer.detokenize(tokens)
    assert reconstructed == text


def test_fast_tokenizer_cjk():
    text = "CtxGuard 是超轻量级 上下文 守护者。"
    tokens = FastTokenizer.tokenize(text)
    assert len(tokens) > 5
    assert "是" in tokens
    assert "超" in tokens
    reconstructed = FastTokenizer.detokenize(tokens)
    assert reconstructed == text
