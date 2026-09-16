"""Compressor operators package for CtxGuard."""

from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.compressors.ansi_cleaner import ANSICleaner
from ctxguard.core.compressors.progress_merger import ProgressMerger
from ctxguard.core.compressors.stacktrace import StacktraceFolder
from ctxguard.core.compressors.json_struct import JSONStructCompressor
from ctxguard.core.compressors.whitespace import WhitespaceCleaner
from ctxguard.core.compressors.dedup import DedupCompressor
from ctxguard.core.compressors.ast_code import ASTCodeCompressor
from ctxguard.core.compressors.git_diff import GitDiffCompressor

__all__ = [
    "BaseCompressor",
    "ANSICleaner",
    "ProgressMerger",
    "StacktraceFolder",
    "JSONStructCompressor",
    "WhitespaceCleaner",
    "DedupCompressor",
    "ASTCodeCompressor",
    "GitDiffCompressor",
]
