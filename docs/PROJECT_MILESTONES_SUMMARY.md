# CtxGuard 完整研发历程与核心技术演进报告
> **Context Optimization, Prompt Cache Stabilization, Temporal Knowledge Graph & Self-Evolution Gateway**

---

## 🏛️ 阶段一：网关核心基座与全功能可视化控制面板
1. **内嵌式现代化 Web 控制面板 (`dashboard.py` / `:8787/dashboard`)**：
   - 从 0 到 1 构建了包含四大核心监控板块的控制面板；
   - 支持按项目（Project）、会话（Session ID / 对话名称）、模型（Model）进行多维分类与流控过滤；
   - 引入 Chart.js 实时 Token 流量折线图，动态对比 Raw Tokens vs Optimized Tokens 并渲染节省阴影；
   - 修复了 `refreshData` 中 DOM null 报错、表格重复渲染，并将大面积会话矩阵优化为默认折叠面板（`<details>`）。
2. **多客户端来源与会话追踪**：
   - 实现了针对 Pi Agent / Pi-Web、Cursor、Claude Code 的请求指纹与客户端类型智能嗅探；
   - 实现了 `/p/{project}/v1/chat/completions` 多项目路径路由隔离。

---

## ⚡ 阶段二：流式网络与协议层核心修复
1. **SSE 流式思考与输出实时隔离 (`f2201d8`)**：
   - 实现了对 DeepSeek-R1 / o1 / o3 思考链（`reasoning_content` / `thinking`）的独立捕获与实时隔离传递。
2. **SSE 异常标准事件封装 (`4e25784`)**：
   - 修复了上游大模型报错时直接掐断连接导致前端客户端抛 `Unexpected EOF` 的问题，改用标准的 OpenAI/Anthropic SSE 错误事件安全封装。
3. **防止模型 Prompt 模仿（Prompt Mimicry Fix `87f7cce`)**：
   - 修复了此前对 `assistant` 历史消息进行去重导致大模型模仿 `[Ref: ...]` 格式的严重 Bug，确立了“仅对 tool/user 消息进行结构化折叠，assistant 消息坚决不折叠”的铁律。
4. **流式中途取消与缓存击穿防护 (`17d4f6c`)**：
   - 在 `SSEStreamHandler` 中引入 `try...finally` 异常熔断守护，彻底解决用户点击 Stop 取消导致缓存状态丢失的隐蔽 Bug。


---

## 🛡️ 阶段三：Prompt Cache 物理级绝对防抖体系
1. **工具与 Schema 递归字母序归一化 (`ToolsNormalizer`)**：
   - 递归对所有 `tools[]` 的名称、`properties`、`required` 列表进行字典序稳定重排，彻底消除由于客户端字典无序导致的前缀缓存头部报废。
2. **物理级原始二进制切片重放 (`RawByteOverlayGuard`)**：
   - 针对未修改的历史前缀，跳过 Python 字典反序列化，直传 HTTP 原始二进制切片，达成 SHA-256 物理级 0 字节漂移。
3. **首部系统提示词快照冻结 (`Session Prefix Freeze`)**：
   - 会话中途首部快照锁定，避坑提醒严格限定在最新 User 消息尾部，彻底杜绝会话中途改动 Rule 造成的缓存击穿。

---

## 🗜️ 阶段四：结构化专用压缩算子流水线矩阵
1. **Git Diff 专用上下文折叠算子 (`GitDiffCompressor`)**：
   - 精准识别 Unified Diff 结构，严格保留增删改行，折叠无变动上下文行，单项节约 48.6% Token，耗时仅 0.15ms。
2. **AST 代码骨架修剪 (`ASTCodeCompressor`)**：
   - 对首次读取的大型代码文件，利用 AST 语法树修剪函数体实现紧凑代码骨架提取。
3. **可逆解压内容指纹库 (`FingerprintRepository`)**：
   - 长文本按块哈希入库，支持模型调用 `ctx_expand` 虚拟工具 0-Token 本地瞬时还原；引入访问频次与时间加权的 LRU 自动容量淘汰引擎。
4. **输出端 Token 塑造与降噪 (`OutputShaper`)**：
   - 注入字节稳定型哨兵消除开场白与复述，结合状态机在机械轮次动态降级思考预算，实测输出侧 Token 净降 30.7%。


---

## 🧠 阶段五：时序知识图谱与因果自进化闭环
1. **跨 Agent 时序知识图谱引擎 (`MemoryGraphEngine`)**：
   - 支持自由谓词、实体关系网、中文 Bigram 分词与四级作用域；
   - 废除生硬文本便签，改用 BM25关键词 + 向量语义 + 图谱关系推理三路混合检索在 User 消息尾部幂等召回；
   - 挂载 `memory_save` / `memory_search` 虚拟工具，大模型自主调用、网关出口本地拦截入库。
2. **多轮标签循环堆叠强力根治 (`sanitizer.py`)**：
   - 引入全字符集泛化清洗器，网关入口处对所有历史版本记忆标签做 100% 幂等强力擦除。
3. **日常反问句误判入库硬拦截**：
   - 增加疑问/反问语气词（`吗/呢/？/?/还是`）硬拦截与停用词黑名单，杜绝把日常反问存入偏好图谱。
4. **工业级规则剪枝与预算淘汰 (`RulePruner`)**：
   - 深度对齐 Headroom，实现基于 `category+trigger` 的版本覆盖（Supersede）、10 条上限预算截断，以标准边界注释标记（`<!-- ctxguard:learn:start -->`）原子替换规则文件。

---

## 🚀 阶段六：全生态一键接入、基准评测与代码开源
1. **全生态 Agent 一键适配器 (`ctxguard env`)**：
   - 支持 `eval $(ctxguard env --eval)` 一键注入环境变量；
   - 支持 `ctxguard env --patch` 自动探测并记忆每个客户端原本的中转地址与 Key，实现多端各走各的中转站、独立分流。
2. **真实多轮 Agent 交互轨迹评测套件 (`trajectory_eval.py`)**：
   - 构建 10 轮真实 Coding Agent 评测工作流，端到端证明“既大幅节省 Token，又 100% 保持前缀字节不变”。
3. **全套自动化测试与文档开源同步**：
   - 单元与集成测试扩充至 133 个（100% 全部通过）；
   - 安全脱敏全量代码，更新 `pyproject.toml` 支持全局 CLI 安装，并成功同步推送到 GitHub 远程仓库！
