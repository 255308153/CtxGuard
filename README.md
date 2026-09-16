# 🛡️ CtxGuard

<div align="center">

**Ultra-Lightweight, Transparent Context Optimization & Memory Gateway for LLMs & AI Agents**

*Cut Token Costs by 50%~80% • Preserve Official Prompt Cache • Zero Code Changes • Sub-Millisecond Overhead*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-133%20passed-success.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)

</div>

---

## ⚡ What is CtxGuard?

**CtxGuard** is an ultra-lightweight, zero-config reverse proxy and request-side context governance gateway designed specifically for long-context Coding Agents (Claude Code, Pi Agent, Cursor, VSCode) and LLM applications.

It sits transparently between your Agent harness and LLM providers (Anthropic, OpenAI, DeepSeek), intercepting outbound API calls to compress redundant tool outputs, stabilize Prompt Cache prefixes, manage temporal user memory, and shape model verbosity—**without modifying your code or sacrificing reasoning accuracy**.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer["1. Client Ecosystem (Zero-Code Change)"]
        A1["Cursor / VSCode"] 
        A2["Claude Code"] 
        A3["Pi Agent / Pi-Web"]
        A4["OpenAI / Custom SDK"]
    end

    ClientLayer -->|HTTP POST /v1/chat or /v1/messages| GatewayIngress

    subgraph CtxGuardGateway["2. CtxGuard Context & Security Gateway (Port 8787)"]
        GatewayIngress["Gateway Ingress & Protocol Router"]

        subgraph IngressPipeline["Request Optimization Pipeline"]
            direction TB
            P1["ToolsNormalizer<br/>(Recursive Alphabetical Key Order)"]
            P2["Structural Compressors<br/>(GitDiff / ANSI / Stacktrace / AST)"]
            P3["Fingerprint Pool & LRU<br/>(0-Token ctx_expand Cache)"]
            P4["MemoryGraphEngine<br/>(3-Way Hybrid Retrieval & Tail Inject)"]
            P5["OutputShaper<br/>(Verbosity Steering & Effort Routing)"]
            P6["RawByteOverlayGuard<br/>(Byte-Slice Snapshot & 0-Drift Check)"]
            
            P1 --> P2 --> P3 --> P4 --> P5 --> P6
        end

        GatewayIngress --> IngressPipeline

        subgraph BackgroundEngines["Background Autonomous Engines"]
            B1["LoopDetector & PivotAnalyzer<br/>(Failure-to-Pivot Mining)"]
            B2["RulePruner & AtomicRuleWriter<br/>(Supersede & 10-Item Cap Sync)"]
            B3["SQLite Graph Store & Fingerprints<br/>(Embedded Zero-Maintenance DB)"]
        end

        IngressPipeline -.->|Async Logging & GC| BackgroundEngines
        BackgroundEngines -.->|Sync Rules| C1[".cursorrules / CLAUDE.local.md"]
    end

    subgraph CloudProviders["3. Upstream LLM Providers"]
        L1["Anthropic Claude 3.5 / 3.7"]
        L2["OpenAI GPT-4o / o1 / o3 / GPT-5"]
        L3["DeepSeek V3 / R1"]
    end

    IngressPipeline -->|High-Speed Forwarding (Keep-Alive / HTTP/2)| CloudProviders
    CloudProviders -->|SSE Token Stream| GatewayEgress["SSE Stream Handler & Local Virtual Tool Interceptor"]
    GatewayEgress -->|Streamed Tokens| ClientLayer
```

---

## 🚀 Key Features

### 1. 🔒 Prompt Cache Bit-Exact Stabilization (0-Drift Guarantee)
- **Session Prefix Snapshot Freeze**: Locks System Prompt and historical tool schemas byte-for-byte across session turns.
- **Recursive Schema Normalizer (`ToolsNormalizer`)**: Alphabetically sorts `tools[]` definitions and deep JSON Schema properties to stop random client dict disorder from evicting KV Cache.
- **Physical Byte Slices (`RawByteOverlayGuard`)**: Streams raw HTTP byte slices for frozen prefixes, guaranteeing 100% bit-exact SHA-256 matches and securing 50%~90% cloud cache discounts.

### 2. 🗜️ 10-Tier Structural Content Compressors
- **Git Diff Context Folding (`GitDiffCompressor`)**: Folds redundant context lines while strictly preserving hunk headers and `+`/`-` modifications (**saves ~48.6% tokens at 0.15ms latency**).
- **ANSI & Progress Stream Cleaner**: Strips terminal escape codes and squashes repetitive package manager progress bars into single 100% completion frames.
- **Stacktrace Folders**: Collapses repetitive exception loops into first-frame summaries.
- **AST Skeleton Pruner**: Extracts compact signatures and interface stubs from large source files.

### 3. 🔄 Reversible Dedup with 0-Token Local Expansion
- **Content Fingerprint Pool (`FingerprintRepository`)**: Hashes large chunks into local SQLite storage with access-frequency and timestamp-weighted **LRU capacity eviction**.
- **Virtual Tool `ctx_expand`**: Replaces repeated files with lightweight references. When the LLM needs original details, the gateway intercepts `ctx_expand` locally and restores text with **0 upstream tokens and 0 latency**.
### 4. 🧠 Temporal Knowledge Graph Memory
- **3-Way Hybrid Retrieval**: Combines BM25 keywords, vector semantic similarity, and knowledge graph relational reasoning with Chinese bigram tokenization support.
- **Cache-Safe Tail Injection**: Injects retrieved user preferences (`[Relevant User Context]`) strictly as a dynamic suffix to the latest user message, ensuring historical KV Cache prefixes remain intact.
- **Virtual Tools `memory_save` & `memory_search`**: Enables proactive LLM memory management with local gateway interception.

### 5. 🛠️ Autonomous Self-Evolution & Rule Pruning
- **Failure-to-Pivot Analysis (`PivotAnalyzer`)**: Discovers turning points where failures led to successful actions.
- **Rule Budget Cap (`RulePruner`)**: Synthesizes actionable rules, supersedes conflicting directives, and caps active rules at 10 items to prevent bloat.
- **Atomic Marker-Based Sync**: Updates `.cursorrules` and `CLAUDE.local.md` idempotently without overwriting manual developer guidelines.

### 6. ✂️ Output Token Shaping
- **Verbosity Steering**: Strips conversational filler and redundant file echo via byte-stable sentinels.
- **Effort Routing**: Dynamically downgrades thinking effort on mechanical turns (e.g. file reads), delivering a **30.7% net reduction in output token generation**.
## 📦 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/255308153/CtxGuard.git
cd CtxGuard

# Install in editable mode
pip install -e .
```

### 1. Launch Gateway Server

```bash
# Start CtxGuard gateway on default port 8787
ctxguard start --port 8787
```

- **Interactive Dashboard**: `http://127.0.0.1:8787/dashboard`

---

### 2. Connect Your Agent Ecosystem

#### Option A: One-Click Environment Injection (CLI Agents)
```bash
# Export proxy endpoints to current shell session
eval $(ctxguard env --eval)

# Launch your favorite agents seamlessly:
claude          # Claude Code
pi              # Pi Agent
```

#### Option B: Automatic Config Patching (Cursor & VSCode)
```bash
# Automatically detects and patches local config files while remembering original upstreams
ctxguard env --patch
```

#### Option C: Manual Client Base URL Configuration
Point your client's Base URL to CtxGuard:
- **OpenAI Compatible (GPT / DeepSeek)**: `http://127.0.0.1:8787/v1`
- **Anthropic Compatible (Claude Code)**: `http://127.0.0.1:8787`

---

## 📊 Performance & Token Savings Scoreboard

| Benchmark Scenario | Raw Tokens | Optimized Tokens | Token Reduction | Compression Latency (p50) |
| :--- | :--- | :--- | :--- | :--- |
| **Git Diff Review** | 383 | 197 | **48.56%** | `0.15 ms` |
| **Repeated File Read (Dedup)** | 4,200 | 45 | **98.92%** | `0.08 ms` |
| **Terminal Build Logs** | 1,850 | 320 | **82.70%** | `0.12 ms` |
| **Multi-Turn Agent Trajectory** | 6,735 | 5,584 | **17.09%** | `0.21 ms` |
| **Output Token Shaping** | 1,240 (out) | 860 (out) | **30.70%** | `0.00 ms` |

---

## 💻 CLI Commands

```bash
ctxguard stats            # Real-time token optimization and cost dashboard
ctxguard savings          # Multi-day durable financial savings ledger
ctxguard learn --apply    # Mine failure trajectories and update project rules
ctxguard env              # View agent connection presets and shell exports
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
