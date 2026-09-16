# 面试问答 · CtxGuard 上下文优化与智能守护网关

> 本专栏是针对 **CtxGuard（Context Guard）** 项目的全套架构解析、源码级技术原理与面试问答手册。
> CtxGuard 专注于在应用代理层解决 AI Agent 的 **Token 消耗暴涨** 与 **厂商 Prompt Cache 破坏** 两大核心痛点。
> 架构融合了 `sqz`（指纹可逆展开）、`Headroom`（前缀缓存安全与离线学习）、`Kompact`（自适应档位调度）、`LLMLingua-2`（轻量双向剪枝）与 `Mem0/Zep`（时序图谱记忆），实现 **0 重型依赖、单文件免运维、<3ms 极低代理延迟**。

---

## 专栏全景目录

### 架构与技术深度专栏：[ctxguard 核心模块详解](ctxguard/README.md)

| 编号 | 核心模块 | 核心技术亮点与一句话解析 | 对应代码实现 |
|:---|:---|:---|:---|
| **00** | [架构总览](ctxguard/00-架构总览.md) | 双协议透明反向代理、六层流水线、<3ms 极低延迟与数据生命周期 | `ctxguard/proxy/`, `pipeline.py` |
| **01** | [内容压缩](ctxguard/01-内容压缩/README.md) | 六大算子流水线、JSON 数组 Schema 折叠、ANSI/堆栈正则清洗、自适应调度（**8 篇子文档**） | `ctxguard/core/compressors/` |
| **02** | [缓存安全](ctxguard/02-缓存安全.md) | **第一性原理：Cache > Compression**，Token 边界反推、字节级防抖与经济套利仲裁 | `ctxguard/core/guards/cache_guard.py` |
| **03** | [可逆压缩](ctxguard/03-可逆压缩.md) | SHA-256 内容指纹、`[Ref:...]` 标记、`ctx_expand` 虚拟工具与 0 Token 本地拦截 | `ctxguard/core/virtual_tools/`, `dedup.py` |
| **04** | [流式响应与拦截](ctxguard/04-流式响应与拦截.md) | 字节级 SSE 零缓冲透传、流式 Token 实时计量、工具调用本地短路 | `ctxguard/proxy/sse.py`, `upstream.py` |
| **05** | [时序记忆与图谱](ctxguard/05-时序记忆与图谱.md) | 单文件 SQLite + FTS5 BM25 检索、BFS 2 跳子图、事实版本演化链 (Supersession Chain) | `ctxguard/storage/repository_graph.py` |
| **06** | [语义缓存](ctxguard/06-语义缓存.md) | 会话级精确哈希与全局余弦相似度匹配，0 Token / 0ms 短路返回 | `ctxguard/core/semantic_cache.py` |
| **07** | [多模态与超长上下文](ctxguard/07-多模态与超长上下文.md) | Vision Base64 隔离透传、超长上下文自适应降级控制与冷重压缩 | `ctxguard/core/adaptive_scheduler.py` |
| **08** | [失败学习与自进化](ctxguard/08-失败学习与自进化.md) | `ctxguard learn` 离线死循环挖掘、报错到成功因果转折点提取、`CLAUDE.local.md` 幂等落盘 | `ctxguard/learn/` |
| **09** | [省钱统计与账本](ctxguard/09-省钱统计与账本.md) | SQLite WAL 双向记账本、Token 节省率/资金看板、CLI 看板与 Web 监控 | `ctxguard/storage/savings_ledger.py` |
| **10** | [接入方式与多协议适配](ctxguard/10-接入方式与多协议适配.md) | 零业务侵入切换 `base_url`、OpenAI/Anthropic 双向适配器、Cursor / Claude Code / MCP 接入 | `ctxguard/proxy/adapters/` |
| **11** | [踩过的坑与技术内幕](ctxguard/11-踩过的坑与技术内幕.md) | 缓存雪崩、工具翻转震荡、序列化转义微差、堆栈误剪等 6 大血泪教训 | 核心架构复盘 |
| **12** | [模式与配置系统](ctxguard/12-模式与配置系统.md) | 5 层配置合并优先级、Pydantic v2 强校验 Schema、自定义 Python Hook 拦截器 | `ctxguard/config/` |

---

## 面试速查专栏

- [面试口径与标准话术速查](面试口径.md) —— 30 秒极简版、高频追问标准答案、团队分工与架构权衡、禁忌词对照表。
- [上下文架构演进与行业对比](上下文架构演进与对比.md) —— CtxGuard 与 Headroom / sqz / Kompact / LLMLingua-2 / Mem0 的全面对比。

---
*版本：v1.0 (2026-09) · 项目：CtxGuard*
