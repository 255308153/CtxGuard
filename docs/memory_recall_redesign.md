# CtxGuard 记忆召回引擎架构设计方案 (Memory Recall Engine)

## 一、 现状痛点剖析
1. **历史块重复堆叠 (Duplication Bug)**：在多轮对话中，网关未对历史残留标签进行清洗，导致 `[Memory Extraction Protocol]` 像雪球一样多轮重复堆叠。
2. **全量粗暴吐出 (Zero Relevance Filtering)**：未计算当前 Query 与记忆的相关性，所有三元组全量硬编码吐出，白白浪费 Token 并干扰模型。
3. **生硬机器格式 (Unnatural Triplets)**：直接输出 `User operates_on macOS`，缺乏语义自然度。

---

## 二、 核心架构重构 (3 层召回过滤流水线)

```
        用户最新提问 (User Query)
                   │
                   ▼
  ┌─────────────────────────────────┐
  │ 1. 幂等性清洗层 (Sanitizer)      │  <-- 正则剥除历史消息中残留的注入块
  └────────────────┬────────────────┘
                   │
                   ▼
  ┌─────────────────────────────────┐
  │ 2. 混合相关性评分 (Hybrid Scorer)│  <-- BM25 + Jaccard/Embedding 语义相关性
  └────────────────┬────────────────┘
                   │  (得分 < 0.35 阈值 -> 0 注入，零 Token 浪费)
                   ▼
  ┌─────────────────────────────────┐
  │ 3. 预算与自然语言合成 (Synthesizer)│  <-- Top-K (<= 3条) 自然语言格式化
  └─────────────────────────────────┘
```

---

## 三、 召回模板升级对比

### 改造前 (生硬且重复)：
```markdown
[Personal Knowledge Graph Context]
[e9d49ea5] **User** *operates_on* **macOS**
[e9d49ea5] **User** *prefers_default_model* **DeepSeek-Flash**
[/Personal Knowledge Graph Context]
```

### 改造后 (自然、精准且只在相关时召回)：
```markdown
[User Context & Preferences]
- Operating System: macOS (Apple Silicon) [ref: #e9d4]
- Primary Workflow: Uses pi agent with pi-web as UI [ref: #f8c1]
[/User Context & Preferences]
```

---

## 四、 实施计划
1. 在 `ctxguard/core/memory/` 下实现 `relevance.py`（相关性打分与自适应阈值门禁）；
2. 重构 `graph_engine.py` 的 `inject_graph_context`（增加全量消息幂等清洗 + 自然语言合成）；
3. 增加单元测试与端到端召回精度测试。
