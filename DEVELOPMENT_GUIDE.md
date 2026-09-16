# CtxGuard 核心开发与架构扩展手册 (Developer Guide)

> 本文档面向 CtxGuard 的核心开发者、二次开发人员及架构师，详细阐述系统的代码实现全貌、内部调用链路、算子扩展标准、AST 代码骨架化演进方案与本地调试指南。

---

## 目录
1. [项目全景架构与调用生命周期](#一-项目全景架构与调用生命周期)
2. [核心子系统与源码深入剖析](#二-核心子系统与源码深入剖析)
3. [如何开发并注册一个新的压缩算子（实战教学）](#三-如何开发并注册一个新的压缩算子实战教学)
4. [进阶演进：如何接入 Tree-sitter AST 代码符号骨架化](#四-进阶演进如何接入-tree-sitter-ast-代码符号骨架化)
5. [Prompt Cache 守护安全与测试验证规范](#五-prompt-cache-守护安全与测试验证规范)
6. [单文件存储与时序图谱二次开发](#六-单文件存储与时序图谱二次开发)
7. [离线自进化规则挖掘引擎扩展](#七-离线自进化规则挖掘引擎扩展)
8. [本地开发、测试与基准评测运行规范](#八-本地开发测试与基准评测运行规范)

---

## 一、 项目全景架构与调用生命周期

### 1. 核心端到端数据流向图

```text
客户端 (Cursor / Claude Code / Agent SDK)
       │ HTTP POST (OpenAI / Anthropic 格式)
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. Proxy Ingress (ctxguard/proxy/server.py & router.py)         │
│    └─ 协议归一化：转换为标准统一的 NormalizedRequest               │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Virtual Tool Short-Circuit (ctxguard/core/virtual_tools/)     │
│    └─ 检测最新消息是否为 ctx_expand 调用                           │
│       ├─ 是 ──► 从 SQLite 直读原文 0 Token 返回 (Short-Circuit)  │
│       └─ 否 ──► 继续向下流转                                     │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Compression Pipeline (ctxguard/core/pipeline.py)             │
│    ├─ ① Token 计数与自适应档位评估 (AdaptiveScheduler: L0~L3)   │
│    ├─ ② 前缀缓存动态切分 (CacheGuard.partition_messages)          │
│    │    ├─ [Frozen Prefix] ──► 严格冻结，建立去重指纹，禁止改动   │
│    │    └─ [Compressible Suffix] ──► 活区算子串行清洗           │
│    ├─ ③ 算子流水线清洗：                                         │
│    │    Dedup -> ANSI -> Progress -> Stacktrace -> JSON -> Prune│
│    ├─ ④ 经济套利仲裁 (Economic Arbitrator)                      │
│    │    └─ 检查压缩节省是否击败云端 Prompt Cache 读取折扣        │
│    └─ ⑤ 注入 ctx_expand 虚拟工具 (Sticky-On) 与 Anthropic 缓存点│
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Upstream Forwarding (ctxguard/proxy/upstream.py)             │
│    └─ orjson SIMD 快速序列化，httpx 异步连接池转发至云端 API     │
└─────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. SSE Streaming & Telemetry (ctxguard/proxy/sse.py & ledger.py)│
│    ├─ 零缓冲实时 yield 字节流给客户端                             │
│    └─ 流结束时提取 usage，异步将节省明细落入 .ctxguard.db        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 二、 核心子系统与源码深入剖析

### 1. 配置子系统 (`ctxguard/config/`)
- `schema.py`：基于 Pydantic v2 构建的强类型配置对象（`AppConfig`、`CacheGuardConfig`、`DedupConfig` 等）；
- `loader.py`：负责按以下优先级执行多源配置的级联覆盖合并：
  $$\text{CLI 参数} > \text{环境变量 (CTXGUARD\_*)} > \text{工作区 ./ctxguard.yaml} > \text{全局 ~/.ctxguard/ctxguard.yaml} > \text{Default}$$

### 2. 协议双向适配器 (`ctxguard/proxy/adapters/`)
- `base.py`：定义 `BaseAdapter` 抽象基类，规范 `normalize_request()` 与 `format_response()`；
- `openai.py`：适配 `/v1/chat/completions`，负责 `function_call`、`tool_calls` 与标准消息流的双向转换；
- `anthropic.py`：适配 `/v1/messages`，负责提取顶层 `system` 参数、处理 `tool_use` / `tool_result` 内容块，以及注入 `cache_control: {"type": "ephemeral"}`。

### 3. 上下文核心流水线 (`ctxguard/core/pipeline.py`)
- `process(request: NormalizedRequest) -> RequestContext` 是系统的核心逻辑调度枢纽。
- 关键状态对象 `RequestContext`：
  ```python
  class RequestContext:
      request: NormalizedRequest
      original_tokens: int
      optimized_tokens: int
      active_level: int              # 自适应档位 0, 1, 2, 3
      applied_compressors: List[str] # 本轮命中的算子清单
      metadata: Dict[str, Any]
  ```

---

## 三、 如何开发并注册一个新的压缩算子（实战教学）

以开发一个 **“Markdown 冗余注释与空白行清洗算子 (MarkdownDocCleaner)”** 为例：

### 第一步：继承 `BaseCompressor` 抽象基类

在 `ctxguard/core/compressors/` 目录下新建 `md_cleaner.py`：

```python
# ctxguard/core/compressors/md_cleaner.py
import re
from ctxguard.core.compressors.base import BaseCompressor
from ctxguard.core.context import RequestContext

class MarkdownDocCleaner(BaseCompressor):
    """清理 Markdown 中被注释掉的 HTML 注释与多余的表格分割线"""
    
    HTML_COMMENT_REGEX = re.compile(r"<!--[\s\S]*?-->")

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    @property
    def name(self) -> str:
        return "md_doc_cleaner"

    def is_applicable(self, context: RequestContext) -> bool:
        # 仅在自适应级别 >= 1 且未被全局禁用时激活
        return self.enabled and context.active_level >= 1

    def compress_text(self, text: str) -> str:
        if not text or "<!--" not in text:
            return text
        # 剥离无意义的 HTML 注释
        return self.HTML_COMMENT_REGEX.sub("", text)
```

### 第二步：在 `CompressionPipeline` 中装配算子

修改 `ctxguard/core/pipeline.py`：

```python
from ctxguard.core.compressors.md_cleaner import MarkdownDocCleaner

class CompressionPipeline:
    def __init__(self, config: AppConfig, ...):
        # ...
        self.compressors: List[BaseCompressor] = [
            self.dedup_compressor,
            ANSICleaner(config.structural_compression.log_cleaner),
            ProgressMerger(config.structural_compression.log_cleaner),
            StacktraceFolder(config.structural_compression.log_cleaner),
            JSONStructCompressor(config.structural_compression.json_compressor),
            MarkdownDocCleaner(enabled=True), # 注册新算子
            WhitespaceCleaner(),
            self.semantic_pruner,
        ]
```

### 第三步：编写单元测试验证安全底线

在 `tests/unit/test_md_cleaner.py` 中编写断言：
- 确保 Assistant 角色的消息绝对不被修改；
- 确保包含 HTML 注释的工具输出能够精准剥离且不破坏有效 Markdown 排版。

---

## 四、 进阶演进：如何接入 Tree-sitter AST 代码符号骨架化

根据 `references/aider/aider/repomap.py` 的优秀实践，我们可以在 CtxGuard 中引入 **AST 符号级代码骨架化折叠**。

### 1. 架构目标
对于**首次出现且超过 300 行的代码文件**：
- 提取 `class` 与 `def` 函数签名及 Docstring；
- 将具体实现折叠为 `...  # [CtxGuard: Implementation folded, 60 lines]`；
- 原始全文存入 `FingerprintRepository`；
- 模型若需要修改函数体，自动调起 `ctx_expand` 还原。

### 2. 核心代码骨架实现 (`ASTCodeCompressor`)

```python
# ctxguard/core/compressors/ast_code.py
from tree_sitter import Language, Parser
from ctxguard.core.compressors.base import BaseCompressor

class ASTCodeCompressor(BaseCompressor):
    def __init__(self, min_lines: int = 100):
        self.min_lines = min_lines

    def compress_python_ast(self, code_str: str) -> str:
        # 1. 使用 tree_sitter 解析语法树
        # 2. 遍历 AST 节点，定位 FunctionDefinition 的 block
        # 3. 提取签名与 Docstring，替换 block 为 `...`
        # 4. 返回骨架化代码
        pass
```

---

## 五、 Prompt Cache 守护安全与测试验证规范

### 1. 缓存安全三大铁律（必须在代码审查中遵守）
1. **冻结前缀不可变**：`request.messages[:frozen_message_count]` 内的所有对象严禁修改、增删或重新排版；
2. **工具列表不可抖动 (Sticky-On)**：`ctx_expand` 工具一旦在会话中注入，必须在整个 Session 的后续所有请求中始终注入，严禁条件性增删；
3. **经济套利底线**：算子压缩后的总收益若不满足 $\frac{\text{raw} - \text{compressed}}{\text{raw}} > \text{read\_discount}$，必须触发原子回滚（`compressible_suffix = orig_suffix_copies`）。

### 2. 单元测试门禁
运行 `pytest tests/ -v` 验证以下核心断言：
- `test_cache_guard.py`：验证前缀边界反向累加算法与经济套利公式；
- `test_dedup.py`：验证 Assistant 消息不被篡改、去重标记准确性；
- `test_json_struct.py`：验证同构/非同构 JSON 数组的健壮性。

---

## 六、 单文件存储与时序图谱二次开发

### 1. 数据库模型 (`ctxguard/storage/`)
系统采用单文件嵌入式 `sqlite3`（工作区目录下的 `.ctxguard.db`），已开启 **WAL 并发模式**。

核心表结构：
1. `fingerprints`：存储内容 SHA-256 与原始全文；
2. `savings_ledger`：记录每轮会话的 Prompt 优化前/后 Token、缓存命中 Token 与净省资金；
3. `kg_entities` 与 `kg_relationships`：时序知识图谱实体与关联表；
4. `kg_entities_fts`：FTS5 全文索引虚拟表，支持高效 BM25 检索。

### 2. 事实版本演化（Supersession Chain）开发规范
向知识图谱写入新事实时：
- **严禁执行 `DELETE FROM kg_entities`**；
- 必须通过 `update_entity_validity(entity_id, valid_until=now)` 标记过期，并由新实体记录 `supersedes = old_id`。

---

## 七、 离线自进化规则挖掘引擎扩展

### 1. 规则提取状态机 (`ctxguard/learn/`)
- `loop_detector.py`：基于滑动窗口扫描会话历史中**相同命令连续报错 $\ge 3$ 次**的事件序列；
- `causality_extractor.py`：定位引发由“报错状态”跳变至“执行成功状态”的关键转折操作（Pivot Action）；
- `rule_renderer.py`：使用标准 Markdown 模板渲染成工程规则；
- `atomic_writer.py`：利用 `<!-- START_CTXGUARD_LEARNED_RULES -->` 标记块隔离技术，将规则幂等合并写入工作区的 `CLAUDE.local.md` 与 `.cursorrules`。

---

## 八、 本地开发、测试与基准评测运行规范

### 1. 环境准备与开发模式安装
```bash
# 进入工作区
cd /Users/lqc/Downloads/CtxGuard

# 安装开发依赖 (以 editable 模式安装)
pip install -e .
```

### 2. 运行单元测试套件
```bash
pytest tests/ -v --tb=short
```

### 3. 运行端到端压缩与延迟基准评测
```bash
python benchmarks/run_benchmark.py
```

### 4. 本地启动网关并验证
```bash
# 启动本地代理
ctxguard start --port 8787 --log-level debug

# 在新终端检查状态看板
ctxguard stats
ctxguard savings
```

---
*版本：v1.0 (2026-09) · 维护团队：CtxGuard Core Team*
