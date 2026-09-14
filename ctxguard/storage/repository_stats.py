"""Repository for logging request metrics and aggregating savings statistics."""

import json
from typing import Any, Dict, List
from ctxguard.storage.db import DatabaseManager


# Approximate Input pricing per million tokens for popular models
MODEL_PRICING_PER_MILLION: Dict[str, float] = {
    "claude-3-5-sonnet": 3.00,
    "claude-3-5-haiku": 0.80,
    "claude-3-opus": 15.00,
    "gpt-4o": 2.50,
    "gpt-4o-mini": 0.15,
    "gpt-4-turbo": 10.00,
    "deepseek-chat": 0.14,
    "deepseek-coder": 0.14,
    "default": 3.00,
}


class StatsRepository:
    """Manages request metrics logging and aggregate statistical analysis."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def record_request(
        self,
        session_id: str,
        protocol: str,
        model: str,
        raw_tokens: int,
        optimized_tokens: int,
        latency_ms: float,
        applied_compressors: List[str],
    ) -> None:
        """Record a completed request metric."""
        saved_tokens = max(0, raw_tokens - optimized_tokens)
        saved_ratio = round((saved_tokens / max(1, raw_tokens)) * 100, 2)

        with self.db.get_connection() as conn:
            # Ensure session exists
            conn.execute(
                """
                INSERT INTO sessions (session_id, updated_at)
                VALUES (?, CURRENT_TIMESTAMP)
                ON CONFLICT(session_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
                """,
                (session_id,),
            )
            # Insert request log
            conn.execute(
                """
                INSERT INTO requests (
                    session_id, protocol, model, raw_tokens, optimized_tokens,
                    saved_tokens, saved_ratio, latency_ms, applied_compressors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    protocol,
                    model,
                    raw_tokens,
                    optimized_tokens,
                    saved_tokens,
                    saved_ratio,
                    latency_ms,
                    json.dumps(applied_compressors),
                ),
            )
            conn.commit()

    def get_summary(self) -> Dict[str, Any]:
        """Aggregate total token savings, request counts, and latency averages."""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT
                    COUNT(*) as total_requests,
                    COALESCE(SUM(raw_tokens), 0) as total_raw_tokens,
                    COALESCE(SUM(optimized_tokens), 0) as total_optimized_tokens,
                    COALESCE(SUM(saved_tokens), 0) as total_saved_tokens,
                    COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms
                FROM requests
                """
            )
            row = cursor.fetchone()
            if not row or row["total_requests"] == 0:
                return {
                    "total_requests": 0,
                    "total_raw_tokens": 0,
                    "total_optimized_tokens": 0,
                    "total_saved_tokens": 0,
                    "overall_saved_percent": 0.0,
                    "avg_latency_ms": 0.0,
                    "estimated_dollars_saved": 0.0,
                }

            total_raw = row["total_raw_tokens"]
            total_saved = row["total_saved_tokens"]
            saved_percent = round((total_saved / max(1, total_raw)) * 100, 2)
            dollars_saved = self._calculate_dollar_savings()

            return {
                "total_requests": row["total_requests"],
                "total_raw_tokens": total_raw,
                "total_optimized_tokens": row["total_optimized_tokens"],
                "total_saved_tokens": total_saved,
                "overall_saved_percent": saved_percent,
                "avg_latency_ms": round(row["avg_latency_ms"], 2),
                "estimated_dollars_saved": round(dollars_saved, 4),
            }

    def _calculate_dollar_savings(self) -> float:
        """Calculate dollars saved across different models."""
        total_dollars = 0.0
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT model, SUM(saved_tokens) as model_saved_tokens
                FROM requests
                GROUP BY model
                """
            )
            for row in cursor.fetchall():
                model_name = row["model"].lower()
                saved_tokens = row["model_saved_tokens"]
                # Match price
                price_per_m = MODEL_PRICING_PER_MILLION.get("default", 3.00)
                for key, price in MODEL_PRICING_PER_MILLION.items():
                    if key in model_name:
                        price_per_m = price
                        break
                total_dollars += (saved_tokens / 1_000_000.0) * price_per_m

        return total_dollars

    def get_recent_requests(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Retrieve recent request records."""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, timestamp, protocol, model,
                       raw_tokens, optimized_tokens, saved_tokens, saved_ratio, latency_ms
                FROM requests
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
