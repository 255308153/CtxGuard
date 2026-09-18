"""AST-based symbol-level code skeletonizer and compressor."""

import ast
import re
from typing import Any, Dict, List, Optional, Tuple
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
        min_body_lines: int = 4,
        tool_injection_enabled: bool = True,
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
            if tool_injection_enabled:
                placeholder = f"{indent_str}...  # [CtxGuard: Implementation folded ({count} lines). Use ctx_expand('{short_sha}') if details needed]"
            else:
                placeholder = f"{indent_str}...  # [CtxGuard: Implementation folded ({count} lines)]"
            new_lines[start_idx:end_idx] = [placeholder]

        skeleton_code = "\n".join(new_lines)
        return skeleton_code


class TreeSitterSkeletonizer:
    """Industrial-grade multi-language AST code skeletonizer powered by Tree-sitter (TS, JS, Go, Rust, Java, C, C++, Python)."""

    _LANG_PARSERS: Dict[str, Tuple[Any, str]] = {}

    @classmethod
    def get_parser_and_lang(cls, lang_name: str) -> Optional[Tuple[Any, str]]:
        lang_key = lang_name.lower().strip()
        if lang_key in cls._LANG_PARSERS:
            return cls._LANG_PARSERS[lang_key]

        try:
            import tree_sitter_languages
            p = tree_sitter_languages.get_parser(lang_key if lang_key != "ts" else "typescript")
            if p:
                cls._LANG_PARSERS[lang_key] = (p, lang_key)
                return (p, lang_key)
        except Exception:
            pass

        try:
            from tree_sitter import Language, Parser

            if lang_key in ("python", "py"):
                import tree_sitter_python
                lang = Language(tree_sitter_python.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "python")
                return (p, "python")

            if lang_key in ("javascript", "js", "jsx"):
                import tree_sitter_javascript
                lang = Language(tree_sitter_javascript.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "javascript")
                return (p, "javascript")

            if lang_key in ("typescript", "ts"):
                import tree_sitter_typescript
                lang = Language(tree_sitter_typescript.language_typescript())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "typescript")
                return (p, "typescript")

            if lang_key in ("tsx",):
                import tree_sitter_typescript
                lang = Language(tree_sitter_typescript.language_tsx())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "tsx")
                return (p, "tsx")

            if lang_key in ("go", "golang"):
                import tree_sitter_go
                lang = Language(tree_sitter_go.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "go")
                return (p, "go")

            if lang_key in ("rust", "rs"):
                import tree_sitter_rust
                lang = Language(tree_sitter_rust.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "rust")
                return (p, "rust")

            if lang_key in ("java",):
                import tree_sitter_java
                lang = Language(tree_sitter_java.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "java")
                return (p, "java")

            if lang_key in ("c",):
                import tree_sitter_c
                lang = Language(tree_sitter_c.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "c")
                return (p, "c")

            if lang_key in ("cpp", "c++", "cc", "cxx"):
                import tree_sitter_cpp
                lang = Language(tree_sitter_cpp.language())
                p = Parser(lang)
                cls._LANG_PARSERS[lang_key] = (p, "cpp")
                return (p, "cpp")

        except Exception:
            return None

        return None

    @classmethod
    def skeletonize(
        cls,
        code_str: str,
        lang_name: str,
        short_sha: str,
        min_body_lines: int = 4,
        tool_injection_enabled: bool = True,
    ) -> Optional[str]:
        parser_info = cls.get_parser_and_lang(lang_name)
        if not parser_info:
            return None

        parser, canonical_lang = parser_info
        code_bytes = code_str.encode("utf-8")
        try:
            tree = parser.parse(code_bytes)
        except Exception:
            return None

        folds: List[Tuple[int, int, int, int]] = []
        body_node_types = {"statement_block", "block", "compound_statement", "constructor_body"}
        func_node_types = {
            "function_declaration", "function_definition", "function_item",
            "method_declaration", "method_definition", "constructor_declaration",
            "arrow_function"
        }

        def find_body(node: Any) -> None:
            if node.type in func_node_types:
                for child in node.children:
                    if child.type in body_node_types:
                        start_line = child.start_point[0]
                        end_line = child.end_point[0]
                        line_count = end_line - start_line + 1
                        if line_count >= min_body_lines:
                            indent_col = node.start_point[1]
                            folds.append((child.start_byte, child.end_byte, line_count, indent_col))
                        break
            for child in node.children:
                find_body(child)

        find_body(tree.root_node)
        if not folds:
            return None

        # Sort descending by start_byte to replace from bottom to top
        folds.sort(key=lambda x: x[0], reverse=True)
        mut_bytes = bytearray(code_bytes)

        comment_prefix = "#" if canonical_lang == "python" else "//"

        for start_b, end_b, line_count, indent_col in folds:
            indent_str = " " * indent_col
            if canonical_lang == "python":
                if tool_injection_enabled:
                    rep_text = f":\n{indent_str}    ...  # [CtxGuard: Implementation folded ({line_count} lines). Use ctx_expand('{short_sha}') if details needed]"
                else:
                    rep_text = f":\n{indent_str}    ...  # [CtxGuard: Implementation folded ({line_count} lines)]"
            else:
                if tool_injection_enabled:
                    rep_text = f" {{\n{indent_str}    {comment_prefix} [CtxGuard: Implementation folded ({line_count} lines). Use ctx_expand('{short_sha}') if details needed]\n{indent_str}}}"
                else:
                    rep_text = f" {{\n{indent_str}    {comment_prefix} [CtxGuard: Implementation folded ({line_count} lines)]\n{indent_str}}}"
            mut_bytes[start_b:end_b] = rep_text.encode("utf-8")

        return mut_bytes.decode("utf-8", errors="replace")


class GenericBraceSkeletonizer:
    """Heuristic skeletonizer fallback for C-style brace languages (JS/TS, Go, Rust, Java, C/C++)."""

    FUNC_DEF_REGEX = re.compile(
        r"^(\s*(?:export\s+)?(?:async\s+)?(?:function|func|fn|public|private|protected|def)?\s*[\w\<\>\[\]\s,\*&]+\([^\)]*\)[^{;\n]*)\{\s*$",
        re.MULTILINE
    )

    @classmethod
    def skeletonize(
        cls,
        code_str: str,
        short_sha: str,
        min_body_lines: int = 5,
        tool_injection_enabled: bool = True,
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
                    new_lines.append(header)
                    if tool_injection_enabled:
                        new_lines.append(f"{indent_str}    // [CtxGuard: Implementation folded ({body_lines_count} lines). Use ctx_expand('{short_sha}') if details needed]")
                    else:
                        new_lines.append(f"{indent_str}    // [CtxGuard: Implementation folded ({body_lines_count} lines)]")
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
        fingerprint_repo: Optional[FingerprintRepository] = None,
        tool_injection_enabled: bool = True,
    ):
        self.config = config
        self.fingerprint_repo = fingerprint_repo
        self.tool_injection_enabled = tool_injection_enabled
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

                # Priority 1: High-precision Tree-sitter multi-language parser
                skeleton = TreeSitterSkeletonizer.skeletonize(
                    code_body,
                    lang_name=lang,
                    short_sha=short_sha,
                    tool_injection_enabled=self.tool_injection_enabled,
                )

                # Priority 2: Native Python AST fallback for python
                if not skeleton and lang in ["python", "py", ""]:
                    skeleton = PythonASTSkeletonizer.skeletonize(
                        code_body,
                        short_sha=short_sha,
                        preserve_docstrings=self.config.preserve_docstrings,
                        tool_injection_enabled=self.tool_injection_enabled,
                    )

                # Priority 3: Heuristic Generic Brace Fallback
                if not skeleton and lang in self.config.supported_languages:
                    skeleton = GenericBraceSkeletonizer.skeletonize(
                        code_body,
                        short_sha=short_sha,
                        tool_injection_enabled=self.tool_injection_enabled,
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

            skeleton = TreeSitterSkeletonizer.skeletonize(
                text,
                lang_name="python",
                short_sha=short_sha,
                tool_injection_enabled=self.tool_injection_enabled,
            )
            if not skeleton:
                skeleton = PythonASTSkeletonizer.skeletonize(
                    text,
                    short_sha=short_sha,
                    preserve_docstrings=self.config.preserve_docstrings,
                    tool_injection_enabled=self.tool_injection_enabled,
                )
            if not skeleton:
                skeleton = GenericBraceSkeletonizer.skeletonize(
                    text,
                    short_sha=short_sha,
                    tool_injection_enabled=self.tool_injection_enabled,
                )

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
