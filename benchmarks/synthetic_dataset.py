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
