# 01 · 内容压缩算子体系详解

> 本子专栏深入剖析 CtxGuard 的核心结构化压缩算子与自适应流水线实现。

---

## 篇章目录

| 编号 | 篇章名 | 核心内容与技术点 | 涉及源码 |
|---|---|---|---|
| **01** | [01-它要解决什么问题](01-它要解决什么问题.md) | Agent 场景的 Token 冗余痛点：重复文件、JSON Schema 膨胀、ANSI 噪音 | `core/compressors/` |
| **02** | [02-六大算子流水线](02-六大算子流水线.md) | 六大算子串联执行顺序、数据流转机制与 Hook 拦截扩展 | `core/pipeline.py` |
| **03** | [03-JSON结构无损折叠](03-JSON结构无损折叠.md) | 同构对象数组提取 `_schema` 表头与 `_rows` 矩阵，无损压缩 60%+ | `compressors/json_struct.py` |
| **04** | [04-终端与日志智能清洗](04-终端与日志智能清洗.md) | ANSI 颜色转义码剥离、进度条最后一帧合并、重复异常堆栈折叠 | `compressors/ansi_cleaner.py`, `progress_merger.py`, `stacktrace.py` |
| **05** | [05-自适应调度与多档位控制](05-自适应调度与多档位控制.md) | AdaptiveScheduler 动态分级：L0 透传、L1 纯规则、L2 深度折叠、L3 ONNX | `core/adaptive_scheduler.py` |
| **06** | [06-ONNX轻量语义剪枝](06-ONNX轻量语义剪枝.md) | 借鉴 LLMLingua-2 思想，微型双向编码器 INT8 打分剪枝，保护关键字 | `plugins/onnx/scorer.py` |
| **07** | [07-代价与质量边界](07-代价与质量边界.md) | 压缩有损 vs 无损的边界、代码语法安全与回滚机制 | 架构设计底线 |

---
*版本：v1.0 (2026-09)*
