# CtxGuard 极简使用与配置说明指南

CtxGuard 是一个运行在本地的**智能上下文治理与 Prompt Cache 防抖网关**。通过将客户端的 API 地址指向本地网关，即可无感享受 **40%~80% 的 Token 压缩、物理级缓存防抖与跨会话自进化记忆**。

---

## 核心架构与请求流向

```text
┌──────────────────────────┐
│  客户端 (IDE / Agent)    │ (Cursor, Claude Code, Pi Agent, Chatbox 等)
└────────────┬─────────────┘
             │ (Base URL: http://127.0.0.1:8787/v1)
             ▼
┌──────────────────────────┐
│  CtxGuard 代理网关       │ • 消除 ANSI 乱码、折叠 Git Diff 与冗长堆栈
│  (本地 8787 端口)        │ • 规范化 Tool Schema，锁定 Prompt Cache
└────────────┬─────────────┘
             │ (自动透传 API Key 与转发)
             ▼
┌──────────────────────────┐
│  云端模型 / 第三方中转站  │ (OpenAI, Anthropic, DeepSeek, One API / New API)
└──────────────────────────┘
```

---

## 第一步：配置上游服务地址 (`ctxguard.yaml`)

打开项目根目录下的 `ctxguard.yaml`，配置你要转发的真实模型服务商或中转站地址：

```yaml
server:
  host: "127.0.0.1"
  port: 8787

upstream:
  default_provider: "openai"
  providers:
    # 1. 如果使用 OpenAI 官方或第三方中转站 (One API / New API)
    openai:
      base_url: "https://你的中转站域名/v1"   # 官方默认为: https://api.openai.com
      api_key_env: "OPENAI_API_KEY"

    # 2. 如果使用 DeepSeek 官方
    deepseek:
      base_url: "https://api.deepseek.com"
      api_key_env: "DEEPSEEK_API_KEY"

    # 3. 如果使用 Anthropic 官方
    anthropic:
      base_url: "https://api.anthropic.com"
      api_key_env: "ANTHROPIC_API_KEY"
```

---

## 第二步：启动 CtxGuard 网关服务

在终端中执行以下命令启动本地网关：

```bash
# 启动本地代理服务 (默认端口 8787)
python3 -m ctxguard.cli.main start --port 8787
```

- **控制面板访问**：浏览器打开 `http://127.0.0.1:8787/dashboard`
- **健康检查接口**：`http://127.0.0.1:8787/health`

---

## 第三步：客户端一键接入

### 场景 1：终端类 Agent (Claude Code / Pi Agent)
在当前终端执行一键环境注入：
```bash
eval $(python3 -m ctxguard.cli.main env --eval)
```
随后直接运行 `claude` 或 `pi` 即可自动走网关代理。

### 场景 2：图形客户端 / IDE (Cursor, VSCode, Chatbox, NextChat)
在客户端的设置面板中配置：
- **API Base URL / 接口地址**：`http://127.0.0.1:8787/v1`
- **API Key / 密钥**：填写你平时使用的 API Key（中转站 Key 或官方 Key）
- **Model / 模型**：正常选择 `gpt-4o`, `gpt-5.6`, `claude-3-7-sonnet`, `deepseek-v3` 等

---

## 常用 CLI 运维命令

```bash
# 查看实时优化看板与最近请求流水
python3 -m ctxguard.cli.main stats

# 查看长期累积省钱账本与进度条分析
python3 -m ctxguard.cli.main savings

# 手动触发历史会话自进化与避坑规则提取
python3 -m ctxguard.cli.main learn --apply
```
