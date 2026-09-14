# CtxGuard 参考项目源码库（References）

本项目吸收借鉴了以下顶尖开源项目的精髓设计：

| 参考项目 | 存放目录 | 核心借鉴技术点 | 源码重要路径 |
| :--- | :--- | :--- | :--- |
| **Headroom** | `references/headroom/` | 1. JSON 数组无损结构压缩与 Schema 提取<br>2. Prompt Cache 静态前缀冻结保护<br>3. 离线失败因果自学习（`headroom learn`） | `headroom/core/`<br>`headroom/learn/`<br>`headroom/proxy/` |
| **sqz** | `references/sqz/` | 1. 基于 SHA-256 的会话级内容指纹去重（~13 Token 指针）<br>2. MCP 代理与可逆展开工具（`sqz_expand`）<br>3. Safe-mode 保护堆栈和报错 | `src/`<br>`crates/` |
| **Kompact** | `references/kompact/` | 1. 纯透明 HTTP 反向代理架构（Zero code changes）<br>2. 8 阶段多档位自适应流水线（Adaptive Pipeline） | `src/`<br>`proxy/` |
| **LLMLingua** | `references/LLMLingua/` | 1. LLMLingua-2 双向微型编码器 Token 分类打分<br>2. 长文本与 RAG 检索块的信息熵剪枝算法 | `llmlingua/` |
