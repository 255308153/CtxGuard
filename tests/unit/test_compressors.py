"""Unit tests for all CtxGuard compression operators."""

import pytest
from ctxguard.config.schema import (
    LogCleanerConfig,
    JSONCompressorConfig,
    DedupConfig,
)
from ctxguard.core.context import Message, NormalizedRequest, RequestContext
from ctxguard.core.compressors.ansi_cleaner import ANSICleaner
from ctxguard.core.compressors.progress_merger import ProgressMerger
from ctxguard.core.compressors.stacktrace import StacktraceFolder
from ctxguard.core.compressors.whitespace import WhitespaceCleaner
from ctxguard.core.compressors.json_struct import JSONStructCompressor
from ctxguard.core.compressors.dedup import DedupCompressor


def test_ansi_cleaner():
    cleaner = ANSICleaner(LogCleanerConfig(enabled=True, strip_ansi=True))
    colored_text = "\x1b[31mError: \x1b[0m\x1b[1;32mBuild Failed\x1b[0m on line 42"
    result = cleaner.compress_text(colored_text)
    assert result == "Error: Build Failed on line 42"
    assert "\x1b" not in result


def test_progress_merger():
    merger = ProgressMerger(LogCleanerConfig(enabled=True, merge_progress_bars=True))
    progress_log = (
        "Downloading package:\n"
        "[====>          ] 20%\n"
        "[========>      ] 40%\n"
        "[============>  ] 80%\n"
        "[==============>] 100%\n"
        "Done!"
    )
    result = merger.compress_text(progress_log)
    lines = result.splitlines()
    assert len(lines) == 3
    assert lines[0] == "Downloading package:"
    assert "[==============>] 100%" in lines[1]
    assert lines[2] == "Done!"


def test_whitespace_cleaner():
    cleaner = WhitespaceCleaner()
    messy_text = "def foo():   \n\n\n\n\n    return 1   \n\n\n"
    result = cleaner.compress_text(messy_text)
    assert result == "def foo():\n\n    return 1\n\n"


def test_stacktrace_folder():
    folder = StacktraceFolder(LogCleanerConfig(enabled=True, fold_repeated_stacktraces=True, stacktrace_threshold=3))
    repeated_error = (
        "Starting worker...\n"
        "ERROR: Connection refused by host 10.0.0.1:5432\n"
        "ERROR: Connection refused by host 10.0.0.1:5432\n"
        "ERROR: Connection refused by host 10.0.0.1:5432\n"
        "ERROR: Connection refused by host 10.0.0.1:5432\n"
        "ERROR: Connection refused by host 10.0.0.1:5432\n"
        "Worker stopped."
    )
    result = folder.compress_text(repeated_error)
    assert "identical line repeated 4 more times" in result
    assert "Worker stopped." in result


def test_json_struct_compressor():
    compressor = JSONStructCompressor(JSONCompressorConfig(enabled=True, min_array_length=3))
    json_array_text = (
        '[\n'
        '  {"id": 1, "name": "Alice", "role": "admin"},\n'
        '  {"id": 2, "name": "Bob", "role": "user"},\n'
        '  {"id": 3, "name": "Charlie", "role": "editor"}\n'
        ']'
    )
    result = compressor.compress_text(json_array_text)
    assert "_schema" in result
    assert "_rows" in result
    assert "Alice" in result and "Bob" in result


def test_dedup_compressor():
    dedup = DedupCompressor(DedupConfig(enabled=True, min_chars=50))
    
    file_content = (
        "// File: src/components/Header.tsx\n"
        "export function Header() {\n"
        "    return <header><h1>Welcome to MyApp</h1><nav>Navigation</nav></header>;\n"
        "}\n"
    )

    # First turn
    msg1 = Message(role="tool", content=file_content)
    req1 = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[msg1], session_id="test_session")
    ctx1 = RequestContext(request=req1)
    dedup.process(ctx1, [msg1])
    assert msg1.get_text_content() == file_content  # First time preserved

    # Second turn (same content in same session)
    msg2 = Message(role="tool", content=file_content)
    req2 = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[msg2], session_id="test_session")
    ctx2 = RequestContext(request=req2)
    dedup.process(ctx2, [msg2])
    
    assert "[Ref:sha256_" in msg2.get_text_content()
    assert "unchanged" in msg2.get_text_content()
