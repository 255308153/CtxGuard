# CtxGuard 核心开发与架构扩展手册 (Developer Guide)

> 本文档面向 CtxGuard 的核心开发者、二次开发人员及架构师，详细阐述系统的代码实现全貌、内部调用链路、算子扩展标准、AST 代码骨架化演进方案与本地调试指南。

---

## 目录
1. [项目全景架构与调用生命周期](#一-项目全景架构与调用生命周期)
2. [核心子系统与源码深入剖析](#二-核心子系统与源码深入剖析)
3. [如何开发并注册一个新的压缩算子（实战教学）](#三-如何开发并注册一个新的压缩算子实战教学)
4. [工业级 Tree-sitter AST 多语言代码骨架化 (TreeSitterSkeletonizer)](#四-工业级-tree-sitter-ast-多语言代码骨架化-treesitterskeletonizer)
5. [Tool 影子状态机与增量差分 (ToolDeltaCompressor)](#五-tool-影子状态机与增量差分-tooldeltacompressor)
6. [终端超长日志智能截断 (LogTruncator)](#六-终端超长日志智能截断-logtruncator)
7. [敏感信息与凭证脱敏 (SecretRedactor)](#七-敏感信息与凭证脱敏-secretredactor)
8. [思考链生命周期治理 (ThinkingManager)](#八-思考链生命周期治理-thinkingmanager)
9. [Prompt Cache 守护安全与测试验证规范](#九-prompt-cache-守护安全与测试验证规范)
10. [单文件存储与时序图谱二次开发](#十-单文件存储与时序图谱二次开发)
11. [离线自进化规则挖掘引擎扩展](#十一-离线自进化规则挖掘引擎扩展)
12. [本地开发、测试与基准评测运行规范](#十二-本地开发测试与基准评测运行规范)

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
│    ├─ ② 思考链管理 (ThinkingManager: DeepSeek / Gemini / Claude)│
│    ├─ ③ 前缀缓存动态切分 (CacheGuard.partition_messages)          │
│    │    ├─ [Frozen Prefix] ──► 严格冻结，建立去重指纹，禁止改动   │
│    │    └─ [Compressible Suffix] ──► 活区算子串行清洗           │
│    ├─ ④ 算子流水线深度优化：                                     │
│    │    Dedup -> ToolDelta (Shadow State) -> SecretRedactor     │
│    │    -> ANSI -> Progress -> Stacktrace -> LogTruncator       │
│    │    -> JSONStruct -> TreeSitter AST -> SemanticPruner       │
│    ├─ ⑤ 经济套利仲裁 (Economic Arbitrator)                      │
│    │    └─ 检查压缩节省是否击败云端 Prompt Cache 读取折扣        │
│    └─ ⑥ 注入 ctx_expand 虚拟工具 (Sticky-On) 与 Anthropic 缓存点│
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
- `schema.py`：基于 Pydantic v2 构建的强类型配置对象（`AppConfig`、`CacheGuardConfig`、`DedupConfig`、`ToolDeltaConfig`、`TreeSitterConfig`、`LogTruncatorConfig`、`ThinkingConfig`、`SecretRedactorConfig` 等）；
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
            ToolDeltaCompressor(config.tool_delta, fingerprint_repo=self.fingerprint_repo),
            SecretRedactor(config.secret_redactor),
            ANSICleaner(config.structural_compression.log_cleaner),
            ProgressMerger(config.structural_compression.log_cleaner),
            StacktraceFolder(config.structural_compression.log_cleaner),
            LogTruncator(config.log_truncator, fingerprint_repo=self.fingerprint_repo),
            JSONStructCompressor(config.structural_compression.json_compressor),
            MarkdownDocCleaner(enabled=True), # 注册新算子
            TreeSitterSkeletonizer(config.tree_sitter, fingerprint_repo=self.fingerprint_repo),
            WhitespaceCleaner(),
            self.semantic_pruner,
        ]
```

### 第三步：编写单元测试验证安全底线

在 `tests/unit/test_md_cleaner.py` 中编写断言：
- 确保 Assistant 角色的消息绝对不被修改；
- 确保包含 HTML 注释的工具输出能够精准剥离且不破坏有效 Markdown 排版。

---

## 四、 工业级 Tree-sitter AST 多语言代码骨架化 (`TreeSitterSkeletonizer`)

### 1. 架构目标与优势
CtxGuard 在 `ctxguard/core/compressors/ast_code.py` 中完整实现了**基于 Tree-sitter 纯 C 绑定的多语言代码骨架化引擎**：
- **多语言原生支持**：开箱即用支持 Python, JavaScript, TypeScript, TSX, Go, Rust, Java, C, C++ 9+ 门主流语言；
- **微秒级性能**：单文件解析耗时 `< 1ms`，比纯 Python AST 解析器快 5~10 倍；
- **语法鲁棒性**：完美免疫注释括号、模板字符串及 JSX 嵌套，绝不破坏语法结构；
- **100% 可逆**：折叠的函数体存入 SQLite `FingerprintRepository`，附带 `ctx_expand(short_sha)` 恢复标记。

### 2. 核心架构实现与解析原理
```python
# ctxguard/core/compressors/ast_code.py 关键片段
class TreeSitterSkeletonizer(BaseCompressor):
    SUPPORTED_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".mjs": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".h": "c",
        ".cpp": "cpp",
        ".hpp": "cpp",
        ".cc": "cpp",
    }
```

---

## 五、 Tool 影子状态机与增量差分 (`ToolDeltaCompressor`)

针对 Agent 频繁调用 `list_dir`、`find_by_name`、`git status`、`ls` 等状态探针指令，CtxGuard 提供了内存影子状态机与增量差分引擎：
1. **会话级影子快照**：维护每个 Session 的最近一次工具状态集合；
2. **Jaccard 相似度探测**：计算与前次快照的相似度（默认阈值 $\ge 0.5$ 判定同源指令）；
3. **集合增量差分 (Set Diff)**：
   - 精确计算 `+ Added` 与 `- Removed` 项；
   - 将上百行未变化的文件列表紧凑折叠为 `... (K items unchanged)`；
   - 原始输出入库，支持 `ctx_expand` 零损调阅。

---

## 六、 终端超长日志智能截断 (`LogTruncator`)

针对测试和编译产生的海量长日志：
- **头部 (Head 25 行)**：保留启动命令、环境参数、构建版本；
- **尾部 (Tail 75 行)**：保留核心报错信息、Traceback 堆栈与退出代码；
- **中间折叠**：替换为 `[... Truncated N lines ... | Full output cached: sha256_xxx | use ctx_expand to restore]`。

---

## 七、 敏感信息与凭证脱敏 (`SecretRedactor`)

自动在代理网关层过滤并脱敏 API 凭证：
- OpenAI / Anthropic / GitHub / AWS / JWT 密钥及 Bearer Tokens；
- PEM 格式私钥证书 (`-----BEGIN PRIVATE KEY-----`)；
- 包含明文密码的数据库连接字符串 (`postgres://user:password@host:5432/db`)。

---

## 八、 思考链生命周期治理 (`ThinkingManager`)

针对各类推理大模型的 CoT 规范进行专用治理：
- **DeepSeek-R1**：剥离历史 Assistant 消息中的 `reasoning_content` 与 `<think>` 标签，杜绝二次计费；
- **Google Gemini**：剥离 `<thought>` 块；
- **Anthropic Claude 3.7**：在前置窗口内保留思考签名享受 Prompt Cache，并在窗口超限或冷重整时安全修剪。

---

## 九、 Prompt Cache 守护安全与测试验证规范

### 1. 缓存安全三大铁律（必须在代码审查中遵守）
1. **冻结前缀不可变**：`request.messages[:frozen_message_count]` 内的所有对象严禁修改、增删或重新排版；
2. **工具列表不可抖动 (Sticky-On)**：`ctx_expand` 工具一旦在会话中注入，必须在整个 Session 的后续所有请求中始终注入，严禁条件性增删；
3. **经济套利底线**：算子压缩后的总收益若不满足 $\frac{\text{raw} - \text{compressed}}{\text{raw}} > \text{read\_discount}$，必须触发原子回滚（`compressible_suffix = orig_suffix_copies`）。

### 2. 单元测试门禁
运行 `pytest tests/ -v` 验证以下核心断言：
- `test_cache_guard.py`：验证前缀边界反向累加算法与经济套利公式；
- `test_dedup.py`：验证 Assistant 消息不被篡改、去重标记准确性；
- `test_json_struct.py`：验证同构/非同构 JSON 数组的健壮性；
- `test_tool_delta.py`：验证会话级影子状态增量差分与 Jaccard 相似度；
- `test_tree_sitter_skeletonizer.py`：验证多语言 AST 纯 C 解析与 Docstring 完整保留；
- `test_log_truncator.py`：验证 Head 25 / Tail 75 日志智能截断；
- `test_thinking_manager.py`：验证 DeepSeek / Gemini / Claude 思考治理；
- `test_secret_redactor.py`：验证 API 密钥与敏感凭证脱敏。

---

## 十、 单文件存储与时序图谱二次开发

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

## 十一、 离线自进化规则挖掘引擎扩展

### 1. 规则提取状态机 (`ctxguard/learn/`)
- `loop_detector.py`：基于滑动窗口扫描会话历史中**相同命令连续报错 $\ge 3$ 次**的事件序列；
- `causality_extractor.py`：定位引发由“报错状态”跳变至“执行成功状态”的关键转折操作（Pivot Action）；
- `rule_renderer.py`：使用标准 Markdown 模板渲染成工程规则；
- `atomic_writer.py`：利用 `<!-- START_CTXGUARD_LEARNED_RULES -->` 标记块隔离技术，将规则幂等合并写入工作区的 `CLAUDE.local.md` 与 `.cursorrules`。

---

## 十二、 本地开发、测试与基准评测运行规范

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
