"""AST-based symbol-level code skeletonizer and compressor."""

import ast
import re
from typing import Dict, List, Optional, Tuple
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext, Message
from ctxguard.config.schema import ASTCodeCompressorConfig
from ctxguard.utils.hasher import compute_sha256, compute_short_fingerprint
from ctxguard.storage.repository_fingerprint import FingerprintRepository


class PythonASTSkeletonizer:
    """Extracts function/class signatures and docstrings, folding implementation bodies using Python's native AST."""

    @classmethod
    def skeletonize(
        cls,
        code_str: str,
        short_sha: str,
        preserve_docstrings: bool = True,
        min_body_lines: int = 4
    ) -> Optional[str]:
        """Parse and skeletonize Python code. Returns None if code cannot be parsed as valid Python."""
        try:
            tree = ast.parse(code_str)
        except Exception:
            return None

        lines = code_str.splitlines()
        if len(lines) < min_body_lines:
            return None

        # Collect function ranges to fold: (body_start_line_1indexed, body_end_line_1indexed, indent_level, folded_count)
        folds: List[Tuple[int, int, int, int]] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.body:
                    continue

                body_nodes = node.body
                first_body_node = body_nodes[0]
                body_start_line = first_body_node.lineno

                # Check if first node is a docstring
                has_docstring = False
                if preserve_docstrings:
                    if isinstance(first_body_node, ast.Expr) and isinstance(first_body_node.value, ast.Constant) and isinstance(first_body_node.value.value, str):
                        has_docstring = True
                        if len(body_nodes) > 1:
                            first_body_node = body_nodes[1]
                            body_start_line = first_body_node.lineno
                        else:
                            # Only docstring in function body, no implementation to fold
                            continue

                body_end_line = getattr(node, "end_lineno", None)
                if body_end_line is None:
                    # Fallback for older python AST
                    body_end_line = max(getattr(n, "end_lineno", n.lineno) for n in body_nodes)

                folded_line_count = body_end_line - body_start_line + 1
                if folded_line_count >= min_body_lines:
                    # Determine indent from the first statement of the body
                    start_line_idx = body_start_line - 1
                    if start_line_idx < len(lines):
                        line_str = lines[start_line_idx]
                        indent = len(line_str) - len(line_str.lstrip())
                    else:
                        indent = node.col_offset + 4

                    folds.append((body_start_line, body_end_line, indent, folded_line_count))

        if not folds:
            return None

        # Sort folds from bottom to top so line replacements don't invalidate upper line numbers
        folds.sort(key=lambda f: f[0], reverse=True)

        new_lines = list(lines)
        for start_line, end_line, indent, count in folds:
            start_idx = start_line - 1
            end_idx = end_line  # slice is exclusive at end
            indent_str = " " * indent
            placeholder = f"{indent_str}...  # [CtxGuard: Implementation folded ({count} lines). Use ctx_expand('{short_sha}') if details needed]"
            new_lines[start_idx:end_idx] = [placeholder]

        skeleton_code = "\n".join(new_lines)
        return skeleton_code


class GenericBraceSkeletonizer:
    """Heuristic skeletonizer for C-style brace languages (JS/TS, Go, Rust, Java, C/C++)."""

    FUNC_DEF_REGEX = re.compile(
        r"^(\s*(?:export\s+)?(?:async\s+)?(?:function|func|fn|public|private|protected|def)?\s*[\w\<\>\[\]\s,\*&]+\([^\)]*\)[^{;\n]*)\{\s*$",
        re.MULTILINE
    )

    @classmethod
    def skeletonize(
        cls,
        code_str: str,
        short_sha: str,
        min_body_lines: int = 5
    ) -> Optional[str]:
        lines = code_str.splitlines()
        if len(lines) < min_body_lines:
            return None

        modified = False
        new_lines: List[str] = []
        i = 0
        n = len(lines)

        while i < n:
            line = lines[i]
            # Match function header ending with {
            match = cls.FUNC_DEF_REGEX.match(line)
            if match and "{" in line:
                header = line
                indent = len(line) - len(line.lstrip())
                indent_str = " " * indent
                body_lines_count = 0
                brace_depth = 1
                start_i = i + 1
                curr_i = start_i

                while curr_i < n and brace_depth > 0:
                    brace_depth += lines[curr_i].count("{") - lines[curr_i].count("}")
                    if brace_depth > 0:
                        body_lines_count += 1
                    curr_i += 1

                if brace_depth == 0 and body_lines_count >= min_body_lines:
                    # Successfully found closing brace
                    new_lines.append(header)
                    new_lines.append(f"{indent_str}    // [CtxGuard: Implementation folded ({body_lines_count} lines). Use ctx_expand('{short_sha}') if details needed]")
                    new_lines.append(f"{indent_str}}}")
                    i = curr_i
                    modified = True
                    continue

            new_lines.append(line)
            i += 1

        if modified:
            return "\n".join(new_lines)
        return None


class ASTCodeCompressor(BaseCompressor):
    """AST-based structural code skeletonizer that extracts signatures and folds implementations."""

    CODE_BLOCK_REGEX = re.compile(
        r"(```([a-zA-Z0-9_\-\+]*)\n([\s\S]*?)```)",
        re.MULTILINE
    )

    def __init__(
        self,
        config: ASTCodeCompressorConfig,
        fingerprint_repo: Optional[FingerprintRepository] = None
    ):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.session_fingerprints: Dict[str, Dict[str, str]] = {}

    @property
    def name(self) -> str:
        return "ast_code_compressor"

    def is_applicable(self, context: RequestContext) -> bool:
        return self.config.enabled

    def compress_text(self, text: str) -> str:
        # compress_text alone without session context
        return self._compress_code_content(text, session_id="default")

    def _compress_code_content(self, text: str, session_id: str = "default") -> str:
        if not text or len(text.splitlines()) < self.config.min_lines:
            return text

        if session_id not in self.session_fingerprints:
            self.session_fingerprints[session_id] = {}
        fingerprint_store = self.session_fingerprints[session_id]

        # Case 1: Markdown code block(s) present
        if "```" in text:
            def replace_block(match: re.Match) -> str:
                full_block = match.group(1)
                lang = (match.group(2) or "").strip().lower()
                code_body = match.group(3)

                if len(code_body.splitlines()) < self.config.min_lines:
                    return full_block

                sha = compute_sha256(code_body)
                short_sha = compute_short_fingerprint(code_body, length=12)

                # Save original code into fingerprint store
                fingerprint_store[sha] = code_body
                fingerprint_store[short_sha] = code_body
                if self.fingerprint_repo:
                    self.fingerprint_repo.save_fingerprint(sha, session_id, code_body)
                    self.fingerprint_repo.save_fingerprint(short_sha, session_id, code_body)

                skeleton = None
                if lang in ["python", "py", ""]:
                    skeleton = PythonASTSkeletonizer.skeletonize(
                        code_body,
                        short_sha=short_sha,
                        preserve_docstrings=self.config.preserve_docstrings
                    )

                if not skeleton and lang in self.config.supported_languages:
                    skeleton = GenericBraceSkeletonizer.skeletonize(
                        code_body,
                        short_sha=short_sha
                    )

                if skeleton and len(skeleton) < len(code_body):
                    return f"```{lang}\n{skeleton}\n```"
                return full_block

            return self.CODE_BLOCK_REGEX.sub(replace_block, text)

        # Case 2: Plain text that is a whole python/code file
        lines = text.splitlines()
        if len(lines) >= self.config.min_lines:
            sha = compute_sha256(text)
            short_sha = compute_short_fingerprint(text, length=12)

            fingerprint_store[sha] = text
            fingerprint_store[short_sha] = text
            if self.fingerprint_repo:
                self.fingerprint_repo.save_fingerprint(sha, session_id, text)
                self.fingerprint_repo.save_fingerprint(short_sha, session_id, text)

            skeleton = PythonASTSkeletonizer.skeletonize(
                text,
                short_sha=short_sha,
                preserve_docstrings=self.config.preserve_docstrings
            )
            if not skeleton:
                skeleton = GenericBraceSkeletonizer.skeletonize(text, short_sha=short_sha)

            if skeleton and len(skeleton) < len(text):
                return skeleton

        return text

    def process(self, context: RequestContext, target_messages: List[Message]) -> None:
        if not self.is_applicable(context):
            return

        session_id = context.request.session_id or "default"

        for msg in target_messages:
            if msg.role == "assistant":
                continue  # Never mutate assistant messages

            text = msg.get_text_content()
            if not text:
                continue

            optimized = self._compress_code_content(text, session_id=session_id)
            if optimized != text:
                msg.set_text_content(optimized)
                if self.name not in context.applied_compressors:
                    context.applied_compressors.append(self.name)
