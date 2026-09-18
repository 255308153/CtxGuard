#!/usr/bin/env python3
"""
Render CtxGuard architecture diagram in RepoAgent infographic style.
Generates assets/architecture_diagram.png using Headless Google Chrome at 2x Retina resolution.
"""

import subprocess
import os
import sys

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>CtxGuard Architecture Diagram</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800;900&family=JetBrains+Mono:wght@500;600;700;800&display=swap');

  * {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }

  body {
    font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #ffffff;
    width: 1440px;
    height: 960px;
    padding: 24px 36px;
    color: #1e293b;
    position: relative;
    overflow: hidden;
  }

  /* 基础容器卡片 (RepoAgent 风格: 粗描边、大圆角、白底、精美轻投影) */
  .diagram-box {
    background: #ffffff;
    border-radius: 22px;
    position: relative;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  }

  .border-blue {
    border: 3.5px solid #2872e1;
  }

  .border-green {
    border: 3.5px solid #007e54;
    background: #ffffff;
  }

  .border-orange {
    border: 3.5px solid #c97322;
  }

  .border-dark {
    border: 3.5px solid #1f242b;
  }

  .border-dashed-gray {
    border: 2.5px dashed #cbd5e1;
    background: #ffffff;
  }

  /* 顶部左一: Client Ecosystem & TeamWork */
  .box-github {
    position: absolute;
    top: 24px;
    left: 36px;
    width: 440px;
    height: 236px;
    padding: 24px 28px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .github-header {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .github-title {
    font-size: 27px;
    font-weight: 800;
    color: #2872e1;
    letter-spacing: -0.5px;
  }

  .github-divider {
    height: 2px;
    background: #e2e8f0;
    margin: 4px 0;
  }

  .teamwork-row {
    display: flex;
    align-items: center;
    gap: 20px;
    margin-bottom: 6px;
  }

  .teamwork-title {
    font-size: 26px;
    font-weight: 800;
    color: #1f242b;
  }

  /* 顶部中间: Independent Developer & Coding Agents */
  .box-developer {
    position: absolute;
    top: 24px;
    left: 546px;
    width: 380px;
    height: 168px;
    padding: 16px 20px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .dev-left {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .dev-title {
    font-size: 21px;
    font-weight: 800;
    color: #2872e1;
    line-height: 1.22;
  }

  .dev-icons {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-top: 2px;
  }

  .icon-badge {
    width: 34px;
    height: 34px;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 5px rgba(0,0,0,0.12);
  }

  .dev-divider-dashed {
    width: 0;
    height: 124px;
    border-left: 2px dashed #93c5fd;
    margin: 0 8px;
  }

  .dev-illustration {
    width: 108px;
    height: 108px;
  }

  /* Code Update 药丸按钮 (RepoAgent 风格) */
  .box-code-update {
    position: absolute;
    top: 208px;
    left: 546px;
    width: 380px;
    height: 52px;
    border: 3px solid #b91c1c;
    border-radius: 14px;
    background: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 12px;
    font-size: 19px;
    font-weight: 800;
    color: #b91c1c;
    box-shadow: 0 4px 12px rgba(185, 28, 28, 0.08);
  }

  /* 中间分隔条: Git + Pre-commit 风格条 */
  .bar-git-commit {
    position: absolute;
    top: 288px;
    left: 36px;
    width: 890px;
    height: 40px;
    border: 2px solid #5b6577;
    border-radius: 8px;
    background: #f8fafc;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 17px;
    font-weight: 800;
    color: #334155;
    letter-spacing: 0.5px;
    z-index: 5;
  }

  .bar-git-text {
    background: #f8fafc;
    padding: 0 16px;
    position: relative;
    z-index: 6;
  }

  /* 右侧主框: CtxGuard Gateway (RepoAgent 绿色主卡片) */
  .box-repoagent {
    position: absolute;
    top: 24px;
    right: 36px;
    width: 400px;
    height: 908px;
    padding: 22px 20px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .repoagent-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
  }

  .repoagent-title {
    font-size: 30px;
    font-weight: 900;
    color: #007e54;
    letter-spacing: -0.5px;
  }

  .repoagent-port {
    font-size: 12px;
    font-weight: 800;
    background: #d1fae5;
    color: #065f46;
    padding: 4px 10px;
    border-radius: 20px;
    margin-left: auto;
  }

  .modules-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px 10px;
  }

  /* 小模块彩色圆角卡片 (RepoAgent 风格) */
  .mod-card {
    border-radius: 16px;
    padding: 10px 8px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    min-height: 82px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.02);
  }

  .mod-title {
    font-size: 14px;
    font-weight: 800;
    line-height: 1.25;
    margin-bottom: 3px;
  }

  .mod-subtitle {
    font-size: 10px;
    font-weight: 600;
    opacity: 0.85;
  }

  /* 黄色卡片 */
  .card-yellow {
    background: #fff2d6;
    border: 2px solid #e2a832;
    color: #633806;
  }

  /* 橙色卡片 */
  .card-orange {
    background: #fde4d6;
    border: 2px solid #eb7e4d;
    color: #7c2d12;
  }

  /* 浅蓝卡片 */
  .card-blue {
    background: #d9e9fc;
    border: 2px solid #5095e8;
    color: #1e3a8a;
  }

  /* 浅粉紫卡片 */
  .card-purple {
    background: #eed7ec;
    border: 2px solid #aa68aa;
    color: #581c87;
  }

  /* 浅绿卡片 */
  .card-green {
    background: #cae8bd;
    border: 2px solid #5ca642;
    color: #14532d;
  }

  /* 浅青卡片 */
  .card-cyan {
    background: #d4f2fd;
    border: 2px solid #38bdf8;
    color: #0c4a6e;
  }

  /* 点点点 */
  .dots-row {
    grid-column: span 2;
    display: flex;
    justify-content: center;
    gap: 24px;
    font-size: 22px;
    font-weight: 900;
    color: #1e293b;
    letter-spacing: 4px;
    margin: 1px 0;
  }

  /* 底部 LLMs 卡片 (RepoAgent 红卡) */
  .card-llms {
    background: #fca7a7;
    border: 3.5px solid #dc2626;
    border-radius: 20px;
    padding: 18px 16px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    margin-top: 10px;
  }

  .llms-title {
    font-size: 32px;
    font-weight: 900;
    color: #1e293b;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
  }

  .llms-sub {
    font-size: 11.5px;
    font-weight: 800;
    color: #7f1d1d;
    text-align: center;
    margin-bottom: 6px;
  }

  .llms-tags {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
    justify-content: center;
  }

  .llm-badge {
    background: #ffffff;
    border: 1.5px solid #f87171;
    border-radius: 12px;
    padding: 2px 8px;
    font-size: 10px;
    font-weight: 800;
    color: #991b1b;
  }

  /* 左下角: Markdown 代码对比框 (RepoAgent 黑色卡片) */
  .box-markdown {
    position: absolute;
    top: 352px;
    left: 36px;
    width: 440px;
    height: 580px;
    padding: 22px;
    display: flex;
    flex-direction: column;
  }

  .markdown-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 14px;
  }

  .markdown-icon-box {
    background: #1f242b;
    color: white;
    font-weight: 900;
    font-size: 15px;
    padding: 4px 8px;
    border-radius: 6px;
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .markdown-title {
    font-size: 22px;
    font-weight: 900;
    color: #1f242b;
  }

  .markdown-columns {
    display: flex;
    align-items: center;
    gap: 10px;
    flex: 1;
  }

  /* 对比蓝色卡片 (RepoAgent 左右蓝框) */
  .code-sheet {
    flex: 1;
    height: 100%;
    background: #d8e8fc;
    border-radius: 18px;
    padding: 16px 12px;
    display: flex;
    flex-direction: column;
    justify-content: space-around;
    box-shadow: 0 4px 10px rgba(40, 114, 225, 0.12);
  }

  .sheet-title {
    font-size: 12px;
    font-weight: 800;
    color: #1e40af;
    border-bottom: 1.5px solid #93c5fd;
    padding-bottom: 4px;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
  }

  .code-item {
    display: flex;
    flex-direction: column;
    margin: 2px 0;
  }

  .code-fn {
    font-size: 12px;
    font-weight: 800;
    color: #0f172a;
    font-family: 'JetBrains Mono', monospace;
  }

  .code-doc {
    font-size: 10px;
    color: #475569;
    font-family: 'JetBrains Mono', monospace;
    margin-top: 1px;
  }

  .code-red {
    color: #dc2626 !important;
    font-weight: 800;
  }

  .code-green {
    color: #15803d !important;
    font-weight: 800;
  }

  .code-strike {
    text-decoration: line-through;
    color: #94a3b8 !important;
  }

  .sheet-arrow {
    width: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  /* 中间下 1: Repository Structure (橙色卡) */
  .box-structure {
    position: absolute;
    top: 352px;
    left: 546px;
    width: 380px;
    height: 250px;
    padding: 20px 22px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .structure-header {
    font-size: 22px;
    font-weight: 800;
    color: #c97322;
    margin-bottom: 8px;
  }

  .structure-body {
    display: flex;
    align-items: center;
    gap: 20px;
  }

  .tree-icon-svg {
    width: 82px;
    height: 82px;
    flex-shrink: 0;
  }

  .structure-bullets {
    list-style: none;
    font-size: 14.5px;
    font-weight: 700;
    color: #94a3b8;
    line-height: 1.7;
    font-family: 'JetBrains Mono', monospace;
  }

  .structure-bullets li::before {
    content: "•";
    color: #c97322;
    font-size: 18px;
    display: inline-block;
    width: 14px;
  }

  /* 中间下 2: Human Feedback 风格虚线框 */
  .box-feedback {
    position: absolute;
    top: 628px;
    left: 546px;
    width: 380px;
    height: 304px;
    padding: 20px 22px;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
  }

  .feedback-header {
    font-size: 21px;
    font-weight: 800;
    color: #8b5cf6;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .feedback-body {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .feedback-icon-svg {
    width: 72px;
    height: 72px;
    flex-shrink: 0;
  }

  .feedback-bullets {
    list-style: none;
    font-size: 13.5px;
    font-weight: 700;
    color: #64748b;
    line-height: 1.7;
  }

  .feedback-bullets li::before {
    content: "•";
    color: #8b5cf6;
    font-size: 18px;
    display: inline-block;
    width: 14px;
  }

  /* 编号徽章 ① ② ③ ④ 与箭头 (RepoAgent 同款) */
  .step-badge {
    position: absolute;
    width: 44px;
    height: 44px;
    border-radius: 50%;
    border: 3.5px solid #2872e1;
    background: #ffffff;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 23px;
    font-weight: 900;
    color: #2872e1;
    box-shadow: 0 4px 10px rgba(40, 114, 225, 0.15);
    z-index: 20;
  }

  /* 流程连线层 (完全复刻 RepoAgent 的线条流向) */
  .flow-svg {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
    z-index: 10;
  }
</style>
</head>
<body>

  <!-- 矢量连线与闭环流向 (完全对标 RepoAgent) -->
  <svg class="flow-svg" xmlns="http://www.w3.org/2000/svg">
    <!-- 1号箭头: 位于 ① 下方 -->
    <path d="M 495 138 L 528 138" fill="none" stroke="#2872e1" stroke-width="3.5" stroke-linecap="round"/>
    <path d="M 520 131 L 530 138 L 520 145" fill="none" stroke="#2872e1" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>

    <!-- 2号箭头: 位于 ② 下方 -->
    <path d="M 945 158 L 980 158" fill="none" stroke="#2872e1" stroke-width="3.5" stroke-linecap="round"/>
    <path d="M 972 151 L 982 158 L 972 165" fill="none" stroke="#2872e1" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>

    <!-- 3号曲线与箭头: 从 LLMs 边侧优雅卷曲向上指向 Human Feedback & Structure -->
    <path d="M 970 680 C 930 680 915 645 918 610" fill="none" stroke="#2872e1" stroke-width="3.5" stroke-linecap="round"/>
    <path d="M 910 622 L 918 608 L 926 620" fill="none" stroke="#2872e1" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>

    <!-- 4号箭头: 位于 ④ 上方，指向 Markdown -->
    <path d="M 526 470 L 492 470" fill="none" stroke="#2872e1" stroke-width="3.5" stroke-linecap="round"/>
    <path d="M 500 463 L 490 470 L 500 477" fill="none" stroke="#2872e1" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>

    <!-- Structure 底部的棕色弧形回路箭头 (RepoAgent 同款) -->
    <path d="M 720 605 C 700 635 770 635 750 605" fill="none" stroke="#c97322" stroke-width="3" stroke-linecap="round"/>
    <path d="M 742 615 L 750 604 L 758 615" fill="none" stroke="#c97322" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>

    <!-- Human Feedback 向上指向 Structure 的紫色虚线箭头 (RepoAgent 同款) -->
    <path d="M 735 628 L 735 608" fill="none" stroke="#8b5cf6" stroke-width="3" stroke-dasharray="4,4" stroke-linecap="round"/>

    <!-- 闭环虚线: 从 Markdown 顶部穿出向上，穿入 Git + Pre-commit 并最终抵达 Github Repository -->
    <path d="M 256 352 L 256 328" fill="none" stroke="#2872e1" stroke-width="3" stroke-dasharray="6,6" stroke-linecap="round"/>
    <path d="M 256 288 L 256 260" fill="none" stroke="#2872e1" stroke-width="3" stroke-dasharray="6,6" stroke-linecap="round"/>
    <path d="M 249 274 L 256 260 L 263 274" fill="#2872e1"/>

    <!-- Git + Pre-commit 顶部右侧蓝色虚线向上 -->
    <path d="M 390 288 L 390 260" fill="none" stroke="#2872e1" stroke-width="3" stroke-dasharray="6,6" stroke-linecap="round"/>
    <path d="M 383 274 L 390 260 L 397 274" fill="#2872e1"/>
  </svg>

  <!-- 步骤序号圆圈徽标 ① ② ③ ④ (完美复刻 RepoAgent) -->
  <div class="step-badge" style="top: 75px; left: 490px;">1</div>
  <div class="step-badge" style="top: 96px; left: 940px;">2</div>
  <div class="step-badge" style="top: 616px; left: 938px;">3</div>
  <div class="step-badge" style="top: 492px; left: 486px;">4</div>

  <!-- ==================== 1. 顶部左侧: Github Repository / TeamWork ==================== -->
  <div class="diagram-box border-blue box-github">
    <div class="github-header">
      <!-- Github Octocat 矢量图标 (RepoAgent 同款) -->
      <svg width="46" height="46" viewBox="0 0 24 24" fill="#2872e1">
        <path fill-rule="evenodd" clip-rule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"/>
      </svg>
      <div class="github-title">Github Repository</div>
    </div>

    <div class="github-divider"></div>

    <div class="teamwork-row">
      <!-- TeamWork 矢量图标 (RepoAgent 同款: 实心蓝人物 + 空心蓝人物群体) -->
      <svg width="60" height="50" viewBox="0 0 40 30" fill="none">
        <!-- 实体人像群 (左侧) -->
        <circle cx="8" cy="10" r="4" fill="#2872e1"/>
        <path d="M1 24 C1 18 4 16 8 16 C12 16 15 18 15 24" fill="#2872e1"/>
        <circle cx="16" cy="8" r="3.5" fill="#2872e1"/>
        <path d="M11 24 C11 19 13 17 16 17 C19 17 21 19 21 24" fill="#2872e1"/>
        
        <!-- 空心描边人像群 (右侧) -->
        <circle cx="26" cy="9" r="3.5" stroke="#2872e1" stroke-width="2.5"/>
        <path d="M21 24 C21 18.5 23.5 17 26 17 C28.5 17 31 18.5 31 24" stroke="#2872e1" stroke-width="2.5"/>
        <circle cx="33" cy="11" r="3" stroke="#2872e1" stroke-width="2"/>
        <path d="M29 24 C29 20 31 19 33 19 C35 19 37 20 37 24" stroke="#2872e1" stroke-width="2"/>
      </svg>
      <div class="teamwork-title">TeamWork</div>
    </div>
  </div>

  <!-- ==================== 2. 顶部中间: Independent Developer ==================== -->
  <div class="diagram-box border-blue box-developer">
    <div class="dev-left">
      <div class="dev-title">Independent<br>Developer</div>
      <div class="dev-icons">
        <!-- VS Code 蓝徽标 -->
        <div class="icon-badge" style="background: #007acc;">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M17.5 2L6.5 10.5L2 7L0 8.5L4 12L0 15.5L2 17L6.5 13.5L17.5 22L24 19V5L17.5 2ZM18 16.5L9.5 12L18 7.5V16.5Z"/></svg>
        </div>
        <!-- PyCharm 绿黑徽标 -->
        <div class="icon-badge" style="background: #21d789; font-family: monospace; font-size: 13px; font-weight: 900; color: #000;">
          PC
        </div>
        <!-- Claude Code / JetBrains 标 -->
        <div class="icon-badge" style="background: #d97706; font-family: 'JetBrains Mono', monospace; font-size: 11px; font-weight: 800; color: #ffffff;">
          CC
        </div>
      </div>
    </div>

    <div class="dev-divider-dashed"></div>

    <!-- 程序员打字插画 (RepoAgent 同款可爱画风) -->
    <svg class="dev-illustration" viewBox="0 0 100 100" fill="none">
      <!-- 电脑显示器 -->
      <rect x="18" y="32" width="48" height="34" rx="3" fill="#ffffff" stroke="#1f242b" stroke-width="2.5"/>
      <rect x="23" y="36" width="38" height="24" fill="#e2e8f0"/>
      <!-- 代码点阵彩色线条 -->
      <line x1="26" y1="42" x2="38" y2="42" stroke="#2563eb" stroke-width="2"/>
      <line x1="26" y1="47" x2="52" y2="47" stroke="#059669" stroke-width="2"/>
      <line x1="26" y1="52" x2="44" y2="52" stroke="#d97706" stroke-width="2"/>
      <!-- 电脑底座支架 -->
      <path d="M 37 66 L 47 66 L 45 74 L 39 74 Z" fill="#1f242b"/>
      <rect x="29" y="74" width="28" height="4" rx="1" fill="#1f242b"/>
      <!-- 键盘 -->
      <rect x="15" y="80" width="54" height="6" rx="2" fill="#ffffff" stroke="#1f242b" stroke-width="2"/>
      <!-- 人物头与头发 -->
      <circle cx="76" cy="30" r="14" fill="#fed7aa" stroke="#1f242b" stroke-width="2.5"/>
      <path d="M 64 24 C 64 16 75 13 84 17 C 90 20 89 28 88 32 C 84 28 78 27 74 30 Z" fill="#633806"/>
      <circle cx="72" cy="28" r="2" fill="#1f242b"/>
      <path d="M 69 34 Q 73 38 77 34" stroke="#1f242b" stroke-width="2" stroke-linecap="round"/>
      <!-- 人物躯干与双手打字 -->
      <path d="M 64 44 C 64 42 70 42 78 42 C 86 42 90 46 90 56 L 80 58 L 74 46 Z" fill="#2872e1" stroke="#1f242b" stroke-width="2.5"/>
      <path d="M 74 46 L 56 60 L 52 76" fill="none" stroke="#1f242b" stroke-width="3.5" stroke-linecap="round"/>
      <circle cx="50" cy="78" r="3.5" fill="#fed7aa"/>
    </svg>
  </div>

  <!-- ==================== Code Update 药丸按钮 (RepoAgent 同款) ==================== -->
  <div class="box-code-update">
    <!-- 刷新同步图标 -->
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#b91c1c" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
      <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
    </svg>
    <span>ctxguard wrap (Code Update)</span>
  </div>

  <!-- ==================== 中间条: Git + Pre - commit ==================== -->
  <div class="bar-git-commit">
    <span class="bar-git-text">Git + Pre - commit (Reverse Proxy &amp; Two-Stage SSE Check)</span>
  </div>

  <!-- ==================== 3. 右侧主容器: CtxGuard (RepoAgent 绿框) ==================== -->
  <div class="diagram-box border-green box-repoagent">
    <div>
      <div class="repoagent-header">
        <!-- 绿圈双环 / 无限大图标 (RepoAgent 同款) -->
        <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="#007e54" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M18.178 8c5.096 0 5.096 8 0 8-5.095 0-7.133-8-12.228-8-5.096 0-5.096 8 0 8 5.095 0 7.133-8 12.228-8z"/>
        </svg>
        <div class="repoagent-title">CtxGuard</div>
        <div class="repoagent-port">:8787</div>
      </div>

      <!-- 核心网格卡片组 (RepoAgent 同款卡片与配色) -->
      <div class="modules-grid">
        <!-- 1: Change Detector / Tree-sitter AST (黄色) -->
        <div class="mod-card card-yellow">
          <div class="mod-title">Tree-sitter<br>AST</div>
          <div class="mod-subtitle">9+ Langs Skeleton</div>
        </div>

        <!-- 2: File Handler / Tool Delta (橙色) -->
        <div class="mod-card card-orange">
          <div class="mod-title">Tool Delta<br>Engine</div>
          <div class="mod-subtitle">Jaccard Diff (-90%)</div>
        </div>

        <!-- 3: Bi-direct Reference Retriever / Log Truncator (浅蓝) -->
        <div class="mod-card card-blue">
          <div class="mod-title">Log Head-Tail<br>Truncator</div>
          <div class="mod-subtitle">Head 25 / Tail 75</div>
        </div>

        <!-- 4: Parallel Chat-Engine / Thinking Manager (浅蓝) -->
        <div class="mod-card card-blue">
          <div class="mod-title">Thinking<br>Manager</div>
          <div class="mod-subtitle">0 Signature Error</div>
        </div>

        <!-- 点点点 -->
        <div class="dots-row">
          <span>•••</span>
          <span>•••</span>
        </div>
        <div class="dots-row">
          <span>•••</span>
          <span>•••</span>
        </div>

        <!-- 5: Muti-linguistic / Secret Redactor (粉紫) -->
        <div class="mod-card card-purple">
          <div class="mod-title">Secret<br>Redactor</div>
          <div class="mod-subtitle">API Keys / PEM</div>
        </div>

        <!-- 6: Auto-Commit / CCR Interceptor (绿卡) -->
        <div class="mod-card card-green">
          <div class="mod-title">CCR Auto-<br>Continuation</div>
          <div class="mod-subtitle">0-Token Expand</div>
        </div>

        <!-- 7: Prompt Cache Guard (全宽浅青色卡片) -->
        <div class="mod-card card-cyan" style="grid-column: span 2; min-height: 64px;">
          <div class="mod-title" style="font-size: 13.5px; margin-bottom: 2px;">Prompt Cache Guard &amp; Schema Sorter</div>
          <div class="mod-subtitle">0-Copy Binary Slices • 100% KV Cache Stability</div>
        </div>
      </div>
    </div>

    <!-- 底部 LLMs 卡片 (RepoAgent 红卡) -->
    <div class="card-llms">
      <div class="llms-title">LLMs</div>
      <div class="llms-sub">100% KV Cache Stability • 50%~88% Net Savings</div>
      <div class="llms-tags">
        <span class="llm-badge">Claude 3.7/4</span>
        <span class="llm-badge">Gemini 3.8</span>
        <span class="llm-badge">GPT-5.6</span>
        <span class="llm-badge">DeepSeek R1</span>
      </div>
    </div>
  </div>

  <!-- ==================== 4. 左下角: Markdown 代码对比框 (RepoAgent 黑色卡片) ==================== -->
  <div class="diagram-box border-dark box-markdown">
    <div class="markdown-header">
      <div class="markdown-icon-box">
        <span>M↓</span>
      </div>
      <div class="markdown-title">Markdown (Context Diff)</div>
    </div>

    <div class="markdown-columns">
      <!-- 左蓝卡: 旧结构 (Raw 膨胀上下文) -->
      <div class="code-sheet">
        <div class="sheet-title">
          <span>Raw Context</span>
          <span class="code-red">12,500 Tok</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Func Func_A</span>
          <span class="code-doc">120 lines raw body</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Class class_A</span>
          <span class="code-doc">All method codes</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Func func_B</span>
          <span class="code-doc">Unchanged scan probe</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Func func_C</span>
          <span class="code-doc">1,850 lines test logs</span>
        </div>
        <div style="text-align: center; color: #1f242b; font-weight: 900; font-size: 16px;">••• •••</div>
        <div class="code-item">
          <span class="code-fn">Func func_D</span>
          <span class="code-doc">Random Tool Schemas</span>
        </div>
      </div>

      <!-- 中间箭头 -->
      <div class="sheet-arrow">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="#e5ad35">
          <path d="M 4 8 L 14 8 L 14 4 L 22 12 L 14 20 L 14 16 L 4 16 Z"/>
        </svg>
      </div>

      <!-- 右蓝卡: 新结构 (CtxGuard 优化后带红色新增与划线删除) -->
      <div class="code-sheet">
        <div class="sheet-title">
          <span>CtxGuard Stream</span>
          <span class="code-green">2,800 Tok</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Func Func_A</span>
          <span class="code-doc code-red">Doc of func_A (Skeleton)</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Class class_A</span>
          <span class="code-doc">[ctx_expand ref]</span>
        </div>
        <div class="code-item">
          <span class="code-fn code-strike">Func func_B</span>
          <span class="code-doc code-strike">Doc of func_B (Folded)</span>
        </div>
        <div class="code-item">
          <span class="code-fn">Func func_C</span>
          <span class="code-doc code-green">Head 25 / Tail 75</span>
        </div>
        <div style="text-align: center; color: #1f242b; font-weight: 900; font-size: 16px;">••• •••</div>
        <div class="code-item">
          <span class="code-fn code-red">Func func_H (New)</span>
          <span class="code-doc code-red">Sorted Schemas (Locked)</span>
        </div>
      </div>
    </div>
  </div>

  <!-- ==================== 5. 中间下: Repository Structure (橙色卡) ==================== -->
  <div class="diagram-box border-orange box-structure">
    <div class="structure-header">Repository Structure</div>
    <div class="structure-body">
      <!-- 树形图 SVG (RepoAgent 同款) -->
      <svg class="tree-icon-svg" viewBox="0 0 100 100" fill="none">
        <circle cx="25" cy="50" r="14" fill="#ffffff" stroke="#64748b" stroke-width="4"/>
        <circle cx="25" cy="50" r="6" fill="#64748b"/>
        <path d="M 39 50 L 58 50" stroke="#64748b" stroke-width="4" stroke-linecap="round"/>
        <path d="M 58 28 L 58 72" stroke="#64748b" stroke-width="4" stroke-linecap="round"/>
        <path d="M 58 28 L 72 28" stroke="#64748b" stroke-width="4" stroke-linecap="round"/>
        <path d="M 58 72 L 72 72" stroke="#64748b" stroke-width="4" stroke-linecap="round"/>
        <rect x="72" y="18" width="20" height="20" rx="3" fill="#ffffff" stroke="#64748b" stroke-width="4"/>
        <rect x="72" y="62" width="20" height="20" rx="3" fill="#ffffff" stroke="#64748b" stroke-width="4"/>
      </svg>

      <!-- 字段列表 -->
      <ul class="structure-bullets">
        <li>hot_lru_fingerprints</li>
        <li>sqlite_wal_database</li>
        <li>temporal_kg_graph</li>
        <li>start_line_frozen</li>
        <li>end_line_delta</li>
      </ul>
    </div>
  </div>

  <!-- ==================== 6. 中间底: Human Feedback (灰色虚线框) ==================== -->
  <div class="diagram-box border-dashed-gray box-feedback">
    <div class="feedback-header">
      <span>Human Feedback (ctxguard learn)</span>
    </div>
    <div class="feedback-body">
      <!-- 人物反馈图标 (RepoAgent 同款: 读书/看文档的人物剪影) -->
      <svg class="feedback-icon-svg" viewBox="0 0 80 80" fill="none">
        <circle cx="34" cy="24" r="12" fill="#a78bfa"/>
        <!-- 躯干 -->
        <path d="M 22 42 C 22 36 28 34 38 34 C 48 34 54 38 54 46 L 50 64 L 32 64 Z" fill="#a78bfa"/>
        <!-- 书本/平板 -->
        <path d="M 38 46 L 58 38 L 66 60 L 46 66 Z" fill="#ffffff" stroke="#a78bfa" stroke-width="3"/>
        <line x1="44" y1="49" x2="56" y2="44" stroke="#8b5cf6" stroke-width="2"/>
        <line x1="47" y1="56" x2="59" y2="51" stroke="#8b5cf6" stroke-width="2"/>
      </svg>

      <!-- 反馈列表 -->
      <ul class="feedback-bullets">
        <li>LogScanner Trajectory</li>
        <li>LoopDetector Dead-Loops</li>
        <li>CausalityPivot Rules</li>
        <li>AGENTS.md Auto-Carry</li>
        <li>Physical Token Savings</li>
      </ul>
    </div>
  </div>

</body>
</html>
"""

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    html_file = os.path.join(script_dir, "render_diagram.html")
    png_file = os.path.join(script_dir, "architecture_diagram.png")

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(HTML_CONTENT)
    print(f"[+] Wrote template to {html_file}")

    chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_bin):
        print(f"[-] Google Chrome not found at {chrome_bin}")
        sys.exit(1)

    cmd = [
        chrome_bin,
        "--headless=new",
        "--disable-gpu",
        "--force-device-scale-factor=2",
        "--window-size=1440,960",
        f"--screenshot={png_file}",
        html_file
    ]
    print(f"[+] Rendering {png_file} at 2x Retina resolution...")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0 and os.path.exists(png_file):
        print(f"[✓] Rendered successfully! Size: {os.path.getsize(png_file)} bytes")
    else:
        print(f"[-] Render failed! stderr: {res.stderr}")
        sys.exit(1)

if __name__ == "__main__":
    main()
