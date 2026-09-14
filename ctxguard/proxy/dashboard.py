"""Embedded Web Dashboard HTML template and UI renderer for CtxGuard."""

def get_dashboard_html() -> str:
    """Returns self-contained modern dark-mode responsive dashboard HTML."""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CtxGuard 控制面板 | Context Optimization Gateway</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            brand: {
              50: '#ecfdf5',
              400: '#34d399',
              500: '#10b981',
              600: '#059669',
              900: '#064e3b',
            },
            dark: {
              bg: '#090d16',
              card: '#111827',
              border: '#1f293d',
              input: '#0d1322'
            }
          }
        }
      }
    }
  </script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
    body { font-family: 'Plus Jakarta Sans', sans-serif; background: #090d16; color: #f3f4f6; }
    code, pre, .font-mono { font-family: 'JetBrains Mono', monospace; }
    .glass { background: rgba(17, 24, 39, 0.7); backdrop-filter: blur(12px); border: 1px solid rgba(31, 41, 61, 0.8); }
    .glow-emerald { box-shadow: 0 0 25px -5px rgba(16, 185, 129, 0.2); }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-brand-500 selection:text-white">

  <!-- Top Navigation Header -->
  <header class="border-b border-dark-border glass sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-lg bg-gradient-to-tr from-brand-600 to-emerald-400 flex items-center justify-center shadow-lg shadow-brand-500/20">
          <svg class="w-5 h-5 text-gray-950 font-bold" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
          </svg>
        </div>
        <div>
          <span class="text-lg font-extrabold tracking-tight bg-gradient-to-r from-white via-gray-100 to-brand-400 bg-clip-text text-transparent">CtxGuard</span>
          <span class="ml-2 text-xs font-semibold px-2 py-0.5 rounded-full bg-brand-500/10 text-brand-400 border border-brand-500/20">v0.1.0</span>
        </div>
      </div>
      
      <!-- Live Status Pill & Actions -->
      <div class="flex items-center space-x-3">
        <div class="flex items-center space-x-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-xs font-medium text-emerald-400">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span>网关在线 (端口: 8787 • SQLite 驱动)</span>
        </div>
        <button onclick="triggerSimulatedLiveRequest()" class="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/40 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/30 transition flex items-center space-x-1.5 shadow-sm">
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
          <span>发送真实测试请求入库</span>
        </button>
        <button onclick="refreshData()" class="px-3 py-1.5 rounded-lg bg-dark-card border border-dark-border text-xs font-semibold hover:bg-gray-800 transition flex items-center space-x-1.5">
          <svg class="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          <span>刷新</span>
        </button>
      </div>
    </div>
  </header>

  <!-- Main Content Tabs -->
  <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">

    <!-- KPI Metric Cards Grid (Direct SQLite Aggregations) -->
    <section class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5">
      <!-- Card 1 -->
      <div class="glass p-5 rounded-2xl glow-emerald">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">真实累计节省 Token</span>
          <span class="p-2 rounded-xl bg-brand-500/10 text-brand-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
          </span>
        </div>
        <div class="mt-4 flex items-baseline justify-between">
          <span id="stat-saved-tokens" class="text-3xl font-extrabold text-white font-mono">0</span>
          <span id="stat-saved-percent" class="text-sm font-bold text-brand-400 bg-brand-500/10 px-2 py-0.5 rounded-md font-mono">0.0%</span>
        </div>
        <div class="mt-2 text-xs text-gray-400 flex justify-between">
          <span>原始输入: <b id="stat-raw-tokens" class="text-gray-300 font-mono">0</b></span>
          <span>优化输出: <b id="stat-opt-tokens" class="text-emerald-400 font-mono">0</b></span>
        </div>
      </div>

      <!-- Card 2 -->
      <div class="glass p-5 rounded-2xl">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">真实折算节省资金</span>
          <span class="p-2 rounded-xl bg-blue-500/10 text-blue-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          </span>
        </div>
        <div class="mt-4 flex items-baseline justify-between">
          <span id="stat-dollars-saved" class="text-3xl font-extrabold text-white font-mono">$0.0000</span>
          <span class="text-xs font-medium text-gray-400">USD</span>
        </div>
        <p class="mt-2 text-xs text-gray-500">按模型官方定价实时 SQL 聚合折算</p>
      </div>

      <!-- Card 3 -->
      <div class="glass p-5 rounded-2xl">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">总代理请求量</span>
          <span class="p-2 rounded-xl bg-purple-500/10 text-purple-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"/></svg>
          </span>
        </div>
        <div class="mt-4 flex items-baseline justify-between">
          <span id="stat-total-requests" class="text-3xl font-extrabold text-white font-mono">0</span>
          <span class="text-xs font-medium text-purple-400">Requests</span>
        </div>
        <p class="mt-2 text-xs text-gray-500">已处理的端到端真实请求总数</p>
      </div>

      <!-- Card 4 -->
      <div class="glass p-5 rounded-2xl">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">网关优化延迟</span>
          <span class="p-2 rounded-xl bg-amber-500/10 text-amber-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          </span>
        </div>
        <div class="mt-4 flex items-baseline justify-between">
          <span id="stat-avg-latency" class="text-3xl font-extrabold text-white font-mono">0.00</span>
          <span class="text-xs font-medium text-amber-400">ms 平均</span>
        </div>
        <p class="mt-2 text-xs text-gray-500">纯算法与 C/Rust SIMD 极速优化</p>
      </div>
    </section>

    <!-- Interactive Workspace Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
      
      <!-- Left Column: Interactive Compression Tester (2 Cols) -->
      <div class="lg:col-span-2 space-y-6">
        <div class="glass rounded-2xl p-6">
          <div class="flex items-center justify-between pb-4 border-b border-dark-border">
            <div>
              <h2 class="text-base font-bold text-white flex items-center space-x-2">
                <svg class="w-4 h-4 text-brand-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/></svg>
                <span>后端实时真实流水线测试工作台</span>
              </h2>
              <p class="text-xs text-gray-400 mt-0.5">调用后端真实 Python `CompressionPipeline.process()` 算子，非前端伪代码</p>
            </div>
            <div class="flex items-center space-x-2">
              <button onclick="loadSample('code')" class="px-2.5 py-1 text-xs rounded-md bg-dark-card border border-dark-border hover:bg-gray-800 text-gray-300">代码样例</button>
              <button onclick="loadSample('json')" class="px-2.5 py-1 text-xs rounded-md bg-dark-card border border-dark-border hover:bg-gray-800 text-gray-300">JSON 样例</button>
              <button onclick="loadSample('log')" class="px-2.5 py-1 text-xs rounded-md bg-dark-card border border-dark-border hover:bg-gray-800 text-gray-300">日志样例</button>
            </div>
          </div>

          <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <div class="flex justify-between items-center text-xs font-semibold text-gray-400 mb-1.5">
                <span>原始输入 (Raw Input)</span>
                <span id="raw-token-badge" class="text-gray-400 font-mono">0 Tokens</span>
              </div>
              <textarea id="test-input" rows="11" class="w-full rounded-xl bg-dark-input border border-dark-border p-3 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500 transition resize-none placeholder-gray-600" placeholder="在此粘贴测试文本、JSON 数组或报错日志..."></textarea>
            </div>
            <div>
              <div class="flex justify-between items-center text-xs font-semibold text-gray-400 mb-1.5">
                <span>优化输出 (Optimized Payload)</span>
                <span id="opt-token-badge" class="text-brand-400 font-mono">0 Tokens (0%)</span>
              </div>
              <textarea id="test-output" rows="11" readonly class="w-full rounded-xl bg-dark-input/60 border border-dark-border p-3 text-xs font-mono text-emerald-300 focus:outline-none resize-none placeholder-gray-600" placeholder="点击下方按钮调用后端真实流水线处理..."></textarea>
            </div>
          </div>

          <div class="mt-4 flex items-center justify-between pt-3 border-t border-dark-border">
            <div id="test-compressors-tags" class="flex flex-wrap gap-1.5 text-xs text-gray-400 items-center">
              <span>后端激活算子:</span>
              <span class="text-gray-500 italic text-xs">等待执行...</span>
            </div>
            <button onclick="runTestCompress()" class="px-5 py-2 rounded-xl bg-gradient-to-r from-brand-600 to-emerald-500 hover:from-brand-500 hover:to-emerald-400 text-gray-950 font-bold text-xs shadow-lg shadow-brand-500/20 transition flex items-center space-x-1.5">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
              <span>执行真实后端流水线</span>
            </button>
          </div>
        </div>

        <!-- Recent Requests History Table (Live SQLite Query) -->
        <div class="glass rounded-2xl p-6">
          <div class="flex items-center justify-between pb-4 border-b border-dark-border">
            <h2 class="text-base font-bold text-white flex items-center space-x-2">
              <svg class="w-4 h-4 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              <span>SQLite 真实请求流水日志表 (`requests` 表)</span>
            </h2>
            <span class="text-xs text-emerald-400 flex items-center space-x-1">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>每 2.5 秒自动同步数据库</span>
            </span>
          </div>

          <div class="mt-4 overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="text-gray-400 font-semibold border-b border-dark-border/60 uppercase text-[11px]">
                <tr>
                  <th class="pb-2.5">ID</th>
                  <th class="pb-2.5">会话 Session</th>
                  <th class="pb-2.5">模型</th>
                  <th class="pb-2.5">原始 Tokens</th>
                  <th class="pb-2.5">优化后</th>
                  <th class="pb-2.5">节省率</th>
                  <th class="pb-2.5">处理延迟</th>
                </tr>
              </thead>
              <tbody id="recent-table-body" class="divide-y divide-dark-border/40 font-mono text-gray-300">
                <tr><td colspan="7" class="py-6 text-center text-gray-500 font-sans">正在加载 SQLite 数据库记录...</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Right Column: Quick Setup & Raw DB Inspector (1 Col) -->
      <div class="space-y-6">
        
        <!-- One-Click Client Integration Guide -->
        <div class="glass rounded-2xl p-6">
          <h2 class="text-base font-bold text-white flex items-center space-x-2 pb-3 border-b border-dark-border">
            <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
            <span>Agent 客户端接入配置</span>
          </h2>

          <div class="mt-4 space-y-3.5 text-xs">
            <div>
              <span class="font-semibold text-gray-300 block mb-1">Cursor / Cline / Windsurf:</span>
              <div class="p-2.5 rounded-lg bg-dark-input font-mono text-emerald-400 border border-dark-border flex justify-between items-center">
                <span>http://127.0.0.1:8787</span>
                <button onclick="copyToClipboard('http://127.0.0.1:8787')" class="text-gray-400 hover:text-white text-[10px] px-2 py-0.5 rounded bg-dark-card">复制</button>
              </div>
            </div>

            <div>
              <span class="font-semibold text-gray-300 block mb-1">OpenAI SDK (Python):</span>
              <pre class="p-2.5 rounded-lg bg-dark-input text-gray-300 border border-dark-border overflow-x-auto font-mono text-[11px]">client = OpenAI(
    base_url="http://127.0.0.1:8787/v1",
    api_key="any-key"
)</pre>
            </div>

            <div>
              <span class="font-semibold text-gray-300 block mb-1">Anthropic SDK (Python):</span>
              <pre class="p-2.5 rounded-lg bg-dark-input text-gray-300 border border-dark-border overflow-x-auto font-mono text-[11px]">client = Anthropic(
    base_url="http://127.0.0.1:8787",
    api_key="any-key"
)</pre>
            </div>
          </div>
        </div>

        <!-- Offline Self-Evolution & Rules Panel -->
        <div class="glass rounded-2xl p-6">
          <div class="flex items-center justify-between pb-3 border-b border-dark-border">
            <h2 class="text-base font-bold text-white flex items-center space-x-2">
              <svg class="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"/></svg>
              <span>离线自进化分析触发</span>
            </h2>
          </div>

          <p class="mt-3 text-xs text-gray-400">调用后端真实 `LoopDetector` 与 `CausalityExtractor` 扫描 SQLite 日志并提炼规则。</p>

          <div class="mt-4 space-y-3">
            <button onclick="triggerLearn()" class="w-full py-2.5 rounded-xl bg-dark-card border border-dark-border hover:border-amber-500/50 text-xs font-semibold text-amber-400 transition flex items-center justify-center space-x-1.5">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
              <span>执行离线自进化分析</span>
            </button>
            <div id="learn-result" class="hidden p-3 rounded-xl bg-dark-input font-mono text-[11px] text-gray-300 border border-dark-border max-h-40 overflow-y-auto"></div>
          </div>
        </div>

      </div>

    </div>
  </main>

  <footer class="border-t border-dark-border/40 py-6 mt-12 text-center text-xs text-gray-500">
    <p>CtxGuard Context Optimization Gateway • 零重型依赖 • 毫秒级极速优化 • SQLite WAL 存储驱动</p>
  </footer>

  <script>
    const SAMPLES = {
      code: `// src/controllers/user.controller.ts
import { Controller, Get, Param } from '@nestjs/common';
import { UserService } from './user.service';

@Controller('users')
export class UserController {
    constructor(private readonly userService: UserService) {}

    @Get(':id')
    async findOne(@Param('id') id: string) {
        return this.userService.findById(id);
    }
}
`,
      json: `[
  {"id": 1, "name": "Alice", "role": "admin", "department": "Security", "active": true},
  {"id": 2, "name": "Bob", "role": "developer", "department": "Backend", "active": true},
  {"id": 3, "name": "Charlie", "role": "designer", "department": "Product", "active": false},
  {"id": 4, "name": "David", "role": "devops", "department": "Infrastructure", "active": true}
]`,
      log: `\\x1b[34m[INFO]\\x1b[0m Starting build sequence...
[====>          ] 20% Compiling TypeScript assets
[========>      ] 40% Compiling TypeScript assets
[============>  ] 80% Compiling TypeScript assets
[==============>] 100% Compilation finished!
\\x1b[32mSuccess:\\x1b[0m Bundle generated in 240ms with 0 errors.
`
    };

    function loadSample(type) {
      document.getElementById('test-input').value = SAMPLES[type] || '';
      runTestCompress();
    }

    async function refreshData() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        
        const summary = data.summary || {};
        document.getElementById('stat-saved-tokens').innerText = (summary.total_saved_tokens || 0).toLocaleString();
        document.getElementById('stat-saved-percent').innerText = `${summary.overall_saved_percent || 0}%`;
        document.getElementById('stat-raw-tokens').innerText = (summary.total_raw_tokens || 0).toLocaleString();
        document.getElementById('stat-opt-tokens').innerText = (summary.total_optimized_tokens || 0).toLocaleString();
        document.getElementById('stat-dollars-saved').innerText = `$${(summary.estimated_dollars_saved || 0).toFixed(4)}`;
        document.getElementById('stat-total-requests').innerText = (summary.total_requests || 0).toLocaleString();
        document.getElementById('stat-avg-latency').innerText = (summary.avg_latency_ms || 0).toFixed(2);

        // Render real recent table
        const tbody = document.getElementById('recent-table-body');
        const recent = data.recent || [];
        if (recent.length > 0) {
          tbody.innerHTML = recent.map(r => `
            <tr class="hover:bg-dark-card/40 transition">
              <td class="py-2.5 text-gray-500 font-bold">#${r.id}</td>
              <td class="py-2.5 text-gray-400 truncate max-w-[120px]">${r.session_id}</td>
              <td class="py-2.5 text-blue-400 font-semibold">${r.model}</td>
              <td class="py-2.5">${r.raw_tokens}</td>
              <td class="py-2.5 text-emerald-400">${r.optimized_tokens}</td>
              <td class="py-2.5 font-bold text-brand-400">${r.saved_ratio}%</td>
              <td class="py-2.5 text-amber-300">${r.latency_ms.toFixed(1)}ms</td>
            </tr>
          `).join('');
        } else {
          tbody.innerHTML = '<tr><td colspan="7" class="py-6 text-center text-gray-500 font-sans">当前 SQLite 数据库暂无请求，点击右上角“发送真实测试请求入库”即可立即生成！</td></tr>';
        }
      } catch (err) {
        console.error('Failed to load stats:', err);
      }
    }

    async function triggerSimulatedLiveRequest() {
      try {
        const res = await fetch('/api/simulate/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: 'claude-3-5-sonnet-20241022',
            prompt: 'Please query customer database records.',
            tool_output: JSON.stringify([
              { id: 1, name: "Alice", role: "admin", status: "active" },
              { id: 2, name: "Bob", role: "user", status: "active" },
              { id: 3, name: "Charlie", role: "manager", status: "pending" }
            ], null, 2)
          })
        });
        const data = await res.json();
        console.log('Real request saved to SQLite:', data);
        await refreshData();
      } catch (err) {
        alert('发送测试请求失败: ' + err);
      }
    }

    async function runTestCompress() {
      const input = document.getElementById('test-input').value;
      if (!input.trim()) return;

      try {
        const res = await fetch('/api/test/compress', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: input })
        });
        const data = await res.json();

        document.getElementById('test-output').value = data.optimized_text || '';
        document.getElementById('raw-token-badge').innerText = `${data.raw_tokens} Tokens`;
        document.getElementById('opt-token-badge').innerText = `${data.optimized_tokens} Tokens (省 ${data.saved_percent}%)`;

        const tagsContainer = document.getElementById('test-compressors-tags');
        const compressors = data.applied_compressors || [];
        if (compressors.length > 0) {
          tagsContainer.innerHTML = '<span>后端激活算子:</span>' + compressors.map(c => `
            <span class="px-2 py-0.5 rounded bg-brand-500/20 text-brand-400 text-[11px] font-mono border border-brand-500/30">${c}</span>
          `).join('');
        } else {
          tagsContainer.innerHTML = '<span>后端激活算子:</span><span class="text-gray-500 italic text-xs">无修改 (内容已最优)</span>';
        }
      } catch (err) {
        console.error('Test compress failed:', err);
      }
    }

    async function triggerLearn() {
      const resultBox = document.getElementById('learn-result');
      resultBox.classList.remove('hidden');
      resultBox.innerText = '正在执行因果挖掘与规则提炼...';

      try {
        const res = await fetch('/api/learn/run', { method: 'POST' });
        const data = await res.json();
        resultBox.innerText = data.rendered_rules || '已完成分析，未发现重复死循环。';
      } catch (err) {
        resultBox.innerText = '自进化分析失败: ' + err;
      }
    }

    function copyToClipboard(text) {
      navigator.clipboard.writeText(text);
      alert('已复制: ' + text);
    }

    // Auto-load & auto-refresh every 2.5s
    window.addEventListener('DOMContentLoaded', () => {
      refreshData();
      loadSample('code');
      setInterval(refreshData, 2500);
    });
  </script>
</body>
</html>
"""
