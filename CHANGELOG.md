# Changelog

All notable changes to the CtxGuard project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.3] - 2026-09-18

### Added
- **多进程 Worker 并发支持 (Multi-Worker Execution)**:
  - `ctxguard start` 新增 `-w / --workers` CLI 命令行参数，支持配置 Uvicorn 多进程 Worker 并行（例如 `ctxguard start -w 4`），突破 Python GIL 限制，充分利用多核 CPU 算力。
  - 实现 `create_app_factory()` 应用工厂，确保多 Worker 模式下 FastAPI 实例、路由与中间件安全独立初始化。
- **纯内存热 LRU 缓存与零磁盘 I/O (In-Memory Hot Fingerprint Store)**:
  - 参照 Headroom 内存优先架构，在 `FingerprintRepository` 中引入容量为 10,000 条的纯内存 `OrderedDict`。
  - 消息指纹读取与前缀命中 100% 在内存中完成纳秒级检索，彻底隔离高频读请求对底层磁盘的访问。
- **SQLite 复合索引加速与批量惰性淘汰**:
  - 新增复合索引：`CREATE INDEX IF NOT EXISTS idx_fingerprints_lru ON fingerprints(last_accessed_at, hit_count);`，淘汰查询由全表排序变为索引范围扫描。
  - 将原本“每条消息淘汰一次”的高频磁盘全表扫描重构为“每 250 次写入批量惰性清理”，长会话磁盘事务提交次数削减 99% 以上。

- **多进程 Worker 分布式前缀状态共享与缓存击穿防护 (Distributed Session Cache Guard)**:
  - 针对多 Worker 并行模式下跨进程内存隔离导致的“间歇性 0 缓存击穿”致命 Bug，在 SQLite WAL 库中新增 `session_cache` 表与 `idx_session_cache_updated` 复合索引。
  - 实现 **L1 RAM Hot + L2 SQLite WAL** 双级热同步机制：各 Worker 在决策点前增量检测拉取最新前缀，转发后原子持久化广播，使历史前缀与缓存指标跨进程即时可见。
  - 路由层全面引入 `pipeline.cache_guard.has_compressed_history(session_id)` 跨进程历史感知，彻底杜绝轮询路由下客户端原始报文（raw `body_bytes`）直通上游引发的 KV Cache 击穿归零。
- **系统提示词不可变性与通用清洗算子安全守卫**:
  - `BaseCompressor.process` 显式跳过 `system` 与 `developer` 角色消息，严格遵守 Cache Invariant 2，杜绝前缀字节偏移。
- **官方文档中心精简与架构沉淀**:
  - 清理多余冲突目录（`docs/17-上下文模块设计/`、`面试问答/`、`docs/DEVELOPER_GUIDE.md`），规范化专栏导航与 `04b-输出Token压缩与塑造.md`。
  - 新增踩坑 13（多 Worker 内存隔离与缓存击穿）、踩坑 14（通用算子角色守卫）以及面试 Q10、Q11 问答。

### Optimized
- **CPU 密集流水线异步多线程卸载 (Async Pipeline Offloading)**:
  - 将 `Pipeline.process` 重构为异步方法，通过 `asyncio.to_thread` 将正则分词、代码 AST 语法树解析与 SHA-256 哈希计算卸载到底层 Worker 线程池。
  - 彻底释放主 `asyncio` 事件循环，彻底解决长会话大请求（如 40 万 Token 任务）计算时阻塞后方并发 Agent 请求的排队延迟问题。
- **历史前缀重复写盘消除 (Zero Redundant SQLite Ingestion)**:
  - 在 `DedupCompressor.index_prefix` 中增加 `if sha in fingerprint_store: continue`，已缓存的会话前缀指纹 100% 跳过重复持久化，彻底消除 SSD 异常写磨损。

---

## [0.2.2] - 2026-09-17

### Added
- **Codex Responses API 原生通道支持**:
  - 废弃非标准 Responses API 强制降级到 ChatCompletions 的转换逻辑，为原生支持 Responses API 的上游服务提供 Transparent Passthrough，保留完整的 Codex SSE 事件序列（`response.created`, `response.output_item.added`, `response.text.delta`, `response.output_item.done`, `response.completed`）。
  - 支持 Codex 专有工具类型：保留 `custom_tool_call` 与 `custom_tool_call_output` 数据结构，修复工具调用输出在转发过程中丢失的问题。
- **并发流请求物理隔离 (Stream Transport Isolation)**:
  - 引入针对流式请求的独立 HTTP 客户端隔离机制，每个 SSE 流使用独立的会话实例，彻底杜绝多并发场景下连接池相互影响的问题。
  - 针对 Codex 客户端主消息流（`gpt-5.6-sol`）与后台会话标题生成流（`gpt-5.6-luna`）的并发冲突，添加轻量模型智能兼容重映射（`gpt-5.6-luna` -> `gpt-5.5`），确保并发请求 100% 成功。
  - 自动嗅探与智能绑定本地代理（支持 Clash / Clash Verge 端口 `7897`），并在网络异常时安全回退。
- **全量测试用例扩充**:
  - 新增 Codex 原生 Responses 流式透传测试。
  - 新增双路并发流隔离防断连回归测试。
  - 新增 `developer` 指令缓存守卫不变性测试。
  - 自动化测试套件通过数提升至 **169 passed**。

### Fixed
- **多轮会话 Prompt Cache 缓存命中率雪崩修复**:
  - 严格执行 **Cache Invariant 1**：会话在首轮建立压缩前缀后，后续请求禁止直接透传客户端原始 `body_bytes`，改为发送一致序列化的压缩前缀，彻底解决后续轮次云端 KV Cache 命中数跌至个位数的问题。
  - 严格执行 **Cache Invariant 2**：对 `developer` / `system` 角色内容实施绝对不可变保护，防止语义剪枝或引用替换破坏系统提示词一致性。
- **Codex 桌面端 Stream Disconnection 异常修复**:
  - 修复上游重试循环中意外调用全局客户端 `close()` 导致活跃主连接中断抛出 `stream disconnected before completion: Transport error: network error: error decoding response body` 的问题。
  - 拦截并安全吞咽上游流生成器中的 `httpx.TransportError`，向客户端正常补齐合法关闭信号，避免客户端 Rust reqwest 解码器直接崩溃。
- **SSE Token 统计回填优化**:
  - 支持解析 OpenAI 格式与 Responses 格式下的 `response.usage.input_token_details.cached_tokens`，精准记录并呈现云端缓存命中节省效果。

---

## [0.2.1] - 2026-09-17

### Added
- **对齐 Headroom 确定性语义精简流水线**:
  - 实现三阶精简梯级（Lossless Pinning -> Dual-Head Neural Pruning -> Exact Span Reconstruction）。
  - 引入 `_KOMPRESS_MUST_KEEP_RE` 模式匹配，增加中文否定词与核心控制动词保留策略，杜绝因语义压缩引起的逻辑反转。
- **自适应超长上下文阶梯降级**:
  - 支持 128k、512k、2M 超长上下文梯级自适应阈值，动态调控压缩激进度与保留比例。
- **CLI 智能封装与客户端自动补丁**:
  - 增加 `ctxguard wrap` 命令，支持自动探测 agent 客户端配置并原地注入透明代理环境。

### Fixed
- 修复未压缩后续轮次的会话缓存失效隐患。
- 修复流式中断时 `on_complete` 回调未执行导致的指标统计丢失问题。

---

## [0.2.0] - 2026-09-17

### Added
- **Tree-sitter AST 语法树骨架提取**:
  - 支持 Python、TypeScript、Go、Rust、Java 等多语言代码块轻量化结构提取。
- **Tool Delta 影子状态机**:
  - 跟踪长链路 Agent 执行状态，过滤冗余中间结果与重复巡检日志。
- **长效时序经验沉淀 (Self-Evolving Learning Engine)**:
  - 引入单文件 SQLite 时序图谱存储（`SQLiteGraphStore`）。
  - 实现故障归因与死循环检测器（Loop Detector & Pivot Analyzer），自动提取并生成避坑规则。
- **敏感信息自动脱敏 (Secret Redactor)**:
  - 正则匹配与擦除 API 密钥、数据库连接串与敏感凭证。

---

## [0.1.0] - 2026-09-16

### Added
- **透明反向代理核心网关**:
  - 兼容 OpenAI 与 Anthropic 协议双向中转与流式适配。
- **实时 Web 控制面板 (Dashboard)**:
  - 提供数据监控大盘、Token 节省趋势、会话回放与知识图谱拓扑展示。
- **项目级路由与会话指纹管理**:
  - 支持 `/p/{project}/...` 动态路由隔离与客户端指纹自动追踪。
