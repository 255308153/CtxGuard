import os
import sys
import shutil
import subprocess
import time
import urllib.request
from typing import List

from ctxguard.utils.console import Console

def _ensure_proxy_running(port: int = 8787) -> None:
    """Ensure CtxGuard gateway proxy is alive on the specified port."""
    health_url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(health_url, timeout=0.5) as resp:
            if resp.status == 200:
                return
    except Exception:
        pass

    Console.info(f"CtxGuard proxy not detected on port {port}. Starting in background...")
    # Spawn proxy daemon in background
    subprocess.Popen(
        [sys.executable, "-m", "ctxguard.cli.main", "start", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    # Wait for ready
    for _ in range(30):
        time.sleep(0.1)
        try:
            with urllib.request.urlopen(health_url, timeout=0.5) as resp:
                if resp.status == 200:
                    Console.success(f"CtxGuard proxy is ready on http://127.0.0.1:{port}")
                    return
        except Exception:
            continue
    Console.warn("Proxy start timeout, continuing launch anyway...")

def execute_wrap(args) -> None:
    agent = args.agent
    port = args.port
    extra_args = args.extra_args or []

    # 1. Ensure proxy gateway is running
    _ensure_proxy_running(port)

    # 2. Build isolated subprocess environment
    env = os.environ.copy()
    env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["OPENAI_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
    env["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{port}/v1"
    env["CTXGUARD_ACTIVE"] = "1"
    env["ENABLE_TOOL_SEARCH"] = "true"

    # 3. Find executable
    target_bin = None
    if agent == "claude":
        target_bin = shutil.which("claude")
        if not target_bin:
            Console.error("Executable 'claude' not found in PATH. Please install Claude Code first.")
            sys.exit(1)
    elif agent == "pi":
        target_bin = shutil.which("pi")
        if not target_bin:
            Console.error("Executable 'pi' not found in PATH.")
            sys.exit(1)
    elif agent == "codex":
        target_bin = shutil.which("codex")
        if not target_bin:
            Console.error("Executable 'codex' not found in PATH.")
            sys.exit(1)
    elif agent == "aider":
        target_bin = shutil.which("aider")
        if not target_bin:
            Console.error("Executable 'aider' not found in PATH.")
            sys.exit(1)
    else:
        target_bin = shutil.which(agent)
        if not target_bin:
            Console.error(f"Executable '{agent}' not found in PATH.")
            sys.exit(1)

    cmd = [target_bin] + extra_args
    Console.info(f"Launching wrapped agent: {' '.join(cmd)} (Proxy: http://127.0.0.1:{port})")

    # 4. Exec subprocess and passthrough TTY
    try:
        proc = subprocess.Popen(cmd, env=env)
        proc.wait()
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        sys.exit(0)
