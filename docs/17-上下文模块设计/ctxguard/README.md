# CtxGuard 架构与功能详解专栏

> `CtxGuard`（Context Guard —— 上下文守护者）是一个高性能、超轻量级本地代理网关，位于客户端（Cursor / Claude Code / Agent SDK）与云端大模型 API（Anthropic / OpenAI / DeepSeek）之间。
> 
> 本专栏按照工业级功能模块切分，逐一深度解析 CtxGuard 的底层机制、核心代码实现、数学公式与避坑实践。

---

## 模块清单与功能导航

| 编号 | 模块名 | 核心机制与技术深度 | 对应源码路径 |
|---|---|---|---|
| **00** | [架构总览](00-架构总览.md) | 双协议透明代理、六层流水线、<3ms 极低延迟与数据生命周期 | `ctxguard/proxy/`, `ctxguard/core/pipeline.py` |
| **01** | [内容压缩](01-内容压缩/) | 六大算子流水线、JSON 结构折叠、ANSI/进度条清洗、多档自适应（8 篇子文档） | `ctxguard/core/compressors/` |
| **02** | [缓存安全](02-缓存安全.md) | **第一性原理：Cache > Compression**，Token 边界反算、字节防抖与经济套利 | `ctxguard/core/guards/cache_guard.py` |
| **03** | [可逆压缩](03-可逆压缩.md) | SHA-256 内容指纹、引用替换、`ctx_expand` 虚拟工具与 0 Token 本地拦截 | `ctxguard/core/virtual_tools/`, `dedup.py` |
| **04** | [流式响应与拦截](04-流式响应与拦截.md) | SSE 字节级透明透传、流式 Token 统计与工具调用短路 | `ctxguard/proxy/sse.py`, `upstream.py` |
| **05** | [时序记忆与图谱](05-时序记忆与图谱.md) | 单文件 SQLite + FTS5 BM25 检索、BFS 2 跳子图、事实演化链 (Supersession) | `ctxguard/storage/repository_graph.py` |
| **06** | [语义缓存](06-语义缓存.md) | 会话级与跨请求精确哈希/向量近似匹配，0 Token / 0ms 短路返回 | `ctxguard/core/semantic_cache.py` |
| **07** | [多模态与超长上下文](07-多模态与超长上下文.md) | 图像/文件多模态 Payload 透传、超长上下文自适应降级控制 | `ctxguard/core/adaptive_scheduler.py` |
| **08** | [失败学习与自进化](08-失败学习与自进化.md) | 离线死循环挖掘、报错到修复因果转折点提取、规则幂等写入 `CLAUDE.local.md` | `ctxguard/learn/` |
| **09** | [省钱统计与账本](09-省钱统计与账本.md) | SQLite WAL 双向记账本、Token 节省率/资金看板、CLI 看板与 Web 监控 | `ctxguard/storage/savings_ledger.py` |
| **10** | [接入方式与多协议适配](10-接入方式与多协议适配.md) | 零侵入代理接入、OpenAI/Anthropic 双向适配器、Cursor/Claude Code 集成 | `ctxguard/proxy/adapters/` |
| **11** | [踩过的坑与技术内幕](11-踩过的坑与技术内幕.md) | 破坏前缀缓存的雪崩代价、工具翻转震荡、序列化转义差异等 6 大深坑 | 核心架构复盘 |
| **12** | [模式与配置系统](12-模式与配置系统.md) | 5 层配置覆盖优先级、Pydantic v2 校验模型与自定义 Python Hook 插件 | `ctxguard/config/` |

---

## 快速阅读路线推荐

如果你只有 15 分钟准备面试，建议重点攻读以下核心篇章：

1. **[02-缓存安全](02-缓存安全.md)** —— 整个项目的立足之本与第一性原理，讲清楚为什么不能盲目改写历史上下文。
2. **[03-可逆压缩](03-可逆压缩.md)** —— Agent 场景中最惊艳的 0 Token 还原杀手锏。
3. **[11-踩过的坑与技术内幕](11-踩过的坑与技术内幕.md)** —— 真实工业界场景踩出来的血泪经验，最能展现资深技术深度。
4. **[08-失败学习与自进化](08-失败学习与自进化.md)** —— 区别于普通压缩工具的 Agent 离线闭环自进化亮点。

---
*版本：v1.0 (2026-09) · CtxGuard Core Architecture Reference*
