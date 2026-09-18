"""记录上游报告缓存读取为零的请求，便于定位缓存失效原因。"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from ctxguard.config.schema import SecretRedactorConfig
from ctxguard.core.compressors.secret_redactor import SecretRedactor

_REDACTOR = SecretRedactor(SecretRedactorConfig())


def _redact(value: Any) -> Any:
    """递归脱敏事件树中的所有字符串，防止密钥/凭证明文落盘。"""
    if isinstance(value, str):
        return _REDACTOR.mask_text(value)
    if isinstance(value, dict):
        return {str(k): _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    """把消息、字节和其他运行时对象转换为可落盘的 JSON 值。"""
    if hasattr(value, "to_dict"):
        return _jsonable(value.to_dict())
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


class CacheZeroRecorder:
    """异步追加缓存零事件，避免磁盘写入阻塞代理请求。"""

    def __init__(self, directory: str = ".ctxguard/cache_zero", enabled: bool = True):
        self.directory = Path(directory).expanduser()
        self.enabled = enabled
        self._write_lock = threading.Lock()

    def record_async(
        self,
        *,
        session_id: str,
        protocol: str,
        model: str,
        provider: str,
        project_name: str,
        request: Any,
        current_messages: Iterable[Any],
        previous_turn: Optional[dict[str, Any]],
        cached_tokens: int = 0,
        cache_type: str = "none",
        prompt_tokens: Optional[int] = None,
        request_id: Optional[int] = None,
        applied_compressors: Optional[Iterable[str]] = None,
        reason: str = "upstream_reported_zero",
    ) -> None:
        if not self.enabled:
            return
        event = {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "protocol": protocol,
            "model": model,
            "provider": provider,
            "project_name": project_name,
            "request_id": request_id,
            "cached_tokens": int(cached_tokens or 0),
            "prompt_tokens": prompt_tokens,
            "cache_type": cache_type or "none",
            "reason": reason,
            "applied_compressors": list(applied_compressors or []),
            "input_context": _jsonable(getattr(request, "raw_payload", None) or request),
            "current_messages": _jsonable(list(current_messages)),
            "previous_turn": _jsonable(previous_turn),
        }
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._write(event)
            return
        loop.create_task(asyncio.to_thread(self._write, event))

    def _write(self, event: dict[str, Any]) -> None:
        try:
            event = _redact(event)
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / f"cache-zero-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
            line = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            with self._write_lock, path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except Exception:
            # 诊断记录失败不能影响上游响应。
            return
