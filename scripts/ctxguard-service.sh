#!/bin/bash
# CtxGuard 网关常驻服务控制脚本（macOS LaunchAgent）
#
# 用法:  ./scripts/ctxguard-service.sh install|uninstall|status|restart|stop|logs
#
# 说明:  必须在「你自己的终端」里运行（需要能访问用户 GUI 会话的 launchd 域）。
#        脚本运行时假设你已登录桌面会话，未通过 sudo 执行。

set -euo pipefail

LABEL="com.ctxguard.gateway"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
OUT_LOG="$HOME/Library/Logs/ctxguard-gateway.log"
ERR_LOG="$HOME/Library/Logs/ctxguard-gateway.error.log"

require_plist() {
  if [ ! -f "$PLIST" ]; then
    echo "✗ 未找到 $PLIST" >&2
    exit 1
  fi
}

case "${1:-}" in
  install)
    require_plist
    mkdir -p "$HOME/Library/Logs"
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "✓ 已注册并启动 $LABEL"
    sleep 3
    launchctl print "$DOMAIN/$LABEL" | grep -E "state|pid" || true
    echo "  面板: http://127.0.0.1:8787"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    echo "✓ 已停止并注销 $LABEL（plist 保留在 $PLIST，删除该文件即可彻底移除）"
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      launchctl print "$DOMAIN/$LABEL" | grep -E "state|pid|last exit|runs" || true
    else
      echo "未注册（launchd 未托管）"
    fi
    echo "--- 8787 端口 ---"
    lsof -nP -iTCP:8787 -sTCP:LISTEN 2>/dev/null || echo "无监听"
    echo "--- 健康检查 ---"
    curl -s --noproxy '*' -o /dev/null -w "HTTP %{http_code}\n" --max-time 5 http://127.0.0.1:8787/ || echo "无响应"
    ;;
  restart)
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "✓ 已重启 $LABEL"
    ;;
  stop)
    launchctl kill SIGTERM "$DOMAIN/$LABEL" 2>/dev/null || true
    echo "✓ 已发送 SIGTERM（KeepAlive 会自动拉起，如需彻底停止请用 uninstall）"
    ;;
  logs)
    tail -n "${2:-80}" "$OUT_LOG" 2>/dev/null || echo "(暂无 $OUT_LOG)"
    if [ -s "$ERR_LOG" ]; then
      echo "--- stderr (末尾 40 行) ---"
      tail -n 40 "$ERR_LOG"
    fi
    ;;
  *)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
