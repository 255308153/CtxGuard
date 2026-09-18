# CtxGuard

<div align="center">

**高并发、低延迟的 AI Agent 上下文治理与智能缓存加速网关**

*毫秒级算子流水线 • 保证云端 KV Cache 稳定命中 • 长效时序记忆 • 零业务侵入*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-205%20passed-success.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)

</div>

---

## 项目简介

在现代 AI Agent（如 Claude Code、Cursor、Pi Agent、Codex）的复杂编码与长链路自动化任务中，随着工具调用的频繁执行，请求上下文呈指数级膨胀：大段未修改的代码差异、冗长的构建日志、重复的状态探测输出以及历史思考链迅速消耗宝贵的上下文窗口，产生高昂的 Token 费用；与此同时，客户端工具定义的无序序列化与动态提示词拼接极易引发服务商前缀缓存（Prompt Cache）频繁失效。

**CtxGuard** 是一套部署在客户端与大模型服务商（OpenAI、Anthropic、DeepSeek 等）之间的透明反向代理网关。它在协议中转层对出向请求实施轻量级结构化优化、语法树骨架提取与字节级防抖，在完全不损耗模型推理能力与代码逻辑的前提下，显著降低通信负载与计算开销，并为多轮会话提供自动进化的项目级经验沉淀与知识图谱记忆能力。

---

## 控制面板预览 (Web Dashboard)

CtxGuard 提供了现代化的一体化监控控制台（默认访问 `http://127.0.0.1:8787/dashboard`），用于直观监控全局 Token 流向、会话压缩曲线、知识图谱与自动演进的规则库：

| 实时 Token 流量趋势与多轮压缩监控 | 跨 Agent 时序知识图谱拓扑 |
| :---: | :---: |
| ![Token 流量趋势图](assets/screenshots/02-traffic-chart.png) | ![知识图谱拓扑](assets/screenshots/03-knowledge-graph.png) |

| 控制面板全局数据大盘概览 | 自进化避坑经验规则库 |
| :---: | :---: |
| ![全局概览看板](assets/screenshots/01-dashboard-overview.png) | ![自进化经验规则库](assets/screenshots/04-learned-rules.png) |

---

## 系统架构 (System Architecture)

<div align="center">

![CtxGuard System Architecture](assets/architecture_diagram.png)

</div>

---

## 核心设计与技术实现

### 1. 物理级前缀防抖与 Prompt Cache 保活
- **二进制切片透传**：对多轮对话中未发生变更的历史消息，跳过 Python 运行时的反序列化与字典重构，直接提取并转发原始 HTTP 请求的底层二进制切片，从根本上杜绝空格、换行符及浮点格式漂移。
- **Schema 确定性重构**：在网关层递归遍历 `tools` 列表及内部 JSON Schema 定义，统一按字母序进行确定性重排序，彻底解决各类客户端实现中字典无序导致的前缀缓存击穿。
- **生命周期冷热隔离与确定性执行**：将上下文划分为静态系统区与动态交互区。会话建立后自动锁定头部提示词快照，动态注入项仅追加于末尾活跃窗口；采用纯粹确定性单向压缩，彻底消除运行时回滚抖动。

### 2. 工业级 Tree-sitter 多语言语法树引擎 (TreeSitterSkeletonizer)
- **9+ 门主流语言原生支持**：采用官方预编译纯 C 语言 Tree-sitter 绑定（支持 Python, JavaScript, TypeScript, TSX, Go, Rust, Java, C, C++ 等语言），逐字节精确提取函数/类签名与 Docstring。
- **微秒级解析**：单文件解析耗时 `< 1ms`，比纯 Python AST 快 5~10 倍；完美免疫注释括号、模板字符串及 JSX/TSX 嵌套，绝不破坏代码语法。
- **可逆代码折叠**：函数体折叠后存入本地 SQLite 指纹池，附带 `ctx_expand(short_sha)` 标记，支持模型按需随时索要完整实现。

### 3. Tool 影子状态机与增量差分器 (ToolDeltaCompressor)
- **会话级影子快照**：针对 `list_dir`、`find_by_name`、`git status`、`ls` 等探针指令，在内存中维护会话维度的文件与目录快照影子状态机。
- **Jaccard 集合相似度探测**：自动计算当前输出与前次快照的重合度（Jaccard $\ge 0.5$ 判定为同源状态更新）。
- **增量集合差分**：精确计算 `+ Added`（新增项）与 `- Removed`（删除项），将海量未变更条目折叠为 `... (K items unchanged)`，将 2500+ Tokens 的状态刷新压缩至 30 Tokens（Token 消耗削减 90%+ 并 100% 可逆）。

### 4. 终端超长日志全局 Head-Tail 智能截断 (LogTruncator)
- **针对超长构建与测试日志**：自动识别 `npm test`、`cargo build`、`pip install` 产生的数千行编译或测试长日志。
- **智能滑动窗口**：保留**头部 25 行**（环境参数、版本信息、启动配置）与**尾部 75 行**（核心报错堆栈、Assertion 失败与退出代码），中间部分折叠存入指纹池（Token 消耗降低 80%+）。
- **ANSI 控制码清洗与进度条合并**：正则消除 ANSI 颜色代码；对包管理工具连续打印的百分比进度条进行帧合并，仅保留最终完成状态。

### 5. 跨轮次思考链神圣透传架构 (ThinkingManager)
- **思考块神圣透传（Passthrough-only）**：对 Assistant 思考链（Claude `thinking` + `signature`、Gemini `<thought>`、DeepSeek `<think>`）默认实施 100% 绝对透传保真。
- **0 签名报错与 100% 缓存对齐**：彻底杜绝修改思考内容引发的 Anthropic 400 签名崩溃，确保 Google Gemini / DeepSeek 的 KV-Cache 字节级无缝对齐，保障 Agent 长期推演认知连贯性。
- **冷热双态生命周期**：在热会话期间锁定已缓存前缀；仅在闲置超时（`was_cold=True`）且显式配置时才执行全量基线重塑。

### 6. 敏感数据与 API 凭证安全脱敏 (SecretRedactor)
- **多凭证类型识别**：自动拦截并脱敏 OpenAI / Anthropic / GitHub / AWS / JWT 密钥及 Bearer Tokens。
- **私钥与证书保护**：PEM 私钥证书（`-----BEGIN PRIVATE KEY-----`）与包含密码的数据库连接字符串（`postgres://user:password@host:5432/db`）自动打码，杜绝凭据外泄风险。

### 7. 可逆内容指纹池与自闭环响应拦截 (Dedup, LRU & CCR Loop)
- **网关层自闭环响应拦截 (CCR Loop)**：在网关层截断拦截云端大模型发出的 `tool_calls: ctx_expand`。网关本地 0.1ms 提取原文并自动在后台发起第 2 轮续写（Continuation Request），向下游客户端（Cline, RooCode, Claude Code, Cursor）彻底屏蔽虚拟工具调用过程，100% 杜绝 `Tool not found` 崩溃，真正实现无感可逆。
- **单会话去重铁律与零跨会话致盲**：内容去重严格锁定在单会话内（`Storage Invariant 2`），新会话首读文件 100% 全量放行，彻底消除新会话“两眼一抹黑”的致盲隐患；SQLite 全局指纹库专注扮演 CAS（内容寻址存储）永久还原底座。
- **纯净占位符清洗 (No-Deception Placeholder)**：禁用工具注入时，全面清洗所有压缩模块的折叠占位符，严禁输出任何 `Use ctx_expand` 诱导信息，杜绝欺骗大模型。
- **纯内存热 LRU 纳秒级检索**：基于 10,000 容量的内存 `OrderedDict` 维护热点指纹索引，读路径 100% 内存 O(1) 命中，杜绝频繁磁盘 I/O 与 SSD 写入磨损；结合批量惰性持久化削减 99% 以上磁盘事务提交。
- **CPU 密集流水线多线程异步卸载**：通过 `asyncio.to_thread` 将 AST 解析与正则分词卸载至工作线程池，主事件循环零阻塞，多 Agent 并发无排队延迟。
- **主动感知回填 (Proactive Context Expansion)**：结合 `ContextTracker` 7 重防御体系，在用户提问前置自适应识别并回填关键上下文，防范 Prompt 膨胀；严格限制仅在活区（Live Zone）末尾追加，绝不篡改历史前缀，完美守护云端 KV Cache 90%+ 稳定命中率。

### 8. 时序知识图谱与多 Agent 插件化自进化学习引擎 (Memory & Learn)
- **跨 Agent 生态插件化扫描体系**：全面解耦为插件体系（`ClaudePlugin`、`CtxGuardGatewayPlugin`、`GeminiPlugin`、`CodexPlugin`）。不仅能离线扫描 Claude Code、Gemini CLI、Codex 等外部工具轨迹，更能将 CtxGuard 自身网关实时中转的多 Agent 请求直接接入分析。
- **三级自适应推理分析器 (3-Tier Analyzer)**：
  - **Tier 1 (LLM 语义分析)**：通过 LiteLLM / 目标大模型执行因果归因与规则精准提炼；
  - **Tier 2 (本地 CLI 免 Key 模式)**：自动检测并调用宿主机已安装的 `claude -p` / `gemini -p` / `codex exec` 命令行，直接复用终端现有订阅权限，无需额外配置昂贵 API Key；
  - **Tier 3 (离线启发式兜底)**：在断网或无模型环境下，自动降级为本地无损规则提取器，保证任何环境下永不崩溃。
- **Round-Trip 往返解析与经验规则结转 (Carried Forward)**：执行学习前自动反向解析项目现有规则文件（`AGENTS.md`、`.cursorrules` 等）；新提炼规则增量更新，历史学到但本轮未触发的冷门规则**自动结转保留**，彻底杜绝“重新学习冲掉历史宝贵经验”的问题。
- **Token 浪费物理计量与加权排序**：精准识别 Agent 死循环调用的分页参数与重复指令，量化计算循环浪费的 Token 体积，高价值避坑规则自动置顶排布。
- **多模态语义检索与图谱记忆**：结合 BM25 词频统计、稠密向量嵌入以及图谱实体关联进行三路加权打分，精准召回环境事实及开发偏好。

---

## 快速上手

### 环境准备与安装

```bash
# 克隆工程
git clone https://github.com/255308153/CtxGuard.git
cd CtxGuard

# 本地安装
pip install -e .
```

### 1. 启动本地网关

```bash
# 标准启动（默认监听 127.0.0.1:8787）
ctxguard start --port 8787

# 多核并发推荐（突破 GIL，启动 4 个 Worker 进程并行处理高并发 Agent 请求）
ctxguard start --port 8787 -w 4
```

服务启动后，可在浏览器中打开 Web 监控看板：`http://127.0.0.1:8787/dashboard` 查看实时请求流量、Token 压缩曲线与图谱状态。

---

### 2. 客户端生态接入

#### 方式一：Wrap 一键直接拉起 Agent（推荐，零配置）
```bash
# 自动在后台启动网关、自动感知原有中转地址并直接进入 Agent 终端：
ctxguard wrap claude        # 一键启动 Claude Code
ctxguard wrap pi            # 一键启动 Pi Agent
ctxguard wrap codex         # 一键启动 Codex
```
> **Wrap 运行原理与底层工作流**：
> 1. **网关自愈探测**：自动检测 `8787` 端口是否存活，若未启动则毫秒级在后台自动静默拉起 Proxy 网关。
> 2. **上游配置自动感知 (Auto-Discovery)**：自动读取 `~/.claude/settings.json` 或 Pi 等配置文件中原本保存的真实中转站 API 地址与 Key，并在网关中建立专用映射。
> 3. **进程级隔离注入 (Isolated Spawning)**：在内存中为即将拉起的 Agent 子进程独立注入 `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`，**完全不污染操作系统的全局环境**。
> 4. **原生 TTY 终端接管**：无缝透传 stdin/stdout 交互，退出 Agent 时自动完成状态清理与复盘。

#### 方式二：终端 Shell 快速注入（当前终端全自动生效）
```bash
# 自动设置当前终端会话的环境变量
eval $(ctxguard env --eval)

# 启动你的 Agent 即可自动享受代理加速：
claude
pi
```

#### 方式三：全自动客户端配置桥接（Cursor / Claude / Pi）
```bash
# 自动读取并记忆各客户端原有中转与 Key，自动将客户端 Base URL 改写指向代理网关
ctxguard env --patch
```

#### 方式四：手动配置服务端点
在任意兼容 OpenAI 或 Anthropic 协议的工具中配置代理地址：
- **OpenAI 兼容端点 (GPT / DeepSeek)**：`http://127.0.0.1:8787/v1`
- **Anthropic 兼容端点 (Claude Code)**：`http://127.0.0.1:8787`

---

## 基准测试与生产实测数据

### 1. 标准基准测试 (Synthetic Benchmarks)

在标准受控测试集下的细分场景评测数据：

| 评测场景与优化维度 | 原始 Token 量 | 优化后 Token 量 | 节省比例 | 处理延迟 (p50) |
| :--- | :--- | :--- | :--- | :--- |
| **Git Diff 补丁上下文折叠** | 383 | 197 | **48.56%** | `0.15 ms` |
| **历史大文件重复引用** | 4,200 | 45 | **98.92%** | `0.08 ms` |
| **构建日志与终端控制码** | 1,850 | 320 | **82.70%** | `0.12 ms` |
| **多轮端到端 Coding 轨迹** | 6,735 | 5,584 | **17.09%** | `0.21 ms` |
| **模型输出端精简与塑造** | 1,240 (Output) | 860 (Output) | **30.70%** | `0.00 ms` |

### 2. 真实生产环境实测累计表现 (Production Real-World Stats)

基于本地 `.ctxguard.db` 记录的日常多 Agent 真实写代码会话累计数据：

| 核心统计指标 | 真实生产环境统计值 | 说明 |
| :--- | :--- | :--- |
| **拦截处理请求总量** | **2,499 次** | 涵盖日常编码、代码审查、单元测试等真实 Agent 轨迹 |
| **原始输入 Token 总量** | **480,922,262 Tokens** (~4.8 亿) | 未经网关优化的原始请求上下文体积 |
| **优化后输入 Token 量** | **123,253,252 Tokens** (~1.2 亿) | 经指纹去重、Diff折叠与日志清洗后的实际入参 |
| **累计净节省 Token** | **357,674,148 Tokens** (~3.57 亿) | 实际削减的纯有效上下文体积 |
| **综合上下文压缩率** | **74.37%** | **平均每 1 亿 Token 上下文可压降 7,400 万+** |
| **主流前沿模型实测** | **GPT / Claude / Gemini / DeepSeek** | 实测各主流旗舰模型均保持 **58% ~ 88%** 稳定压缩率 |

---

## 模块开关与高级配置 (ctxguard.yaml)

CtxGuard 各核心引擎支持在 `ctxguard.yaml` 中进行细粒度的独立开关控制：

```yaml
# 1. 记忆图谱与偏好召回开关 (Memory & Piggyback Extraction)
piggyback_extraction:
  enabled: true       # 设为 false 则关闭偏好记忆提取与上下文动态注入

# 2. 自进化与规则同步开关 (Autonomous Learning & Rule Sync)
learn:
  enabled: true       # 设为 false 则停止死循环扫描与项目规则文件自动修改
  detect_loop_threshold: 3

# 3. 输出端 Token 塑造与降噪 (Output Shaper)
output_shaper:
  enabled: false      # 设为 true 开启输出端客套话修剪与思考预算动态降级
  level: 2            # 1: 轻度精简 | 2: 推荐标准 | 3: 高度精炼 | 4: 极限代码

# 4. 自适应调度与三级动态档位 (Adaptive Pipeline)
adaptive_pipeline:
  enabled: true       # 设为 false 则始终使用纯无损基础压缩
  levels:
    - name: "level_1" # 档位 1 (< 128k Tokens): 纯无损结构压缩 (ANSI/GitDiff/Progress)
      max_tokens: 131072
      compression_mode: "lossless"
    - name: "level_2" # 档位 2 (128k ~ 512k Tokens): 轻量 AST 骨架提取与堆栈剪枝
      max_tokens: 524288
      compression_mode: "lightweight"
    - name: "level_3" # 档位 3 (512k ~ 2M+ Tokens): 深度修剪与激进语义去重 (超长防爆档)
      max_tokens: 2097152
      compression_mode: "deep"
  protected_keywords: ["CRITICAL", "FATAL", "TODO", "FIXME", "EXCEPTION"]
```

---

## CLI 命令速查

```bash
ctxguard wrap <agent>     # 自动感知中转配置并直接一键拉起目标 Agent (claude/pi/codex)
ctxguard env --patch      # 自动扫描并改写本地客户端配置指向代理网关
ctxguard stats            # 查看网关当前的吞吐量、压缩效率与近期待处理请求
ctxguard savings          # 查看长周期的 Token 与成本节约明细
ctxguard learn --dry-run  # 预览复盘提炼的避坑经验与浪费权重（不写磁盘）
ctxguard learn --apply    # 触发自进化学习，智能结转并写入项目规则 (AGENTS.md / .cursorrules)
ctxguard learn -a claude  # 指定仅扫描特定 Agent 生态 (auto / claude / ctxguard / gemini / codex)
ctxguard env              # 查看或导出各客户端的环境变量配置
```

---

## 开源许可证

本项目基于 [MIT License](LICENSE) 许可证开源发布。

