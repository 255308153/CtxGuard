# 04 · 输出 Token 压缩与塑造 (Output Token Shaping)

## 1. 业务背景与第一性原理

在大模型 Agent 真实计费与延迟构成中，**Output Token 的单价通常是 Input Token 的 3~5 倍**（以 Claude 3.5 Sonnet 为例：Input $3/M vs Output $15/M）。
不仅如此，大模型输出的每一个字都需要占用 GPU 的自回归解码时间（Autoregressive Decoding Time），冗长的客套话与复述代码会直接拖慢 Agentic Loop 的整体流转效率。

因此，CtxGuard 借鉴 Headroom 架构设计，引入 **`OutputShaper`** 引擎，从“源头”重塑大模型的输出行为。

---

## 2. 输出精简等级矩阵 (Verbosity Levels)

| 等级 | 适用场景 | 约束策略与指令行为 | 预计 Output Token 节省 |
| :--- | :--- | :--- | :---: |
| **Level 0** | 原生模式 | 0 介入，保持模型默认输出习惯 | 0% |
| **Level 1** | 日常辅助 | 剔除开场套话与结尾复述（No preamble/postamble） | 10%~15% |
| **Level 2 (默认)** | 编码 Agent | **禁止复述已有代码、Diff 与长工具输出**；工具执行成功后直接继续，不废话叙述 | **25%~35%** |
| **Level 3** | 高频调试 | 仅给结论省略解释；**强制优先生成最小局部 Edit，严禁重写全文件** | **35%~50%** |
| **Level 4** | 极限极简 | 极简碎片化输出，仅保留核心代码片段与操作 | 50%+ |

---

## 3. 缓存安全与幂等哨兵机制 (Cache-Safe Sentinel)

为了避免输出控制提示词破坏云端大模型的 Prompt Cache，`OutputShaper` 严格遵守以下两条底线：

1. **字节绝对稳定 (Byte-Stable Text)**：各等级的控制提示词硬编码固化，禁止动态拼接可变时间戳或随机字符；
2. **边界哨兵原子替换 (`<ctxguard_output_shaping>`)**：
   - 注入在 System Prompt 的最末尾；
   - 采用严格哨兵标记包裹，多次流转时自动执行幂等匹配，切换等级时原地原子替换，绝不重复堆叠。

---

## 4. 思考预算动态降级 (Effort Routing)

1. **机械轮次 vs 推理轮次状态机**：
   - 当检测到上一轮为纯读取文件或测试通过时，判定为机械轮次，自动将 `effort` 从 `xhigh` 降级为 `low`；
   - 遇到报错或新需求时保持全开，避免不必要的万字思考浪费。

---

## 5. 基准评测与 30.7% 降幅来源

参考 Headroom 标准评测套件（`eval_output_shaper.py`），在代码审查场景进行 A/B 双盲对照：
- **基准组（Baseline）**：平均输出 1,240 Output Tokens（含开场寒暄与大段复述）；
- **优化组（Shaped Level 2 + Effort Routing）**：平均输出 860 Output Tokens；
- **净降幅**：$\frac{1240 - 860}{1240} \approx \mathbf{30.7\%}$。
