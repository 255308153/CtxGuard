# 01 · CtxGuard 结构化内容压缩算子体系

> 本子专栏深入剖析 CtxGuard 内部的六大结构化压缩算子、自适应调度器与流水线实现。

---

## 算子与章节导航

| 编号 | 篇章名 | 核心内容与技术点 | 对应源码实现 |
|:---|:---|:---|:---|
| **01** | [01-它要解决什么问题](01-它要解决什么问题.md) | Agent 运行时的重复文件读取、同构 JSON 键名膨胀与终端 ANSI 噪音 | `ctxguard/core/compressors/` |
| **02** | [02-六大算子流水线](02-六大算子流水线.md) | `BaseCompressor` 基类规范、流水线串联顺序、回滚机制与 Hook 扩展 | `ctxguard/core/pipeline.py` |
| **03** | [03-JSON结构无损折叠](03-JSON结构无损折叠.md) | 同构对象数组提取 `_schema` 表头与 `_rows` 矩阵，实测无损压缩 48% | `ctxguard/core/compressors/json_struct.py` |
| **04** | [04-终端与日志智能清洗](04-终端与日志智能清洗.md) | ANSI 颜色转义码剥离、进度条最终帧合并、连续异常堆栈折叠 [Repeated N times] | `ansi_cleaner.py`, `progress_merger.py`, `stacktrace.py` |
| **05** | [05-自适应调度与多档位控制](05-自适应调度与多档位控制.md) | AdaptiveScheduler 动态分级：Level 0 透传、Level 1 规则、Level 2 深度、Level 3 ONNX | `ctxguard/core/adaptive_scheduler.py` |
| **06** | [06-ONNX轻量语义剪枝](06-ONNX轻量语义剪枝.md) | 借鉴 LLMLingua-2 思想，微型双向编码器 INT8 打分剪枝，保护关键字白名单 | `ctxguard/plugins/onnx/scorer.py` |
| **07** | [07-代价与质量边界](07-代价与质量边界.md) | Assistant 消息不可变红线、代码语法保真与经济套利兜底 | 架构质量规范 |

---
*版本：v1.0 (2026-09) · 项目：CtxGuard*
