# 03 · JSON 结构无损折叠 (JSONStructCompressor)

## 一、 核心算法机制

在 `ctxguard/core/compressors/json_struct.py` 中，`JSONStructCompressor` 专门针对大模型工具返回的同构对象数组进行结构折叠：

```text
【原始同构 JSON 数组 (约 537 Token)】
[
  {"id": 101, "name": "user_auth", "status": "success", "latency_ms": 12},
  {"id": 102, "name": "db_query",  "status": "success", "latency_ms": 45},
  {"id": 103, "name": "cache_get", "status": "failed",  "latency_ms": 3}
]

            ───────► 【CtxGuard 提取表头折叠后 (约 279 Token)】 ───────►

{
  "_schema": ["id", "name", "status", "latency_ms"],
  "_rows": [
    [101, "user_auth", "success", 12],
    [102, "db_query",  "success", 45],
    [103, "cache_get", "failed",  3]
  ]
}
```

---

## 二、 严格的安全校验门禁

在执行折叠前，代码进行四重安全检查：
1. **JSON 数组正则定位**：使用 `JSON_ARRAY_REGEX = re.compile(r"(\[\s*\{[\s\S]*?\}\s*\])")` 快速定位子串；
2. **同构性检查（Homogeneity Check）**：检查所有元素是否均为 `dict`，且其 `keys()` 集合必须与首个元素完全一致（`set(item.keys()) == first_keys_set`）；
3. **最小长度阈值**：仅当数组长度 `>= min_array_length`（默认 3）且键名数 `>= 2` 时才触发；
4. **忽略特定敏感 Key**：若包含 `ignore_keys` 中声明的字段，自动放行不处理。

---

## 三、 实测 Benchmark 效果

根据 `benchmarks/run_benchmark.py` 的实测数据：
- **场景**：RAG Database Tool Output (Homogeneous JSON)
- **原始 Token**：537 Token
- **折叠后 Token**：279 Token
- **节省率**：**48.04%**
- **处理延迟**：仅 **0.32ms**（采用 `orjson` 快速解析重组）

---
*版本：v1.0 (2026-09) · 关联源码：`ctxguard/core/compressors/json_struct.py`*
