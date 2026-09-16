# 03 · JSON 结构无损折叠

## 一、 核心原理

在工具调用与数据库检索场景中，返回的往往是由相同字段构成的对象数组（Homogeneous Dict Array）。

`JSONStructCompressor` 会自动识别文本中的 JSON 数组模式，提取公共字段集合作为 `_schema`，并将所有对象的数据展平为二维矩阵 `_rows`：

```text
【原始 JSON 数组 (约 350 Token)】
[
  {"id": 101, "name": "user_auth", "status": "success", "latency_ms": 12},
  {"id": 102, "name": "db_query",  "status": "success", "latency_ms": 45},
  {"id": 103, "name": "cache_get", "status": "failed",  "latency_ms": 3}
]

            ───────► 【CtxGuard 折叠后 (约 130 Token)】 ───────►

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

## 二、 核心算法与安全判定规则

在 `ctxguard/core/compressors/json_struct.py` 中，执行严格的安全过滤：

1. **同构性校验（Homogeneity Check）**：
   - 检查数组中每个元素是否全为字典（Dict）；
   - 校验所有元素的键名集合必须与第一项完全一致（`set(item.keys()) == first_keys_set`）；
2. **最小长度门槛（Length Threshold）**：
   - 数组元素个数必须 `>= min_array_length`（默认 3 项），避免对 1~2 项的小数组进行无意义折叠引入开销；
3. **白名单/黑名单忽略**：
   - 若包含 `ignore_keys`（如特定需要保持标准结构的代码配置），则自动跳过；
4. **大模型理解无损性**：
   - 主流大模型（Claude 3.5 / GPT-4o / DeepSeek）对表格型 `_schema + _rows` 具有极强内建先验理解能力，QA 准确率无任何下降。

---
*版本：v1.0 (2026-09)*
