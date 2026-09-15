"""Embedded Web Dashboard HTML template and UI renderer for CtxGuard."""

def get_dashboard_html() -> str:
    """Returns self-contained modern dark-mode responsive dashboard HTML with Session/Project/Model classification and Memory Hub."""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CtxGuard 控制面板 | Context Optimization & Memory Gateway</title>
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
    .glow-purple { box-shadow: 0 0 25px -5px rgba(168, 85, 247, 0.2); }
  </style>
</head>
<body class="min-h-screen flex flex-col antialiased selection:bg-brand-500 selection:text-white">

  <!-- Top Navigation Header -->
  <header class="border-b border-dark-border glass sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-lg bg-gradient-to-tr from-brand-600 to-emerald-400 flex items-center justify-center shadow-lg shadow-brand-500/20 font-extrabold text-gray-950">
          CG
        </div>
        <div>
          <span class="text-lg font-extrabold tracking-tight bg-gradient-to-r from-white via-gray-100 to-brand-400 bg-clip-text text-transparent">CtxGuard 控制面板</span>
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
          <span>发送测试请求入库</span>
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
        <p class="mt-2 text-xs text-gray-500">平均处理耗时: <b id="stat-avg-latency" class="text-purple-300 font-mono">0.00</b> ms</p>
      </div>

      <!-- Card 4 (Memory & Storage) -->
      <div class="glass p-5 rounded-2xl glow-purple">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold uppercase tracking-wider text-gray-400">🧠 持久化记忆指纹库</span>
          <span class="p-2 rounded-xl bg-purple-500/10 text-purple-400">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
          </span>
        </div>
        <div class="mt-4 flex items-baseline justify-between">
          <span id="stat-memory-count" class="text-3xl font-extrabold text-purple-300 font-mono">0</span>
          <span id="stat-memory-chars" class="text-xs font-semibold text-purple-400 bg-purple-500/10 px-2 py-0.5 rounded-md font-mono">0 Chars</span>
        </div>
        <p class="mt-2 text-xs text-gray-500">跨会话内容指纹记忆与自进化知识库</p>
      </div>
    </section>

    <!-- SECTION 1: Classification & Multi-Dimension Filter Console -->
    <section class="glass rounded-2xl p-6 space-y-5">
      
      <!-- Top Row: Section Header & View Mode Switcher -->
      <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-4 pb-4 border-b border-dark-border">
        <div>
          <h2 class="text-base font-bold text-white flex items-center space-x-2">
            <svg class="w-5 h-5 text-brand-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
            <span>对话会话窗口分类与多维流控监控</span>
          </h2>
          <p class="text-xs text-gray-400 mt-1">按对话会话窗口（Session）、归属项目（Project）及调用模型（Model）实时聚合与分类</p>
        </div>

        <!-- View Mode Switcher -->
        <div class="flex items-center bg-dark-input p-1 rounded-xl border border-dark-border space-x-1 text-xs self-start lg:self-auto">
          <button id="btn-view-flat" onclick="setViewMode('flat')" class="px-3.5 py-1.5 rounded-lg font-semibold transition flex items-center space-x-1.5 bg-brand-500/20 text-brand-300 border border-brand-500/30 shadow-sm">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>
            <span>单次请求明细流水</span>
          </button>
          <button id="btn-view-session" onclick="setViewMode('session')" class="px-3.5 py-1.5 rounded-lg font-semibold transition flex items-center space-x-1.5 text-gray-400 hover:text-gray-200">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z"/></svg>
            <span>按对话窗口聚合视图</span>
          </button>
        </div>
      </div>

      <!-- Filter Controls Bar -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <!-- Project Filter -->
        <div class="space-y-1">
          <label class="text-[11px] font-semibold text-gray-400 flex items-center space-x-1">
            <svg class="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
            <span>按项目分类 (Project)</span>
          </label>
          <select id="filter-project" onchange="applyFilters()" class="w-full bg-dark-input border border-dark-border rounded-xl px-3 py-2 text-xs font-mono text-emerald-300 focus:outline-none focus:border-brand-500 transition">
            <option value="ALL">全部项目 (All Projects)</option>
          </select>
        </div>

        <!-- Model Filter -->
        <div class="space-y-1">
          <label class="text-[11px] font-semibold text-gray-400 flex items-center space-x-1">
            <svg class="w-3.5 h-3.5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/></svg>
            <span>按模型分类 (Model)</span>
          </label>
          <select id="filter-model" onchange="applyFilters()" class="w-full bg-dark-input border border-dark-border rounded-xl px-3 py-2 text-xs font-mono text-blue-300 focus:outline-none focus:border-brand-500 transition">
            <option value="ALL">全部模型 (All Models)</option>
          </select>
        </div>

        <!-- Keyword / Session Search -->
        <div class="space-y-1">
          <label class="text-[11px] font-semibold text-gray-400 flex items-center space-x-1">
            <svg class="w-3.5 h-3.5 text-purple-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
            <span>搜索会话 ID / 提问内容</span>
          </label>
          <div class="relative">
            <input id="filter-search" oninput="applyFilters()" type="text" placeholder="输入会话 ID 或提问关键字过滤..." class="w-full bg-dark-input border border-dark-border rounded-xl pl-3 pr-8 py-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500 transition placeholder-gray-600">
            <button onclick="clearSearch()" class="absolute right-2.5 top-2.5 text-gray-500 hover:text-gray-300 text-xs">✕</button>
          </div>
        </div>
      </div>

      <!-- Quick Distribution Badges (Projects & Models) -->
      <div class="pt-2 border-t border-dark-border/60 flex flex-wrap items-center gap-2 text-xs">
        <span class="text-gray-500 text-[11px]">快捷分布:</span>
        <div id="project-badges-container" class="flex flex-wrap gap-1.5 items-center"></div>
        <div class="h-3.5 w-px bg-dark-border mx-1"></div>
        <div id="model-badges-container" class="flex flex-wrap gap-1.5 items-center"></div>
      </div>

      <!-- Active Filter Reset Pill -->
      <div id="active-filter-bar" class="hidden flex items-center justify-between p-2.5 rounded-xl bg-brand-500/10 border border-brand-500/20 text-xs text-brand-300">
        <span id="active-filter-text">当前已筛选: </span>
        <button onclick="resetAllFilters()" class="text-[11px] underline hover:text-white font-semibold">重置所有筛选</button>
      </div>

      <!-- VIEW 1: Flat Stream Table View (Single Request Logs - Default) -->
      <div id="view-flat-container" class="overflow-x-auto">
        <div class="flex items-center justify-between text-xs text-gray-400 px-1 mb-2">
          <span>共找到 <b id="flat-count-badge" class="text-emerald-400 font-mono">0</b> 条请求记录</span>
          <span>点击任意记录行可查看压缩详情与命中的算子</span>
        </div>
        <table class="w-full text-left text-xs">
          <thead class="text-gray-400 font-semibold border-b border-dark-border/60 uppercase text-[11px]">
            <tr>
              <th class="pb-2.5">ID</th>
              <th class="pb-2.5">所属项目</th>
              <th class="pb-2.5">对话会话 ID</th>
              <th class="pb-2.5">提问摘要</th>
              <th class="pb-2.5">模型</th>
              <th class="pb-2.5">Token (原始 → 优化后)</th>
              <th class="pb-2.5">节省率</th>
              <th class="pb-2.5">耗时</th>
              <th class="pb-2.5">操作</th>
            </tr>
          </thead>
          <tbody id="recent-table-body" class="divide-y divide-dark-border/40 font-mono text-gray-300">
            <tr><td colspan="9" class="py-6 text-center text-gray-500 font-sans">正在加载 SQLite 数据库记录...</td></tr>
          </tbody>
        </table>
      </div>

      <!-- VIEW 2: Session Group View (Grouped by Conversation Window) -->
      <div id="view-session-container" class="hidden space-y-3.5">
        <div class="flex items-center justify-between text-xs text-gray-400 px-1">
          <span>共找到 <b id="session-count-badge" class="text-purple-400 font-mono">0</b> 个对话窗口会话</span>
          <span>点击会话卡片可展开该窗口内的各轮对话明细</span>
        </div>
        <div id="session-groups-list" class="space-y-3">
          <div class="py-8 text-center text-gray-500 text-xs">正在加载会话分类数据...</div>
        </div>
      </div>

    </section>

    <!-- SECTION 2: 🧠 记忆中枢与自进化规则大盘 (Dedicated Memory Hub) -->
    <section class="glass rounded-2xl p-6 space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-dark-border">
        <div>
          <h2 class="text-base font-bold text-white flex items-center space-x-2">
            <span class="p-1.5 rounded-lg bg-purple-500/20 text-purple-400">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
            </span>
            <span>🧠 CtxGuard 记忆中枢与自进化知识库 (Memory & Knowledge Hub)</span>
          </h2>
          <p class="text-xs text-gray-400 mt-1">包含两大层级记忆：跨会话大段代码/内容 SHA-256 指纹记忆库，以及从历史交互中自进化提炼的避坑经验规则库</p>
        </div>

        <div class="flex items-center space-x-2">
          <button onclick="triggerLearn()" class="px-3.5 py-1.5 rounded-xl bg-purple-500/20 border border-purple-500/40 text-xs font-semibold text-purple-300 hover:bg-purple-500/30 transition flex items-center space-x-1.5 shadow-sm">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            <span>一键触发自进化经验提炼</span>
          </button>
        </div>
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        
        <!-- Left: Fingerprint Content Memory Store -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-xs font-bold uppercase tracking-wider text-purple-400 flex items-center space-x-1.5">
              <span>📦 跨会话内容指纹记忆库 (`fingerprints`)</span>
            </h3>
            <span class="text-[11px] text-gray-400 font-mono">已持久化: <b id="memory-fp-count" class="text-emerald-400">0</b> 个块</span>
          </div>

          <div class="bg-dark-input rounded-xl border border-dark-border overflow-hidden">
            <div class="max-h-64 overflow-y-auto divide-y divide-dark-border/40 font-mono text-xs">
              <table class="w-full text-left">
                <thead class="text-gray-500 uppercase text-[10px] bg-dark-card/60 sticky top-0">
                  <tr>
                    <th class="p-2.5">指纹哈希 (Hash ID)</th>
                    <th class="p-2.5">长度</th>
                    <th class="p-2.5">所属会话</th>
                    <th class="p-2.5">记忆内容摘要</th>
                  </tr>
                </thead>
                <tbody id="memory-fp-tbody" class="text-gray-300">
                  <tr><td colspan="4" class="p-4 text-center text-gray-500 font-sans text-xs">暂无指纹记忆</td></tr>
                </tbody>
              </table>
            </div>
          </div>
          <p class="text-[11px] text-gray-500">当任意项目或会话再次出现相同内容时，网关直接通过指纹秒级 0-Token 复用。</p>
        </div>

        <!-- Right: Learned Evolution Rules & Incident Memory -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-xs font-bold uppercase tracking-wider text-amber-400 flex items-center space-x-1.5">
              <span>🛡️ 自进化避坑经验规则库 (Learned Rules)</span>
            </h3>
            <span class="text-[11px] text-gray-400 font-mono">已生效: <b id="memory-rule-count" class="text-amber-400">0</b> 条规则</span>
          </div>

          <div id="memory-rules-container" class="space-y-2.5 max-h-64 overflow-y-auto pr-1">
            <div class="p-4 text-center text-gray-500 text-xs">正在加载经验规则库...</div>
          </div>

          <div id="learn-result" class="hidden p-3 rounded-xl bg-dark-input font-mono text-[11px] text-gray-300 border border-dark-border max-h-32 overflow-y-auto"></div>
        </div>

      </div>
    </section>

    <!-- SECTION 3: 🕸️ 个人记忆知识图谱中枢 (Personal Knowledge Graph - SQLiteGraphStore) -->
    <section class="glass rounded-2xl p-6 space-y-6">
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-4 border-b border-dark-border">
        <div>
          <h2 class="text-base font-bold text-white flex items-center space-x-2">
            <span class="p-1.5 rounded-lg bg-emerald-500/20 text-emerald-400">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
            </span>
            <span>🕸️ 个人记忆知识图谱 (Personal Knowledge Graph)</span>
          </h2>
          <p class="text-xs text-gray-400 mt-1">基于 SQLite 单文件图引擎 (SQLiteGraphStore)，具备 BFS 2-hop 多跳拓扑检索能力，跨会话记忆个人偏好、技术栈与工程属性</p>
        </div>

        <div class="flex items-center space-x-3 text-xs">
          <span class="px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-mono">
            实体: <b id="kg-total-entities">0</b> | 关系边: <b id="kg-total-relations">0</b>
          </span>
          <button onclick="refreshGraphStats()" class="px-3 py-1.5 rounded-lg bg-dark-card border border-dark-border text-xs font-semibold hover:bg-gray-800 transition flex items-center space-x-1.5">
            <svg class="w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            <span>刷新图谱</span>
          </button>
        </div>
      </div>

      <!-- Graph Playground & Controls -->
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        <!-- Left: Interactive BFS Subgraph Query Explorer (2 cols) -->
        <div class="lg:col-span-2 space-y-4">
          <div class="p-4 rounded-xl bg-dark-input/80 border border-dark-border space-y-3">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <label class="text-xs font-bold text-gray-300 flex items-center space-x-1.5">
                <svg class="w-3.5 h-3.5 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/></svg>
                <span>BFS 2-hop 关系子图检索体验台</span>
              </label>
              <div class="flex gap-1.5">
                <button onclick="quickQueryGraph('User')" class="px-2 py-0.5 rounded bg-dark-card text-[11px] text-gray-300 border border-dark-border hover:bg-gray-800">查 User</button>
                <button onclick="quickQueryGraph('pnpm')" class="px-2 py-0.5 rounded bg-dark-card text-[11px] text-gray-300 border border-dark-border hover:bg-gray-800">查 pnpm</button>
                <button onclick="quickQueryGraph('Pi-Web')" class="px-2 py-0.5 rounded bg-dark-card text-[11px] text-gray-300 border border-dark-border hover:bg-gray-800">查 Pi-Web</button>
              </div>
            </div>

            <div class="flex gap-2">
              <input id="kg-search-input" onkeydown="if(event.key==='Enter') searchSubgraph()" type="text" placeholder="输入实体名或关键词 (如: User, pnpm, macOS, Pi-Web)..." class="flex-1 bg-dark-bg border border-dark-border rounded-xl px-3 py-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500 transition">
              <button onclick="searchSubgraph()" class="px-4 py-2 rounded-xl bg-emerald-500/20 border border-emerald-500/40 text-xs font-semibold text-emerald-300 hover:bg-emerald-500/30 transition flex items-center space-x-1.5 shadow-sm shrink-0">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
                <span>检索 2-hop 子图</span>
              </button>
            </div>

            <!-- Subgraph Visual Result Box -->
            <div id="kg-query-result" class="p-3.5 rounded-xl bg-dark-bg/90 border border-dark-border min-h-[110px] font-mono text-xs space-y-2">
              <div class="text-gray-500 text-center py-6">在上方输入实体或点击快捷标签，体验 BFS 多跳关联拓扑检索与 Prompt 注入预览</div>
            </div>
          </div>

          <!-- Entity List Table -->
          <div class="bg-dark-input rounded-xl border border-dark-border overflow-hidden">
            <div class="p-3 bg-dark-card/60 border-b border-dark-border flex items-center justify-between">
              <span class="text-xs font-bold text-gray-300">已收录的个人记忆实体清单</span>
              <div id="kg-type-badges" class="flex flex-wrap gap-1"></div>
            </div>
            <div class="max-h-56 overflow-y-auto">
              <table class="w-full text-left text-xs font-mono">
                <thead class="text-gray-500 uppercase text-[10px] bg-dark-card/40 sticky top-0">
                  <tr>
                    <th class="p-2.5">实体名称</th>
                    <th class="p-2.5">类别</th>
                    <th class="p-2.5">描述信息</th>
                    <th class="p-2.5 text-right">操作</th>
                  </tr>
                </thead>
                <tbody id="kg-entities-tbody" class="divide-y divide-dark-border/40 text-gray-300">
                  <tr><td colspan="4" class="p-4 text-center text-gray-500 font-sans text-xs">正在加载知识图谱实体...</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- Right: Manual Memory & Relation Quick-Add Form (1 col) -->
        <div class="space-y-4">
          <div class="p-4 rounded-xl bg-dark-input/80 border border-dark-border space-y-3 text-xs">
            <div class="font-bold text-gray-200 flex items-center space-x-1.5 pb-2 border-b border-dark-border/60">
              <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
              <span>手动添加个人偏好与关系</span>
            </div>

            <div class="space-y-1">
              <label class="text-[11px] text-gray-400">实体名称 (Name):</label>
              <input id="kg-form-name" type="text" placeholder="例如: Bun, PostgreSQL, 偏好中文" class="w-full bg-dark-bg border border-dark-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500">
            </div>

            <div class="space-y-1">
              <label class="text-[11px] text-gray-400">实体类型 (Entity Type):</label>
              <select id="kg-form-type" class="w-full bg-dark-bg border border-dark-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500">
                <option value="preference">偏好 (preference)</option>
                <option value="technology">技术栈 (technology)</option>
                <option value="environment">开发环境 (environment)</option>
                <option value="project">工程项目 (project)</option>
                <option value="person">人物身份 (person)</option>
                <option value="concept">核心概念 (concept)</option>
              </select>
            </div>

            <div class="space-y-1">
              <label class="text-[11px] text-gray-400">描述信息 (Description):</label>
              <input id="kg-form-desc" type="text" placeholder="简短描述，例如: 极速打包运行环境" class="w-full bg-dark-bg border border-dark-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500">
            </div>

            <div class="space-y-1">
              <label class="text-[11px] text-gray-400">与 User 建立关系 (Relation to User):</label>
              <select id="kg-form-rel" class="w-full bg-dark-bg border border-dark-border rounded-lg px-2.5 py-1.5 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500">
                <option value="prefers">prefers (偏好使用)</option>
                <option value="operates_on">operates_on (运行环境)</option>
                <option value="develops">develops (开发/维护)</option>
                <option value="requires">requires (强制要求)</option>
                <option value="none">暂不建边 (仅添加独立节点)</option>
              </select>
            </div>

            <button onclick="submitNewEntity()" class="w-full mt-2 py-2 rounded-xl bg-emerald-500 text-gray-950 font-bold hover:bg-emerald-400 transition text-xs shadow-md shadow-emerald-500/20">
              入库知识图谱
            </button>
          </div>

          <div class="p-3.5 rounded-xl bg-dark-input/40 border border-dark-border text-gray-400 text-[11px] space-y-1.5">
            <div class="text-gray-300 font-semibold flex items-center space-x-1">
              <svg class="w-3.5 h-3.5 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              <span>自动学习说明：</span>
            </div>
            <p>除了手动在此添加，当您在日常提问中提到“以后请用 pnpm”、“我的系统是 macOS”时，网关也会**单次前向无感自动提炼**入库，并自动关联到大模型 System Prompt 中。</p>
          </div>
        </div>

      </div>
    </section>

    <!-- SECTION 4: Interactive Workspace Grid -->
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
              <p class="text-xs text-gray-400 mt-0.5">调用后端真实 Python `CompressionPipeline.process()` 算子</p>
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
              <textarea id="test-input" rows="8" class="w-full rounded-xl bg-dark-input border border-dark-border p-3 text-xs font-mono text-gray-200 focus:outline-none focus:border-brand-500 transition resize-none placeholder-gray-600" placeholder="在此粘贴测试文本、JSON 数组或报错日志..."></textarea>
            </div>
            <div>
              <div class="flex justify-between items-center text-xs font-semibold text-gray-400 mb-1.5">
                <span>优化输出 (Optimized Payload)</span>
                <span id="opt-token-badge" class="text-brand-400 font-mono">0 Tokens (0%)</span>
              </div>
              <textarea id="test-output" rows="8" readonly class="w-full rounded-xl bg-dark-input/60 border border-dark-border p-3 text-xs font-mono text-emerald-300 focus:outline-none resize-none placeholder-gray-600" placeholder="点击下方按钮调用后端真实流水线处理..."></textarea>
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
      </div>

      <!-- Right Column: Quick Setup & Offline Rules Panel (1 Col) -->
      <div class="space-y-6">
        
        <!-- One-Click Client Integration Guide -->
        <div class="glass rounded-2xl p-6">
          <h2 class="text-base font-bold text-white flex items-center space-x-2 pb-3 border-b border-dark-border">
            <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"/></svg>
            <span>Agent 客户端接入配置</span>
          </h2>

          <div class="mt-4 space-y-3.5 text-xs">
            <div>
              <span class="font-semibold text-gray-300 block mb-1">Pi Agent (直接在终端运行):</span>
              <div class="p-2.5 rounded-lg bg-dark-input font-mono text-emerald-400 border border-dark-border flex justify-between items-center">
                <span>pi "你的问题"</span>
                <span class="text-[10px] text-gray-400">自动走 CtxGuard</span>
              </div>
            </div>

            <div>
              <span class="font-semibold text-gray-300 block mb-1">Cursor / Cline / Windsurf:</span>
              <div class="p-2.5 rounded-lg bg-dark-input font-mono text-emerald-400 border border-dark-border flex justify-between items-center">
                <span>http://127.0.0.1:8787/v1</span>
                <button onclick="copyToClipboard('http://127.0.0.1:8787/v1')" class="text-gray-400 hover:text-white text-[10px] px-2 py-0.5 rounded bg-dark-card">复制</button>
              </div>
            </div>

            <div>
              <span class="font-semibold text-gray-300 block mb-1">OpenAI SDK (Python):</span>
              <pre class="p-2.5 rounded-lg bg-dark-input text-gray-300 border border-dark-border overflow-x-auto font-mono text-[11px]">client = OpenAI(base_url="http://127.0.0.1:8787/v1")</pre>
            </div>
          </div>
        </div>

      </div>

    </div>
  </main>

  <!-- Request Details Modal / Drawer -->
  <div id="detail-modal" class="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm hidden flex items-center justify-center p-4">
    <div class="glass bg-dark-card border border-dark-border rounded-2xl max-w-2xl w-full p-6 space-y-4 shadow-2xl relative">
      <div class="flex items-center justify-between border-b border-dark-border pb-3">
        <div class="flex items-center space-x-2">
          <span id="modal-req-id" class="px-2 py-0.5 rounded bg-brand-500/20 text-brand-400 font-mono font-bold text-xs">#0</span>
          <h3 class="text-sm font-bold text-white">对话会话与压缩详情</h3>
        </div>
        <button onclick="closeModal()" class="text-gray-400 hover:text-white p-1 rounded-lg hover:bg-gray-800">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
        </button>
      </div>

      <div class="grid grid-cols-2 gap-3 text-xs">
        <div class="p-3 rounded-xl bg-dark-input border border-dark-border space-y-1">
          <span class="text-gray-400 block text-[11px]">所属项目 (Project)</span>
          <span id="modal-project" class="font-bold text-emerald-400 font-mono text-sm block truncate">-</span>
        </div>
        <div class="p-3 rounded-xl bg-dark-input border border-dark-border space-y-1">
          <span class="text-gray-400 block text-[11px]">会话 Session ID</span>
          <span id="modal-session" class="font-bold text-purple-300 font-mono text-sm block truncate">-</span>
        </div>
        <div class="p-3 rounded-xl bg-dark-input border border-dark-border space-y-1">
          <span class="text-gray-400 block text-[11px]">调用模型 (Model)</span>
          <span id="modal-model" class="font-bold text-blue-400 font-mono block">-</span>
        </div>
        <div class="p-3 rounded-xl bg-dark-input border border-dark-border space-y-1">
          <span class="text-gray-400 block text-[11px]">处理时延 (Latency)</span>
          <span id="modal-latency" class="font-bold text-amber-400 font-mono block">-</span>
        </div>
      </div>

      <div class="space-y-1.5 text-xs">
        <span class="text-gray-400 font-semibold block">对话提问内容摘要 (User Prompt Preview):</span>
        <div id="modal-prompt" class="p-3 rounded-xl bg-dark-input border border-dark-border font-mono text-gray-200 text-xs max-h-32 overflow-y-auto whitespace-pre-wrap">-</div>
      </div>

      <div class="space-y-1.5 text-xs">
        <span class="text-gray-400 font-semibold block">后端命中的压缩算子 (Applied Operators):</span>
        <div id="modal-compressors" class="flex flex-wrap gap-1.5 p-2.5 rounded-xl bg-dark-input border border-dark-border"></div>
      </div>

      <div class="flex justify-end pt-2">
        <button onclick="closeModal()" class="px-4 py-2 rounded-xl bg-dark-card border border-dark-border hover:bg-gray-800 text-xs font-semibold text-gray-300">关闭</button>
      </div>
    </div>
  </div>

  <footer class="border-t border-dark-border/40 py-6 mt-12 text-center text-xs text-gray-500">
    <p>CtxGuard Context Optimization & Memory Gateway • 零重型依赖 • 毫秒级极速优化 • SQLite WAL 存储驱动</p>
  </footer>

  <script>
    let globalRecentData = [];
    let currentViewMode = 'flat'; // 'flat' | 'session'
    let expandedSessions = new Set();
    let filterState = {
      project: 'ALL',
      model: 'ALL',
      search: ''
    };

    function setText(id, text) {
      const el = document.getElementById(id);
      if (el) el.innerText = text;
    }

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
      const el = document.getElementById('test-input');
      if (el) {
        el.value = SAMPLES[type] || '';
        runTestCompress();
      }
    }

    function setViewMode(mode) {
      currentViewMode = mode;
      const btnSession = document.getElementById('btn-view-session');
      const btnFlat = document.getElementById('btn-view-flat');
      const viewSession = document.getElementById('view-session-container');
      const viewFlat = document.getElementById('view-flat-container');

      if (mode === 'session') {
        if (btnSession) btnSession.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition flex items-center space-x-1.5 bg-brand-500/20 text-brand-300 border border-brand-500/30 shadow-sm';
        if (btnFlat) btnFlat.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition flex items-center space-x-1.5 text-gray-400 hover:text-gray-200';
        if (viewSession) viewSession.classList.remove('hidden');
        if (viewFlat) viewFlat.classList.add('hidden');
      } else {
        if (btnFlat) btnFlat.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition flex items-center space-x-1.5 bg-brand-500/20 text-brand-300 border border-brand-500/30 shadow-sm';
        if (btnSession) btnSession.className = 'px-3.5 py-1.5 rounded-lg font-semibold transition flex items-center space-x-1.5 text-gray-400 hover:text-gray-200';
        if (viewFlat) viewFlat.classList.remove('hidden');
        if (viewSession) viewSession.classList.add('hidden');
      }
      renderFilteredViews();
    }

    function toggleSessionExpand(sessionId) {
      if (expandedSessions.has(sessionId)) {
        expandedSessions.delete(sessionId);
      } else {
        expandedSessions.add(sessionId);
      }
      renderFilteredViews();
    }

    function setFilter(type, value) {
      if (type === 'project') {
        filterState.project = value;
        const el = document.getElementById('filter-project');
        if (el) el.value = value;
      } else if (type === 'model') {
        filterState.model = value;
        const el = document.getElementById('filter-model');
        if (el) el.value = value;
      }
      applyFilters();
    }

    function clearSearch() {
      const el = document.getElementById('filter-search');
      if (el) el.value = '';
      filterState.search = '';
      applyFilters();
    }

    function resetAllFilters() {
      filterState = { project: 'ALL', model: 'ALL', search: '' };
      const fp = document.getElementById('filter-project');
      const fm = document.getElementById('filter-model');
      const fs = document.getElementById('filter-search');
      if (fp) fp.value = 'ALL';
      if (fm) fm.value = 'ALL';
      if (fs) fs.value = '';
      applyFilters();
    }

    function applyFilters() {
      const fp = document.getElementById('filter-project');
      const fm = document.getElementById('filter-model');
      const fs = document.getElementById('filter-search');
      if (fp) filterState.project = fp.value;
      if (fm) filterState.model = fm.value;
      if (fs) filterState.search = fs.value.trim().toLowerCase();
      renderFilteredViews();
    }

    async function refreshData() {
      try {
        const res = await fetch('/api/stats');
        const data = await res.json();
        
        const summary = data.summary || {};
        setText('stat-saved-tokens', (summary.total_saved_tokens || 0).toLocaleString());
        setText('stat-saved-percent', `${summary.overall_saved_percent || 0}%`);
        setText('stat-raw-tokens', (summary.total_raw_tokens || 0).toLocaleString());
        setText('stat-opt-tokens', (summary.total_optimized_tokens || 0).toLocaleString());
        setText('stat-dollars-saved', `$${(summary.estimated_dollars_saved || 0).toFixed(4)}`);
        setText('stat-total-requests', (summary.total_requests || 0).toLocaleString());
        setText('stat-avg-latency', (summary.avg_latency_ms || 0).toFixed(2));

        globalRecentData = data.recent || [];
        populateDropdownsAndBadges();
        renderFilteredViews();

        // Also fetch memory stats and graph stats
        refreshMemoryStats();
        refreshGraphStats();
      } catch (err) {
        console.error('Failed to load stats:', err);
      }
    }

    async function refreshMemoryStats() {
      try {
        const res = await fetch('/api/memory/stats');
        const mData = await res.json();

        document.getElementById('stat-memory-count').innerText = (mData.total_fingerprints || 0).toLocaleString();
        document.getElementById('stat-memory-chars').innerText = `${(mData.total_memorized_chars || 0).toLocaleString()} 字符`;
        document.getElementById('memory-fp-count').innerText = mData.total_fingerprints || 0;

        // Render Memory Fingerprints table
        const fpTbody = document.getElementById('memory-fp-tbody');
        const fps = mData.recent_fingerprints || [];
        if (fps.length > 0) {
          fpTbody.innerHTML = fps.map(f => `
            <tr class="hover:bg-dark-card/40">
              <td class="p-2.5 text-purple-300 font-bold truncate max-w-[100px]" title="${f.hash_id}">#${f.hash_id.slice(0, 10)}</td>
              <td class="p-2.5 text-gray-400 font-mono text-[11px]">${f.char_length} 字符</td>
              <td class="p-2.5 text-gray-400 font-mono text-[11px] truncate max-w-[100px]" title="${f.session_id}">${f.session_id}</td>
              <td class="p-2.5 text-gray-300 truncate max-w-[200px]" title="${escapeHtml(f.snippet)}">${escapeHtml(f.snippet)}</td>
            </tr>
          `).join('');
        } else {
          fpTbody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-gray-500 font-sans text-xs">暂无指纹记忆，运行 Agent 读写文件后自动生成</td></tr>';
        }

        // Render Memory Rules
        const rulesContainer = document.getElementById('memory-rules-container');
        const rules = mData.learned_rules || [];
        document.getElementById('memory-rule-count').innerText = rules.length;
        if (rules.length > 0) {
          rulesContainer.innerHTML = rules.map(r => `
            <div class="p-3 rounded-xl bg-dark-input/80 border border-dark-border space-y-1 text-xs">
              <div class="flex items-center justify-between">
                <span class="px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-300 border border-amber-500/20 font-bold text-[11px] font-mono">
                  📌 ${r.category}
                </span>
                <span class="text-[10px] text-gray-500">触发: ${r.trigger}</span>
              </div>
              <div class="text-gray-200 font-medium">${r.directive}</div>
              <div class="text-[11px] text-gray-500 italic">💡 经验来源: ${r.rationale}</div>
            </div>
          `).join('');
        }
      } catch (err) {
        console.error('Failed to load memory stats:', err);
      }
    }

    async function refreshGraphStats() {
      try {
        const resStats = await fetch('/api/graph/stats');
        const gData = await resStats.json();
        setText('kg-total-entities', gData.total_entities || 0);
        setText('kg-total-relations', gData.total_relationships || 0);

        // Render type badges
        const typeBadges = document.getElementById('kg-type-badges');
        if (typeBadges && gData.entity_types) {
          typeBadges.innerHTML = Object.entries(gData.entity_types).map(([k, v]) => `
            <span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 text-[10px] font-mono">
              ${k}: ${v}
            </span>
          `).join('');
        }

        // Fetch entities list
        const resEntities = await fetch('/api/graph/entities');
        const entData = await resEntities.json();
        const tbody = document.getElementById('kg-entities-tbody');
        if (tbody) {
          const ents = entData.entities || [];
          if (ents.length > 0) {
            tbody.innerHTML = ents.map(e => `
              <tr class="hover:bg-dark-card/40">
                <td class="p-2.5 font-bold text-emerald-300 truncate max-w-[120px]" title="${e.name}">
                  <span class="cursor-pointer hover:underline" onclick="quickQueryGraph('${escapeHtml(e.name)}')">
                    ${escapeHtml(e.name)}
                  </span>
                </td>
                <td class="p-2.5 text-purple-300 font-mono text-[11px]">${escapeHtml(e.entity_type)}</td>
                <td class="p-2.5 text-gray-300 font-sans truncate max-w-[220px]" title="${escapeHtml(e.description || '')}">
                  ${escapeHtml(e.description || '(暂无描述)')}
                </td>
                <td class="p-2.5 text-right space-x-1">
                  <button onclick="quickQueryGraph('${escapeHtml(e.name)}')" class="px-2 py-0.5 rounded bg-dark-card hover:bg-gray-800 text-[10px] text-blue-300 border border-dark-border">2-hop</button>
                  <button onclick="deleteGraphEntity('${e.id}')" class="px-2 py-0.5 rounded bg-red-500/10 hover:bg-red-500/20 text-[10px] text-red-400 border border-red-500/20">删</button>
                </td>
              </tr>
            `).join('');
          } else {
            tbody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-gray-500 font-sans text-xs">暂无实体记录</td></tr>';
          }
        }
      } catch (err) {
        console.error('Failed to load graph stats:', err);
      }
    }

    async function searchSubgraph() {
      const qInput = document.getElementById('kg-search-input');
      const query = (qInput ? qInput.value : '').trim();
      const resBox = document.getElementById('kg-query-result');
      if (!query) {
        if (resBox) resBox.innerHTML = '<div class="text-gray-500 text-center py-6">请输入实体关键词进行检索</div>';
        return;
      }

      if (resBox) resBox.innerHTML = '<div class="text-emerald-400 text-center py-6 animate-pulse">正在执行 BFS 2-hop 子图遍历...</div>';

      try {
        const res = await fetch(`/api/graph/query?q=${encodeURIComponent(query)}&hops=2`);
        const data = await res.json();
        const entities = data.entities || [];
        const rels = data.relationships || [];

        if (entities.length === 0) {
          resBox.innerHTML = `<div class="text-amber-400 text-center py-4">未检索到与 "${escapeHtml(query)}" 关联的知识实体，请尝试添加新实体。</div>`;
          return;
        }

        const entMap = {};
        entities.forEach(e => { entMap[e.id] = e; });

        let html = `
          <div class="flex items-center justify-between border-b border-dark-border/60 pb-2">
            <span class="text-emerald-300 font-bold">🎯 命中子图: ${entities.length} 个实体节点, ${rels.length} 条关系边</span>
            <span class="text-[10px] text-gray-400">遍历深度: 2-hop (BFS)</span>
          </div>
          <div class="space-y-1.5 pt-1">
        `;

        if (rels.length > 0) {
          html += '<div class="text-[11px] text-gray-400 font-semibold mb-1">🔗 拓扑关系链条:</div>';
          rels.forEach(r => {
            const src = entMap[r.source_id] ? entMap[r.source_id].name : r.source_id;
            const tgt = entMap[r.target_id] ? entMap[r.target_id].name : r.target_id;
            html += `
              <div class="flex items-center space-x-2 text-xs py-1 px-2 rounded-lg bg-dark-input/60 border border-dark-border/40">
                <span class="text-emerald-300 font-bold"># ${escapeHtml(src)}</span>
                <span class="px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-300 text-[10px] font-mono border border-purple-500/30">${escapeHtml(r.relation_type)}</span>
                <span class="text-blue-300 font-bold">➔ ${escapeHtml(tgt)}</span>
              </div>
            `;
          });
        } else {
          html += '<div class="text-gray-400 text-xs italic">该实体目前为独立节点，暂未与其他实体建立关系边。</div>';
        }

        if (data.context_markdown) {
          html += `
            <div class="mt-2 pt-2 border-t border-dark-border/40">
              <div class="text-[10px] text-gray-400 font-mono mb-1">注入大模型的 Prompt 知识块 (Prompt Injection Preview):</div>
              <pre class="p-2 rounded bg-dark-bg text-emerald-400/90 text-[11px] whitespace-pre-wrap font-mono">${escapeHtml(data.context_markdown)}</pre>
            </div>
          `;
        }

        html += '</div>';
        resBox.innerHTML = html;
      } catch (err) {
        if (resBox) resBox.innerHTML = `<div class="text-red-400 text-center py-4">检索失败: ${err}</div>`;
      }
    }

    function quickQueryGraph(name) {
      const qInput = document.getElementById('kg-search-input');
      if (qInput) qInput.value = name;
      searchSubgraph();
    }

    async function submitNewEntity() {
      const name = (document.getElementById('kg-form-name').value || '').trim();
      const entity_type = document.getElementById('kg-form-type').value;
      const description = (document.getElementById('kg-form-desc').value || '').trim();
      const relation_to_user = document.getElementById('kg-form-rel').value;

      if (!name) {
        alert('请输入实体名称！');
        return;
      }

      try {
        await fetch('/api/graph/entity', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, entity_type, description })
        });

        if (relation_to_user && relation_to_user !== 'none') {
          await fetch('/api/graph/relationship', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              source_name: 'User',
              target_name: name,
              relation_type: relation_to_user
            })
          });
        }

        document.getElementById('kg-form-name').value = '';
        document.getElementById('kg-form-desc').value = '';
        await refreshGraphStats();
        quickQueryGraph(name);
      } catch (err) {
        alert('添加失败: ' + err);
      }
    }

    async function deleteGraphEntity(id) {
      if (!confirm('确定要删除该实体及其关联关系吗？')) return;
      try {
        await fetch(`/api/graph/entity/${id}`, { method: 'DELETE' });
        await refreshGraphStats();
      } catch (err) {
        alert('删除失败: ' + err);
      }
    }

    function populateDropdownsAndBadges() {
      const projectsCount = {};
      const modelsCount = {};

      globalRecentData.forEach(r => {
        const p = r.project_name || 'Pi-Agent';
        const m = r.model || 'unknown';
        projectsCount[p] = (projectsCount[p] || 0) + 1;
        modelsCount[m] = (modelsCount[m] || 0) + 1;
      });

      // Update Project Select
      const projSelect = document.getElementById('filter-project');
      const currentProj = filterState.project;
      const projOptions = ['<option value="ALL">全部项目 (All Projects)</option>'];
      Object.keys(projectsCount).sort().forEach(p => {
        projOptions.push(`<option value="${p}" ${currentProj === p ? 'selected' : ''}>${p} (${projectsCount[p]})</option>`);
      });
      projSelect.innerHTML = projOptions.join('');

      // Update Model Select
      const modelSelect = document.getElementById('filter-model');
      const currentModel = filterState.model;
      const modelOptions = ['<option value="ALL">全部模型 (All Models)</option>'];
      Object.keys(modelsCount).sort().forEach(m => {
        modelOptions.push(`<option value="${m}" ${currentModel === m ? 'selected' : ''}>${m} (${modelsCount[m]})</option>`);
      });
      modelSelect.innerHTML = modelOptions.join('');

      // Render Project Badges
      const projBadgesContainer = document.getElementById('project-badges-container');
      projBadgesContainer.innerHTML = Object.keys(projectsCount).map(p => {
        const isSelected = filterState.project === p;
        return `
          <button onclick="setFilter('project', '${isSelected ? 'ALL' : p}')" class="px-2 py-0.5 rounded-md text-[11px] font-mono border transition ${
            isSelected 
              ? 'bg-emerald-500 text-gray-950 font-bold border-emerald-400 shadow-sm' 
              : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20'
          }">
            ${p} <span class="opacity-80">(${projectsCount[p]})</span>
          </button>
        `;
      }).join('');

      // Render Model Badges
      const modelBadgesContainer = document.getElementById('model-badges-container');
      modelBadgesContainer.innerHTML = Object.keys(modelsCount).map(m => {
        const isSelected = filterState.model === m;
        return `
          <button onclick="setFilter('model', '${isSelected ? 'ALL' : m}')" class="px-2 py-0.5 rounded-md text-[11px] font-mono border transition ${
            isSelected 
              ? 'bg-blue-500 text-white font-bold border-blue-400 shadow-sm' 
              : 'bg-blue-500/10 text-blue-400 border-blue-500/20 hover:bg-blue-500/20'
          }">
            ${m} <span class="opacity-80">(${modelsCount[m]})</span>
          </button>
        `;
      }).join('');
    }

    function renderFilteredViews() {
      // 1. Filter raw items
      const filtered = globalRecentData.filter(r => {
        const p = r.project_name || 'Pi-Agent';
        const m = r.model || 'unknown';
        const sess = r.session_id || '';
        const prev = r.prompt_preview || '';

        if (filterState.project !== 'ALL' && p !== filterState.project) return false;
        if (filterState.model !== 'ALL' && m !== filterState.model) return false;
        if (filterState.search) {
          const matchSearch = sess.toLowerCase().includes(filterState.search)
            || prev.toLowerCase().includes(filterState.search)
            || p.toLowerCase().includes(filterState.search)
            || m.toLowerCase().includes(filterState.search);
          if (!matchSearch) return false;
        }
        return true;
      });

      // Update Active Filter Bar
      const filterBar = document.getElementById('active-filter-bar');
      const filterText = document.getElementById('active-filter-text');
      const isFiltered = (filterState.project !== 'ALL' || filterState.model !== 'ALL' || filterState.search !== '');
      if (isFiltered) {
        filterBar.classList.remove('hidden');
        const tags = [];
        if (filterState.project !== 'ALL') tags.push(`项目: <b>${filterState.project}</b>`);
        if (filterState.model !== 'ALL') tags.push(`模型: <b>${filterState.model}</b>`);
        if (filterState.search) tags.push(`搜索: <b>"${filterState.search}"</b>`);
        filterText.innerHTML = `当前过滤条件 [${tags.join(' • ')}] → 匹配到 <b>${filtered.length}</b> 条记录`;
      } else {
        filterBar.classList.add('hidden');
      }

      // Update count badges
      document.getElementById('flat-count-badge').innerText = filtered.length;

      // 2. Render Flat Table
      const flatTbody = document.getElementById('recent-table-body');
      if (filtered.length > 0) {
        flatTbody.innerHTML = filtered.map((r) => {
          const origIdx = globalRecentData.findIndex(item => item.id === r.id);
          const preview = r.prompt_preview ? r.prompt_preview : '(无提问文本)';
          const proj = r.project_name || 'Pi-Agent';
          return `
            <tr onclick="openModal(${origIdx})" class="hover:bg-dark-card/60 cursor-pointer transition">
              <td class="py-2.5 text-gray-500 font-bold">#${r.id}</td>
              <td class="py-2.5">
                <span class="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-semibold text-[11px]">${proj}</span>
              </td>
              <td class="py-2.5 text-purple-300 truncate max-w-[110px]" title="${r.session_id}">${r.session_id}</td>
              <td class="py-2.5 text-gray-300 font-sans truncate max-w-[200px]" title="${escapeHtml(preview)}">${escapeHtml(preview)}</td>
              <td class="py-2.5 text-blue-400 font-semibold truncate max-w-[140px]">${r.model}</td>
              <td class="py-2.5">${r.raw_tokens} <span class="text-gray-500">→</span> <span class="text-emerald-400">${r.optimized_tokens}</span></td>
              <td class="py-2.5 font-bold text-brand-400">${r.saved_ratio}%</td>
              <td class="py-2.5 text-amber-300">${r.latency_ms.toFixed(1)}ms</td>
              <td class="py-2.5">
                <button onclick="event.stopPropagation(); openModal(${origIdx})" class="px-2 py-0.5 rounded bg-dark-card hover:bg-gray-800 text-[10px] text-gray-300 border border-dark-border">详情</button>
              </td>
            </tr>
          `;
        }).join('');
      } else {
        flatTbody.innerHTML = '<tr><td colspan="9" class="py-6 text-center text-gray-500 font-sans">未找到符合筛选条件的请求记录</td></tr>';
      }

      // 3. Group by Session for Session View
      const sessionMap = {};
      filtered.forEach(r => {
        const sid = r.session_id || 'default';
        if (!sessionMap[sid]) {
          sessionMap[sid] = {
            session_id: sid,
            project_name: r.project_name || 'Pi-Agent',
            models: new Set(),
            requests: [],
            total_raw: 0,
            total_opt: 0,
            total_saved: 0,
            avg_latency: 0,
            first_prompt: r.prompt_preview || '',
            latest_prompt: r.prompt_preview || '',
            last_timestamp: r.timestamp || ''
          };
        }
        const g = sessionMap[sid];
        g.requests.push(r);
        g.models.add(r.model);
        g.total_raw += r.raw_tokens || 0;
        g.total_opt += r.optimized_tokens || 0;
        g.total_saved += r.saved_tokens || 0;
        g.latest_prompt = r.prompt_preview || g.latest_prompt;
      });

      const sessionGroups = Object.values(sessionMap);
      document.getElementById('session-count-badge').innerText = sessionGroups.length;

      const sessionListContainer = document.getElementById('session-groups-list');
      if (sessionGroups.length > 0) {
        sessionListContainer.innerHTML = sessionGroups.map(g => {
          const isExpanded = expandedSessions.has(g.session_id);
          const turnsCount = g.requests.length;
          const modelsList = Array.from(g.models).join(', ');
          const overallSavedRatio = g.total_raw > 0 ? ((g.total_saved / g.total_raw) * 100).toFixed(1) : '0.0';
          const avgLatency = (g.requests.reduce((acc, x) => acc + (x.latency_ms || 0), 0) / turnsCount).toFixed(1);
          
          return `
            <div class="glass rounded-xl border border-dark-border/80 overflow-hidden transition hover:border-dark-border">
              <!-- Session Header Card -->
              <div onclick="toggleSessionExpand('${g.session_id}')" class="p-4 flex flex-col md:flex-row md:items-center justify-between gap-3 cursor-pointer bg-dark-card/40 hover:bg-dark-card/80 transition">
                <div class="space-y-1.5 flex-1 min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-300 border border-emerald-500/20 font-bold text-xs font-mono">
                      📁 ${g.project_name}
                    </span>
                    <span class="px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-300 border border-blue-500/20 font-semibold text-xs font-mono">
                      🤖 ${modelsList}
                    </span>
                    <span class="px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-300 border border-purple-500/20 font-semibold text-xs font-mono">
                      💬 ${turnsCount} 轮对话
                    </span>
                    <span class="text-xs font-mono text-gray-400 truncate max-w-[260px]" title="${g.session_id}">
                      窗口 ID: <b class="text-gray-200">${g.session_id}</b>
                    </span>
                  </div>
                  <div class="text-xs text-gray-300 truncate font-sans" title="${escapeHtml(g.latest_prompt)}">
                    <span class="text-gray-500 font-semibold">最新提问:</span> ${escapeHtml(g.latest_prompt || '(无文本)')}
                  </div>
                </div>

                <!-- Session Stats & Toggle -->
                <div class="flex items-center space-x-4 self-end md:self-center shrink-0">
                  <div class="text-right font-mono text-xs">
                    <div class="text-emerald-400 font-bold">省 ${g.total_saved} Tokens (${overallSavedRatio}%)</div>
                    <div class="text-gray-500 text-[11px]">均耗时 ${avgLatency}ms</div>
                  </div>
                  <div class="w-6 h-6 rounded-lg bg-dark-card border border-dark-border flex items-center justify-center text-gray-400 transition ${isExpanded ? 'rotate-180 text-brand-400' : ''}">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                  </div>
                </div>
              </div>

              <!-- Collapsible Turns Table -->
              ${isExpanded ? `
                <div class="border-t border-dark-border/80 bg-dark-bg/60 p-3 overflow-x-auto">
                  <table class="w-full text-left text-xs font-mono">
                    <thead class="text-gray-500 uppercase text-[10px] border-b border-dark-border/40">
                      <tr>
                        <th class="pb-2">轮次</th>
                        <th class="pb-2">提问摘要</th>
                        <th class="pb-2">模型</th>
                        <th class="pb-2">Token 变化</th>
                        <th class="pb-2">节省率</th>
                        <th class="pb-2">处理算子</th>
                        <th class="pb-2">耗时</th>
                        <th class="pb-2">操作</th>
                      </tr>
                    </thead>
                    <tbody class="divide-y divide-dark-border/30 text-gray-300">
                      ${g.requests.map((r, turnIdx) => {
                        const origIdx = globalRecentData.findIndex(item => item.id === r.id);
                        const comps = (r.applied_compressors || []).map(c => `<span class="px-1.5 py-0.2 rounded bg-brand-500/10 text-brand-400 border border-brand-500/20 text-[10px]">${c}</span>`).join(' ');
                        return `
                          <tr class="hover:bg-dark-card/40">
                            <td class="py-2 text-gray-500">#${r.id} (第 ${turnsCount - turnIdx} 轮)</td>
                            <td class="py-2 text-gray-200 font-sans truncate max-w-[220px]" title="${escapeHtml(r.prompt_preview || '')}">${escapeHtml(r.prompt_preview || '(无提问文本)')}</td>
                            <td class="py-2 text-blue-400 font-semibold">${r.model}</td>
                            <td class="py-2">${r.raw_tokens} → <span class="text-emerald-400">${r.optimized_tokens}</span></td>
                            <td class="py-2 font-bold text-brand-400">${r.saved_ratio}%</td>
                            <td class="py-2">${comps || '<span class="text-gray-500 italic">无</span>'}</td>
                            <td class="py-2 text-amber-300">${r.latency_ms.toFixed(1)}ms</td>
                            <td class="py-2">
                              <button onclick="openModal(${origIdx})" class="px-2 py-0.5 rounded bg-dark-card hover:bg-gray-800 text-[10px] text-gray-300 border border-dark-border">查看详情</button>
                            </td>
                          </tr>
                        `;
                      }).join('')}
                    </tbody>
                  </table>
                </div>
              ` : ''}
            </div>
          `;
        }).join('');
      } else {
        sessionListContainer.innerHTML = '<div class="py-8 text-center text-gray-500 text-xs">未找到符合当前筛选条件的对话会话窗口</div>';
      }
    }

    function openModal(idx) {
      const r = globalRecentData[idx];
      if (!r) return;

      document.getElementById('modal-req-id').innerText = `#${r.id}`;
      document.getElementById('modal-project').innerText = r.project_name || 'Pi-Agent';
      document.getElementById('modal-session').innerText = r.session_id;
      document.getElementById('modal-model').innerText = r.model;
      document.getElementById('modal-latency').innerText = `${r.latency_ms.toFixed(2)} ms (省 ${r.saved_tokens} Tokens / ${r.saved_ratio}%)`;
      document.getElementById('modal-prompt').innerText = r.prompt_preview || '(无提问文本)';

      const compContainer = document.getElementById('modal-compressors');
      const comps = r.applied_compressors || [];
      if (comps.length > 0) {
        compContainer.innerHTML = comps.map(c => `
          <span class="px-2 py-0.5 rounded bg-brand-500/20 text-brand-400 text-[11px] font-mono border border-brand-500/30">${c}</span>
        `).join('');
      } else {
        compContainer.innerHTML = '<span class="text-gray-500 italic text-xs">无修改 (内容结构已最优)</span>';
      }

      document.getElementById('detail-modal').classList.remove('hidden');
    }

    function closeModal() {
      document.getElementById('detail-modal').classList.add('hidden');
    }

    function escapeHtml(str) {
      return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function triggerSimulatedLiveRequest() {
      try {
        const res = await fetch('/api/simulate/request', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: 'deepseek-flash',
            prompt: 'Please query customer database records and optimize schema.',
            project_name: 'Pi-Web',
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
        resultBox.innerText = data.rendered_rules || '已完成分析，未发现重复死循环。已更新自进化避坑经验库。';
        await refreshMemoryStats();
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
      setViewMode('flat');
      refreshData();
      loadSample('code');
      setInterval(refreshData, 2500);
    });
  </script>
</body>
</html>
"""
