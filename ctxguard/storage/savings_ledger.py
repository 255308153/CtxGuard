"""Durable append-only savings event ledger for CtxGuard.

Every optimization — proxy context compression and semantic cache hits —
appends a single JSON line to a file-locked JSONL ledger.
Unlike in-memory stats or database-specific locks, this ledger survives restarts
and is safe across concurrent processes (the proxy gateway, multiple worker processes,
and subagents all append to the same file under an advisory lock).

Cost is computed and stored at write time so historical numbers do not drift if
model pricing changes later.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Advisory file lock (fcntl on Unix)
_HAS_FCNTL = False
try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    fcntl = None  # type: ignore

SCHEMA_VERSION = 1
UNKNOWN = "unknown"
DEFAULT_RETENTION_DAYS = 30
MAX_RETENTION_DAYS = 30
# Blended fallback input price ($/token) when model cannot be identified: $3.0 / 1M tokens
DEFAULT_FALLBACK_INPUT_COST_PER_TOKEN = 3.0 / 1_000_000

# File compaction threshold (1 MB)
_COMPACT_SIZE_BYTES = 1 * 1024 * 1024

# Model input pricing per million tokens
MODEL_PRICING_PER_MILLION: Dict[str, float] = {
    "claude-3-5-sonnet": 3.00,
    "claude-3-7-sonnet": 3.00,
    "claude-3-5-haiku": 0.80,
    "claude-3-opus": 15.00,
    "gpt-4o": 2.50,
    "gpt-4o-mini": 0.15,
    "gpt-4-turbo": 10.00,
    "deepseek-chat": 0.14,
    "deepseek-coder": 0.14,
    "deepseek-flash": 0.14,
    "gemini-1.5-flash": 0.075,
    "gemini-1.5-pro": 1.25,
    "gemini-2.0-flash": 0.10,
    "gemini-2.5-pro": 1.25,
    "gemini-3.7-flash-high": 0.15,
    "gemini-3.8-flash-high": 0.15,
}

# Explicitly free models (0.0 cost)
FREE_MODEL_PREFIXES = ("ollama", "local", "custom", "test")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def resolve_savings_path(path: str | os.PathLike[str] | None = None) -> Path:
    """Resolve destination path for the savings events ledger."""
    if path:
        return Path(path).expanduser().resolve()
    env_path = os.environ.get("CTXGUARD_SAVINGS_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()
    # If local workspace ledger exists, prefer it
    local_ledger = (Path.cwd() / ".ctxguard" / "savings_events.jsonl").resolve()
    if local_ledger.exists():
        return local_ledger
    # Next check home directory ~/.ctxguard
    home_dir = Path.home() / ".ctxguard"
    try:
        home_dir.mkdir(parents=True, exist_ok=True)
        return (home_dir / "savings_events.jsonl").resolve()
    except (PermissionError, OSError):
        return local_ledger


def normalize_model_name(model: Any) -> str:
    if not isinstance(model, str) or not model.strip():
        return UNKNOWN
    return model.strip().lower()


def normalize_client_name(client: Any) -> str:
    if not isinstance(client, str) or not client.strip():
        return UNKNOWN
    cleaned = client.strip()
    return cleaned if cleaned else UNKNOWN


def estimate_cost_usd(
    model: str,
    tokens_saved: int,
    fallback_rate: float = DEFAULT_FALLBACK_INPUT_COST_PER_TOKEN,
) -> float:
    """Calculate the dollar value of saved input tokens.
    
    Uses standard catalog pricing when recognized.
    For local/free models, returns $0.0.
    For unknown models, falls back to conservative blended rate ($3/M) rather than $0.
    """
    if tokens_saved <= 0:
        return 0.0

    model_clean = normalize_model_name(model)
    if model_clean == UNKNOWN:
        return round(float(tokens_saved) * float(fallback_rate), 6)

    # Check for free models
    for prefix in FREE_MODEL_PREFIXES:
        if model_clean.startswith(prefix):
            return 0.0

    # Match pricing
    for key, price_per_m in MODEL_PRICING_PER_MILLION.items():
        if key in model_clean:
            return round((float(tokens_saved) / 1_000_000.0) * price_per_m, 6)

    # Unknown paid model -> fallback rate
    return round(float(tokens_saved) * float(fallback_rate), 6)


def record_savings_event(
    *,
    tokens_before: int,
    tokens_after: int,
    model: Any = None,
    client: Any = None,
    source: str = "proxy",
    timestamp: Any = None,
    cost_usd: Optional[float] = None,
    fallback_rate: float = DEFAULT_FALLBACK_INPUT_COST_PER_TOKEN,
    path: str | os.PathLike[str] | None = None,
) -> bool:
    """Append one savings event to the durable ledger under advisory lock.
    
    Never raises an exception. Returns True if written successfully.
    """
    try:
        before = max(int(tokens_before), 0)
        after = max(int(tokens_after), 0)
    except (TypeError, ValueError):
        return False

    saved = max(before - after, 0)
    if saved <= 0:
        return False

    model_label = normalize_model_name(model)
    client_label = normalize_client_name(client)

    if cost_usd is None:
        cost = estimate_cost_usd(model_label, saved, fallback_rate=fallback_rate)
    else:
        try:
            cost = max(float(cost_usd), 0.0)
        except (TypeError, ValueError):
            cost = 0.0

    ts_dt = _parse_timestamp(timestamp) or _utc_now()

    event = {
        "v": SCHEMA_VERSION,
        "ts": ts_dt.isoformat(),
        "before": before,
        "after": after,
        "saved": saved,
        "cost_usd": round(cost, 6),
        "model": model_label,
        "client": client_label,
        "source": str(source or UNKNOWN),
        "pid": os.getpid(),
    }

    target = resolve_savings_path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, separators=(",", ":")) + "\n"
        with open(target, "a", encoding="utf-8") as handle:
            if _HAS_FCNTL and fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                handle.write(line)
                handle.flush()
            finally:
                if _HAS_FCNTL and fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    except Exception:
        return False

    _maybe_compact(target)
    return True


def _read_events(
    path: str | os.PathLike[str] | None,
    *,
    retention_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    target = resolve_savings_path(path)
    if not target.exists():
        return []

    cutoff = now - timedelta(days=retention_days) if retention_days else None
    events: list[dict[str, Any]] = []

    try:
        with open(target, "r", encoding="utf-8") as handle:
            if _HAS_FCNTL and fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_SH)
            try:
                for line in handle:
                    raw = line.strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except Exception:
                        continue
                    parsed = _parse_timestamp(event.get("ts"))
                    if parsed is None:
                        continue
                    if cutoff is not None and parsed < cutoff:
                        continue
                    event["_ts"] = parsed
                    events.append(event)
            finally:
                if _HAS_FCNTL and fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    except Exception:
        return []

    return events


def _maybe_compact(target: Path) -> None:
    """Compact the ledger if file size exceeds threshold, removing expired events."""
    try:
        if not target.exists() or target.stat().st_size < _COMPACT_SIZE_BYTES:
            return
        now = _utc_now()
        events = _read_events(target, retention_days=DEFAULT_RETENTION_DAYS, now=now)
        tmp_target = target.with_suffix(".tmp")
        with open(tmp_target, "w", encoding="utf-8") as handle:
            if _HAS_FCNTL and fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                for event in events:
                    event_copy = {k: v for k, v in event.items() if not k.startswith("_")}
                    handle.write(json.dumps(event_copy, separators=(",", ":")) + "\n")
                handle.flush()
            finally:
                if _HAS_FCNTL and fcntl is not None:
                    fcntl.flock(handle, fcntl.LOCK_UN)
        os.replace(tmp_target, target)
    except Exception:
        pass


@dataclass
class _Bucket:
    tokens_saved: int = 0
    tokens_before: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, *, saved: int, before: int, cost: float) -> None:
        self.tokens_saved += saved
        self.tokens_before += before
        self.cost_usd += cost
        self.calls += 1

    @property
    def savings_percent(self) -> float:
        if self.tokens_before <= 0:
            return 0.0
        return round((self.tokens_saved / self.tokens_before) * 100, 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tokens_saved": self.tokens_saved,
            "tokens_before": self.tokens_before,
            "cost_usd": round(self.cost_usd, 6),
            "calls": self.calls,
            "savings_percent": self.savings_percent,
        }


@dataclass
class SavingsReport:
    path: str
    schema_version: int
    lifetime: dict[str, Any]
    windows: dict[str, dict[str, Any]]
    by_model: list[dict[str, Any]]
    by_client: list[dict[str, Any]]
    top_model: str = UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "path": self.path,
            "top_model": self.top_model,
            "lifetime": self.lifetime,
            "windows": self.windows,
            "by_model": self.by_model,
            "by_client": self.by_client,
        }


def aggregate_savings(
    path: str | os.PathLike[str] | None = None,
    *,
    now: Optional[datetime] = None,
    retention_days: int = DEFAULT_RETENTION_DAYS,
) -> SavingsReport:
    """Aggregate the durable ledger into lifetime / windowed / per-dimension views."""
    now = now or _utc_now()
    retention_days = max(1, min(retention_days or MAX_RETENTION_DAYS, MAX_RETENTION_DAYS))
    events = _read_events(path, retention_days=retention_days, now=now)

    today_cutoff = (
        now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    )
    week_cutoff = now - timedelta(days=7)

    lifetime = _Bucket()
    today = _Bucket()
    last_7 = _Bucket()
    last_30 = _Bucket()
    by_model: dict[str, _Bucket] = {}
    by_client: dict[str, _Bucket] = {}

    for event in events:
        ts: datetime = event["_ts"]
        saved = max(int(event.get("saved", 0) or 0), 0)
        before = max(int(event.get("before", 0) or 0), 0)
        cost = max(float(event.get("cost_usd", 0.0) or 0.0), 0.0)
        model = str(event.get("model", UNKNOWN) or UNKNOWN)
        client = str(event.get("client", UNKNOWN) or UNKNOWN)

        lifetime.add(saved=saved, before=before, cost=cost)
        last_30.add(saved=saved, before=before, cost=cost)

        if ts >= today_cutoff:
            today.add(saved=saved, before=before, cost=cost)
        if ts >= week_cutoff:
            last_7.add(saved=saved, before=before, cost=cost)

        if model not in by_model:
            by_model[model] = _Bucket()
        by_model[model].add(saved=saved, before=before, cost=cost)

        if client not in by_client:
            by_client[client] = _Bucket()
        by_client[client].add(saved=saved, before=before, cost=cost)

    # Sort by_model descending by cost_usd, then tokens_saved
    ranked_models = []
    for m_name, bucket in by_model.items():
        row = {"model": m_name, **bucket.to_dict()}
        ranked_models.append(row)
    ranked_models.sort(key=lambda r: (r["cost_usd"], r["tokens_saved"]), reverse=True)

    # Sort by_client descending by tokens_saved
    ranked_clients = []
    for c_name, bucket in by_client.items():
        row = {"client": c_name, **bucket.to_dict()}
        ranked_clients.append(row)
    ranked_clients.sort(key=lambda r: (r["tokens_saved"], r["calls"]), reverse=True)

    top_model = ranked_models[0]["model"] if ranked_models else UNKNOWN

    return SavingsReport(
        path=str(resolve_savings_path(path)),
        schema_version=SCHEMA_VERSION,
        lifetime=lifetime.to_dict(),
        windows={
            "today": today.to_dict(),
            "last_7_days": last_7.to_dict(),
            "last_30_days": last_30.to_dict(),
        },
        by_model=ranked_models,
        by_client=ranked_clients,
        top_model=top_model,
    )
