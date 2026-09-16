"""Synthetic benchmark datasets simulating realistic Agent workloads."""

from typing import Any, Dict, List


def get_coding_agent_scenario() -> Dict[str, Any]:
    """Scenario 1: Coding Agent reading files, running builds with ANSI logs, and repeated queries."""
    repeated_code = (
        "// src/auth/jwt.service.ts\n"
        "import { Injectable } from '@nestjs/common';\n"
        "import { JwtService } from '@nestjs/jwt';\n\n"
        "@Injectable()\n"
        "export class AuthService {\n"
        "    constructor(private readonly jwt: JwtService) {}\n"
        "    async validateUser(token: string): Promise<any> {\n"
        "        return this.jwt.verify(token);\n"
        "    }\n"
        "}\n"
    )

    ansi_build_log = (
        "\x1b[34m[INFO]\x1b[0m Starting webpack build...\n"
        "[====>          ] 20% Compiling modules\n"
        "[========>      ] 40% Compiling modules\n"
        "[============>  ] 80% Compiling modules\n"
        "[==============>] 100% Build complete!\n"
        "\x1b[32mSuccess:\x1b[0m Bundle generated in 420ms.\n"
    )

    return {
        "name": "Coding Agent Workflow (Dedup + ANSI + Progress)",
        "messages": [
            {"role": "user", "content": "Please inspect jwt.service.ts"},
            {"role": "tool", "content": repeated_code},
            {"role": "assistant", "content": "I see the JWT service. Let's run the build."},
            {"role": "tool", "content": ansi_build_log},
            {"role": "assistant", "content": "Build succeeded. Let me double check jwt.service.ts."},
            {"role": "tool", "content": repeated_code},  # Duplicate! Should trigger Dedup
        ],
    }


def get_rag_database_scenario() -> Dict[str, Any]:
    """Scenario 2: RAG Database query returning large homogeneous JSON arrays."""
    json_rows = "[\n" + ",\n".join([
        f'  {{"id": {i}, "metric_name": "cpu_utilization_{i}", "node": "worker-{i%4}", "value": {i*1.5:.1f}, "status": "healthy"}}'
        for i in range(1, 20)
    ]) + "\n]"

    return {
        "name": "RAG Database Tool Output (Homogeneous JSON Arrays)",
        "messages": [
            {"role": "user", "content": "Query cluster metrics for nodes"},
            {"role": "tool", "content": json_rows},
        ],
    }


def get_long_document_rag_scenario() -> Dict[str, Any]:
    """Scenario 3: Long document RAG scenario with filler words for semantic pruning."""
    paragraphs = []
    for i in range(15):
        paragraphs.append(
            f"Paragraph {i}: Basically and essentially, the system architecture consists of multiple microservices. "
            f"Furthermore, please note that CRITICAL security credentials must be stored securely. "
            f"Moreover, actually every transaction is verified against distributed consensus protocols. "
            f"Obviously and frankly, performance optimizations should be applied."
        )
    text = "\n\n\n\n\n".join(paragraphs)

    return {
        "name": "Long Document RAG (Whitespace + Semantic Pruner)",
        "messages": [
            {"role": "user", "content": "Summarize the microservice security architecture."},
            {"role": "tool", "content": text},
        ],
    }


def get_first_time_large_code_scenario() -> Dict[str, Any]:
    """Scenario 4: First-time reading of a 150-line Python service with multiple classes and methods."""
    code_lines = [
        "```python",
        "# src/services/order_settlement_engine.py",
        "import asyncio",
        "import logging",
        "from typing import Dict, List, Optional",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "class OrderValidationPipeline:",
        '    """Validates order integrity, user balances, and fraud score checks."""',
        "    def __init__(self, db_client, risk_engine):",
        '        """Initialize validation pipeline with dependencies."""',
        "        self.db = db_client",
        "        self.risk = risk_engine",
        "        self.cache = {}",
        "",
        "    def validate_fraud_risk(self, order_id: str, user_id: str) -> float:",
        '        """Calculate risk score based on transaction velocity and geo-ip."""',
        "        history = self.db.query('SELECT * FROM user_txs WHERE uid = ?', user_id)",
        "        score = 0.0",
        "        for tx in history:",
        "            if tx.get('is_flagged'):",
        "                score += 25.0",
        "            if tx.get('amount') > 5000:",
        "                score += 15.0",
        "        return min(100.0, score)",
        "",
        "    def check_inventory_lock(self, item_ids: List[str]) -> bool:",
        '        """Acquire distributed redis locks on all items."""',
        "        for item_id in item_ids:",
        "            locked = self.db.acquire_lock(f'inv_{item_id}', timeout=10)",
        "            if not locked:",
        "                logger.warning(f'Failed to lock item {item_id}')",
        "                return False",
        "        return True",
        "",
        "class SettlementExecutor:",
        '    """Executes distributed multi-party ledger settlement transactions."""',
        "    def __init__(self, ledger_conn, payment_gw):",
        '        """Initialize settlement executor."""',
        "        self.ledger = ledger_conn",
        "        self.gw = payment_gw",
        "",
        "    async def execute_payout(self, order_id: str, amount_cents: int, dest_account: str) -> Dict[str, Any]:",
        '        """Perform atomic payment gateway transfer with audit trail."""',
        "        logger.info(f'Starting payout of {amount_cents} cents for {order_id}')",
        "        tx_id = self.ledger.create_pending_tx(order_id, amount_cents)",
        "        try:",
        "            res = await self.gw.transfer(dest_account, amount_cents, tx_id)",
        "            self.ledger.mark_committed(tx_id, res['confirmation_code'])",
        "            return {'status': 'success', 'tx_id': tx_id}",
        "        except Exception as e:",
        "            logger.error(f'Payout failed for {order_id}: {e}')",
        "            self.ledger.mark_aborted(tx_id, str(e))",
        "            raise",
        "```"
    ]
    code_text = "\n".join(code_lines)

    return {
        "name": "First-time Code Read (AST Skeletonization)",
        "messages": [
            {"role": "user", "content": "Please inspect order_settlement_engine.py and explain its architecture."},
            {"role": "tool", "content": code_text},
        ]
    }


def get_git_diff_review_scenario() -> Dict[str, Any]:
    """Scenario 5: Git Diff Code Review with extensive unchanged context lines."""
    diff_content = (
        "diff --git a/src/auth/session.py b/src/auth/session.py\n"
        "index 83a1b02..d4e2f91 100644\n"
        "--- a/src/auth/session.py\n"
        "+++ b/src/auth/session.py\n"
        "@@ -1,30 +1,30 @@\n"
        " import os\n"
        " import time\n"
        " import hmac\n"
        " import hashlib\n"
        " import json\n"
        " from typing import Optional, Dict, Any\n"
        " from dataclasses import dataclass\n"
        " \n"
        " @dataclass\n"
        " class SessionToken:\n"
        "     user_id: str\n"
        "     token: str\n"
        "     expires_at: float\n"
        "     created_at: float\n"
        "     is_revoked: bool\n"
        " \n"
        " class SessionManager:\n"
        "     def __init__(self, secret_key: str, ttl_seconds: int = 3600):\n"
        "         self.secret_key = secret_key\n"
        "-        self.ttl = ttl_seconds\n"
        "+        self.ttl = max(60, ttl_seconds)  # Enforce minimum TTL\n"
        "         self._store: Dict[str, SessionToken] = {}\n"
        " \n"
        "     def create_session(self, user_id: str) -> str:\n"
        "         now = time.time()\n"
        "         token = hashlib.sha256(f'{user_id}:{now}'.encode()).hexdigest()\n"
        "         self._store[token] = SessionToken(\n"
        "             user_id=user_id,\n"
        "             token=token,\n"
        "-            expires_at=now + self.ttl,\n"
        "+            expires_at=now + self.ttl + 10,\n"
        "             created_at=now,\n"
        "             is_revoked=False\n"
        "         )\n"
        "         return token\n"
        " \n"
        "     def validate_session(self, token: str) -> Optional[str]:\n"
        "         sess = self._store.get(token)\n"
        "         if not sess or sess.is_revoked:\n"
        "             return None\n"
        "         if time.time() > sess.expires_at:\n"
        "             return None\n"
        "         return sess.user_id\n"
    )

    return {
        "name": "Git Diff Review Scenario (Context Line Folding)",
        "messages": [
            {"role": "user", "content": "Review the latest git diff changes for session TTL."},
            {"role": "tool", "content": diff_content},
        ]
    }
