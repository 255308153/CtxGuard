"""Unit tests for ASTCodeCompressor and skeletonizers."""

import ast
import pytest
from ctxguard.config.schema import ASTCodeCompressorConfig
from ctxguard.core.compressors.ast_code import (
    ASTCodeCompressor,
    PythonASTSkeletonizer,
    GenericBraceSkeletonizer,
)
from ctxguard.core.context import Message, NormalizedRequest, RequestContext
from ctxguard.storage.db import DatabaseManager
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.core.virtual_tools.executor import VirtualToolExecutor


SAMPLE_PYTHON_CODE = """
class OrderProcessor:
    \"\"\"Service handling order creation, validation, and settlement.\"\"\"

    def __init__(self, db_conn, logger):
        \"\"\"Initialize processor with database connection.\"\"\"
        self.db = db_conn
        self.logger = logger
        self.retry_count = 3
        self.status = "idle"

    def validate_order(self, order_id: str, amount: float) -> bool:
        \"\"\"Validate if order exists and amount is non-negative.\"\"\"
        if not order_id:
            raise ValueError("Order ID cannot be empty")
        if amount <= 0:
            raise ValueError("Order amount must be positive")
        record = self.db.query("SELECT * FROM orders WHERE id = ?", order_id)
        if not record:
            return False
        return True

    async def execute_settlement(self, order_id: str, gateway_url: str) -> dict:
        \"\"\"Execute async settlement with payment gateway.\"\"\"
        self.logger.info(f"Settling order {order_id}")
        payload = {"order_id": order_id, "timestamp": 1234567890}
        async with httpx.AsyncClient() as client:
            resp = await client.post(f"{gateway_url}/settle", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Settlement failed with status {resp.status_code}")
            return resp.json()
""".strip()


SAMPLE_JS_CODE = """
function processPayment(userId, amount) {
    console.log("Processing payment for user:", userId);
    if (amount <= 0) {
        throw new Error("Invalid amount");
    }
    const token = generateToken(userId);
    const result = sendToGateway(token, amount);
    return result;
}
""".strip()


def test_python_ast_skeletonizer_preserves_syntax_and_docstrings():
    skeleton = PythonASTSkeletonizer.skeletonize(
        SAMPLE_PYTHON_CODE,
        short_sha="abc123456789",
        preserve_docstrings=True,
        min_body_lines=4
    )
    assert skeleton is not None
    # Verify that skeletonized code is 100% valid Python syntax
    parsed_tree = ast.parse(skeleton)
    assert parsed_tree is not None

    # Verify docstrings are preserved
    assert 'Service handling order creation' in skeleton
    assert 'Validate if order exists' in skeleton
    assert 'Execute async settlement' in skeleton

    # Verify implementation lines were folded
    assert 'Implementation folded' in skeleton
    assert 'SELECT * FROM orders' not in skeleton
    assert 'async with httpx.AsyncClient()' not in skeleton
    assert len(skeleton) < len(SAMPLE_PYTHON_CODE)


def test_generic_brace_skeletonizer():
    skeleton = GenericBraceSkeletonizer.skeletonize(
        SAMPLE_JS_CODE,
        short_sha="js1234567890",
        min_body_lines=4
    )
    assert skeleton is not None
    assert "function processPayment(userId, amount) {" in skeleton
    assert "Implementation folded" in skeleton
    assert "generateToken(userId)" not in skeleton


def test_ast_compressor_in_markdown_code_block(tmp_path):
    db_file = tmp_path / "test.db"
    db_mgr = DatabaseManager(f"sqlite:///{db_file}")
    fingerprint_repo = FingerprintRepository(db_mgr)

    config = ASTCodeCompressorConfig(enabled=True, min_lines=15)
    compressor = ASTCodeCompressor(config, fingerprint_repo=fingerprint_repo)

    md_content = f"Here is the service code:\n```python\n{SAMPLE_PYTHON_CODE}\n```\nPlease review."
    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[Message(role="user", content=md_content)],
        session_id="test_session_ast"
    )
    context = RequestContext(request=req, original_tokens=500)

    compressor.process(context, req.messages)

    optimized_text = req.messages[0].get_text_content()
    assert "```python" in optimized_text
    assert "...  # [CtxGuard: Implementation folded" in optimized_text
    assert "OrderProcessor" in optimized_text
    assert "ast_code_compressor" in context.applied_compressors

    # Verify original code is retrievable from fingerprint repo
    import re
    match = re.search(r"ctx_expand\('([a-zA-Z0-9_]+)'\)", optimized_text)
    assert match is not None
    ref_id = match.group(1)

    restored = fingerprint_repo.get_content(ref_id)
    assert restored is not None
    assert "SELECT * FROM orders" in restored


def test_ast_compressor_protects_assistant_messages():
    config = ASTCodeCompressorConfig(enabled=True, min_lines=10)
    compressor = ASTCodeCompressor(config)

    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[Message(role="assistant", content=f"```python\n{SAMPLE_PYTHON_CODE}\n```")],
        session_id="test_session_asst"
    )
    context = RequestContext(request=req, original_tokens=500)

    compressor.process(context, req.messages)

    # Assistant message MUST remain completely unmodified
    assert req.messages[0].get_text_content() == f"```python\n{SAMPLE_PYTHON_CODE}\n```"
    assert "ast_code_compressor" not in context.applied_compressors


def test_ast_compressor_expand_via_virtual_tool(tmp_path):
    db_file = tmp_path / "test_expand.db"
    db_mgr = DatabaseManager(f"sqlite:///{db_file}")
    fingerprint_repo = FingerprintRepository(db_mgr)

    config = ASTCodeCompressorConfig(enabled=True, min_lines=15)
    compressor = ASTCodeCompressor(config, fingerprint_repo=fingerprint_repo)

    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[Message(role="user", content=f"```python\n{SAMPLE_PYTHON_CODE}\n```")],
        session_id="session_tool_test"
    )
    context = RequestContext(request=req, original_tokens=500)
    compressor.process(context, req.messages)

    import re
    match = re.search(r"ctx_expand\('([a-zA-Z0-9_]+)'\)", req.messages[0].get_text_content())
    ref_id = match.group(1)

    # Simulate model issuing a tool call to ctx_expand
    tool_req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[
            Message(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "call_expand_999",
                        "type": "function",
                        "function": {
                            "name": "ctx_expand",
                            "arguments": f'{{"ref_id": "{ref_id}"}}'
                        }
                    }
                ]
            )
        ]
    )

    executor = VirtualToolExecutor(fingerprint_repo=fingerprint_repo)
    resp = executor.check_and_execute(tool_req)

    assert resp is not None
    assert resp.prompt_tokens == 0
    assert resp.completion_tokens == 0
    assert "SELECT * FROM orders" in resp.content
