# CtxGuard 记忆系统设计方案 (Memory Architecture Design Document)

## 一、 背景与设计目标

### 1.1 现状与痛点
在现有的大模型记忆系统中，普遍存在以下三类瓶颈：
1. **协议僵化与脆弱性**：基于刚性 Schema（如限定动词 `relation` 只能为 `prefers` 等极少数单词）导致自然语言中丰富的实体关系被意外过滤；
2. **跨 Agent 孤岛**：用户在 `Pi Agent`（命令行/自动化）与 `pi-web`、`Cursor`、`Claude Code` 等不同交互端之间切换时，记忆无法无缝共享与追踪来源；
3. **破坏 Prompt 缓存 (Cache Ruin)**：动态检索到的记忆如果直接拼接在 Prompt 头部或任意插入，会导致云端大模型供应商（Anthropic/OpenAI/DeepSeek）的 KV Cache 完全失效，产生昂贵的重复计费与高延迟；
4. **同步阻塞导致端到端变慢**：如果在每次生成前强制进行昂贵的向量检索或在生成后等待 LLM 提取记忆，会显著拉长用户的首字延迟（TTFT）。

### 1.2 核心设计目标
借鉴 **Mem0**（双路检索+实体增强）、**Headroom**（透明网关代理+跨 Agent 溯源）、**Letta**（分层内存体系）与 **Zep**（时序知识图谱）的设计优势，CtxGuard 记忆体系的目标为：
-  **透明代理（Zero Code Change）**：无须改造 Client 端代码，Pi Agent、pi-web、Cursor 即插即用；
-  **Prompt 缓存绝对对齐（Cache-Safe Injection）**：记忆注入受到前缀防抖门禁管控，确保 100% 命中 KV Cache；
-  **开放式实体与语义拓扑（Open Entity-Relation Graph）**：解除严格谓词限制，支持自由关系抽取与时序覆盖（Supersede）；
-  **跨 Agent 来源追踪（Cross-Agent Provenance）**：记录每条记忆的沉淀来源（`source_agent`、`project_id`、`session_id`）；
-  **异步零开销（Async Pipeline）**：主请求链毫秒级直通，记忆抽取与图谱维护在后台异步完成。

---

## 二、 系统分层架构

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                      Client Layer (Pi Agent / pi-web / Cursor)          │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │  Transparent HTTP/SSE Proxy (:8787)
┌────────────────────────────────────▼────────────────────────────────────┐
│ 1. 代理拦截与缓存对齐层 (Cache-Aligned Ingress Guard)                      │
│    • ToolsNormalizer: 工具定义与 Schema 字典序防抖                       │
│    • CacheGuard: 稳定前缀锚定，安全位置注入 Top-K 记忆                   │
│    • RawByteOverlayGuard: 物理级原始字节切片防漂移                      │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│ 2. 记忆注入与检索引擎 (Memory Retrieval Engine)                          │
│    • 混合检索: SQLite FTS5 (BM25 稀疏) + 本地轻量级 Dense 向量检索         │
│    • 作用域过滤: USER (全局偏好) > PROJECT (仓库架构/规则) > SESSION     │
│    • 语义去重与评分: Relevance Score = α * Sim(Text) + β * EntityMatch   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│ 3. 存储与图谱拓扑层 (Hierarchical & Temporal Graph Storage)               │
│    • Memory Table: [mem_id, entity, relation, target, desc, scope]      │
│    • Temporal Versioning: 支持 active / superseded 版本链               │
│    • Provenance Meta: [source_agent, project_id, timestamp, turn_id]   │
└────────────────────────────────────┬────────────────────────────────────┘
                                     │
┌────────────────────────────────────▼────────────────────────────────────┐
│ 4. 异步抽取与自进化 Worker (Async Background Learner)                    │
│    • 协议解析器 (Protocol Extractor): 捕获 <memory> 标签与自由语义事实   │
│    • 错误与轨迹扫描器 (Incident Scanner): 自动提取 Agent 避坑规则         │
│    • 自动合并 (Auto-Deduplication & Merge): 相似度 > 90% 自动合并归一     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、 核心模块与数据协议设计

### 3.1 开放式记忆数据模型 (Memory Schema)

```json
{
  "mem_id": "mem_f4a9b21c",
  "scope": "USER",                  // USER | PROJECT | SESSION
  "entity": "User",                 // 主体实体: User | PiAgent | Python3.12 | ...
  "relation": "prefers",            // 自由谓词: prefers | uses | works_on | requires | ...
  "target": "pi-agent with pi-web", // 关联客体或属性
  "entity_type": "preference",      // preference | technology | workflow | constraint | fact
  "desc": "User uses pi agent as the primary agent harness and pi-web as UI",
  "provenance": {
    "source_agent": "pi-agent",
    "project_id": "CtxGuard",
    "session_id": "sess_89a1c2",
    "timestamp": "2025-02-15T15:30:00Z"
  },
  "status": "active",               // active | superseded | deprecated
  "superseded_by": null,            // 指向覆盖此条记忆的新 mem_id
  "access_count": 12,
  "last_accessed_at": "2025-02-15T16:00:00Z"
}
```

### 3.2 提取协议支持（双向兼容）

1. **兼容标准协议格式**：
   - 添加新记忆：`<memory>{"op": "add", "entity": "...", "relation": "...", "target": "...", "entity_type": "...", "desc": "..."}</memory>`
   - 覆盖/更新旧记忆：`<memory>{"op": "supersede", "mem_id": "mem_xxxx", "target": "...", "desc": "..."}</memory>`
2. **容错与自然语言泛化**：
   - 支持自由谓词（如 `uses`、`operates_on`、`develops_with` 等不在硬编码白名单中的自然动词，系统自动归一化而非丢弃）；
   - 网关层拦截并在转发给用户前自动剥离 `<memory>` 标签（保持前端输出干净无噪音）。

---

## 四、 关键技术特性与落地路径

### 4.1 缓存友好型注入 (Cache-Safe Injection)
动态记忆如果直接拼接在最前端，会使每一轮对话的 Prompt Cache 头部哈希变动。
- **解法**：
  1. 系统提示词（System Prompt）头部与静态工具定义保持 100% 绝对冻结；
  2. 记忆块注入在**系统预设的动态锚点区（Dynamic Injection Zone）**，或以伪 User Turn 上下文形式注入在历史会话的特定分界线；
  3. 经过 `RawByteOverlayGuard` 校验，保证未被触碰的历史前缀字节流 SHA-256 零漂移。

### 4.2 跨 Agent 共享与溯源 (Cross-Agent Sharing)
- 当用户在命令行通过 `pi-agent` 配置了技术栈偏好（如“优先使用 pytest 和异步模式”），CtxGuard 会自动记录 `source_agent: "pi-agent"`；
- 后续用户在 `pi-web` 或 `Cursor` 中发起请求时，网关自动将该记忆注入，并在控制面板的可视化图谱中标注来源。

### 4.3 记忆可视化与控制面板联动 (`:8787/dashboard`)
- **Memory Timeline**：按时序展示记忆的新增、覆盖与调用命中热度；
- **Knowledge Graph View**：以节点和边展示实体关系网（如 `User ──[prefers]──> pi agent ──[frontend]──> pi-web`）；
- **Manual Overwrite / Edit**：支持用户在 Web 页面上手动修正、删除或新增记忆。

---

## 五、 实施计划

1. **第一阶段 (底层存储与检索升级)**：
   - 改造 `ctxguard/storage/repository_memory.py`，支持开放式谓词、四级 Scope 与 Supersede 时序版本链。
2. **第二阶段 (网关异步提取与清洗)**：
   - 在 `ctxguard/proxy/router.py` 的 Response 流水线中挂载异步 Memory Extractor，自动提取并剥离 `<memory>` 标签。
3. **第三阶段 (前缀缓存安全注入)**：
   - 在 `CacheGuard` / `pipeline.py` 中实现安全的记忆注入槽位，维持 Prompt Cache 零漂移。
4. **第四阶段 (Web Dashboard 知识图谱展示)**：
   - 在 Web 控制面板中升级沉淀记忆列表与 Force Graph 拓扑关系图。

---

## 六、 架构深度解析：事实记忆 (Memory) vs 避坑规则 (Learned Rules)

在工业级设计（如 Headroom、Mem0、Letta）中，必须严格区分 **事实记忆** 与 **避坑规则**，两者在触发时机、上下文处理与落库机制上完全不同：

### 6.1 核心对比矩阵

| 维度 |  事实记忆 (Memory) |  避坑规则 (Learned Rules) |
| :--- | :--- | :--- |
| **本质定义** | **静态客观事实 & 用户偏好**（“是什么”） | **动态行为约束 & 踩坑指南**（“怎么做 / 禁止怎么做”） |
| **提取时机** | **在线对话时**（通过 `memory_save` / 流量轻量启发式顺便带回） | **离线复盘时**（任务结束后分析 Digest 摘要） |
| **单次 LLM 成本** | **0 额外 LLM 调用**（单轮对话 Tool Call 顺便完成） | **全局仅调用 1 次独立 LLM**（跨会话批处理分析） |
| **典型内容** | • *用户的开发环境是 macOS*<br>• *用户的主力 Agent 是 pi agent + pi-web*<br>• *后端口令库采用 JWT* | • *运行 Python 命令必须加 `uv run`（否则报 ModuleNotFound）*<br>• *读配置文件时不要读 `src/`，去 `config/` 读*<br>• *修改 500 行以上文件禁止全量 write* |
| **存放形式** | **本地数据库 / 知识图谱**（`.ctxguard.db` / `memory.db`） | **项目规则文件**（`.cursorrules` / `CLAUDE.local.md` / `AGENTS.md`） |
| **生效机制** | 根据用户提问**动态召回 Top-K** 注入到当前轮 User 消息尾部 | 作为 **System/Project 上下文常驻**，严格规范 Agent 行为 |

### 6.2 离线复盘提取机制与 Digest Builder 预算控制

离线会话结算（`ctxguard learn`）**绝不会把数十万 Token 的完整原始聊天流水账塞给大模型**，而是经过严格的 Digest 压缩流水线：

1. **触发时机**：
   - 开发者显式执行 `ctxguard learn --apply`；
   - 会话结束 / 任务完成归档时；
   - 捕获到重大死循环（10+ 次重复工具失败）后在后台异步触发。
2. **Digest Builder 压缩流水线**：
   - 剔除成功读取的纯文本大文件内容；
   - 严格保留全部工具报错（Error Outputs）、用户纠错指令与打断；
   - 提取「失败  探索  成功」的关键因果转折点（Pivot Pairs）；
   - 将输入严格约束在 Token 预算以内（默认 80,000 Token，超限自动减半至 40,000 Token）。
3. **幂等写入与标记隔离**：
   - 使用标准边界标记 `<!-- ctxguard:learn:start -->` ... `<!-- ctxguard:learn:end -->`；
   - 每次分析重新运行时完全替换标记块，保证绝不重复膨胀，绝不覆盖开发者的手动配置。
