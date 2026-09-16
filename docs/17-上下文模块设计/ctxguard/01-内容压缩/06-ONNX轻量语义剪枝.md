# 06 · ONNX 轻量语义剪枝插件

## 一、 设计思想：借鉴 LLMLingua-2 剪枝精髓

传统文本摘要采用生成式因果大模型（Causal LLM），存在以下致命缺点：
1. **生成延迟极高（> 500ms）**；
2. **存在幻觉风险，会修改原始事实**；
3. **内存开销巨大（需载入数十亿参数模型）**。

CtxGuard 引入可选的 `plugins/onnx/` 插件，借鉴 **LLMLingua-2** 的 Token 分类（Token Classification）思路：
- 采用微型双向编码器（Bi-Encoder，如 INT8 量化后的 XLM-RoBERTa-mini，体积仅 30MB）；
- 对输入的每个 Token 进行重要性二分类打分（保留 / 丢弃），并行前向传播耗时仅需 **3~5ms**。

---

## 二、 架构与关键词保护机制 (`SemanticPruner`)

在 `ctxguard/plugins/onnx/scorer.py` 中，实行严格的保护白名单：

```python
class SemanticPruner(BaseCompressor):
    def __init__(self, protected_keywords: Optional[List[str]] = None):
        self.protected_keywords = set(protected_keywords or [
            "def ", "class ", "return", "import", "error", "exception",
            "fail", "assert", "http", "curl", "key", "token"
        ])

    def compress_text(self, text: str) -> str:
        # 1. 语法关键行与包含保护关键词的行绝对不剪枝
        # 2. 仅对长段落、自然语言描述与长注释进行 INT8 概率打分丢词
```

---

## 三、 零重型框架的工程实现

- **绝不引入 PyTorch 或 HuggingFace Transformers**；
- 仅依赖轻量级 `onnxruntime-cpu` 运行时与 C++ 编写的 `tokenizers` 库；
- 内存常驻仅增加约 45MB，CPU 单核即可跑满 5,000 Token/s。

---
*版本：v1.0 (2026-09)*
