"""Repository for logging request metrics and aggregating savings statistics."""

import json
import re
from typing import Any, Dict, List, Optional
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
    "deepseek-flash": 0.14,
    "gemini-1.5-flash": 0.075,
    "gemini-1.5-pro": 1.25,
    "gemini-2.0-flash": 0.10,
    "gemini-2.5-pro": 1.25,
    "gemini-3.7-flash-high": 0.15,
    "gemini-3.8-flash-high": 0.15,
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
        project_name: str = "default",
        prompt_preview: str = "",
        cached_tokens: int = 0,
        cache_type: str = "none",
    ) -> int:
        """Record a completed request metric with session, project, preview, and cache stats."""
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
            cursor = conn.execute(
                """
                INSERT INTO requests (
                    session_id, project_name, prompt_preview, protocol, model,
                    raw_tokens, optimized_tokens, saved_tokens, saved_ratio,
                    latency_ms, applied_compressors, cached_tokens, cache_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    project_name,
                    prompt_preview,
                    protocol,
                    model,
                    raw_tokens,
                    optimized_tokens,
                    saved_tokens,
                    saved_ratio,
                    latency_ms,
                    json.dumps(applied_compressors),
                    cached_tokens,
                    cache_type,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def update_cache_stats(self, request_id: int, cached_tokens: int, cache_type: str) -> None:
        """Update cached tokens and cache type after streaming response usage is parsed."""
        if not request_id:
            return
        with self.db.get_connection() as conn:
            conn.execute(
                """
                UPDATE requests
                SET cached_tokens = ?, cache_type = ?
                WHERE id = ?
                """,
                (cached_tokens, cache_type, request_id),
            )
            conn.commit()

    def get_summary(self, project_name: Optional[str] = None) -> Dict[str, Any]:
        """Aggregate total token savings, request counts, cache stats, and latency averages."""
        with self.db.get_connection() as conn:
            query = """
                SELECT
                    COUNT(*) as total_requests,
                    COALESCE(SUM(raw_tokens), 0) as total_raw_tokens,
                    COALESCE(SUM(optimized_tokens), 0) as total_optimized_tokens,
                    COALESCE(SUM(saved_tokens), 0) as total_saved_tokens,
                    COALESCE(SUM(cached_tokens), 0) as total_cached_tokens,
                    COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms
                FROM requests
            """
            params: List[Any] = []
            if project_name and project_name != "ALL":
                query += " WHERE project_name = ?"
                params.append(project_name)

            cursor = conn.execute(query, params)
            row = cursor.fetchone()
            if not row or row["total_requests"] == 0:
                return {
                    "total_requests": 0,
                    "total_raw_tokens": 0,
                    "total_optimized_tokens": 0,
                    "total_saved_tokens": 0,
                    "total_cached_tokens": 0,
                    "cache_hit_percent": 0.0,
                    "overall_saved_percent": 0.0,
                    "avg_latency_ms": 0.0,
                    "estimated_dollars_saved": 0.0,
                }

            total_raw = row["total_raw_tokens"]
            total_saved = row["total_saved_tokens"]
            total_opt = row["total_optimized_tokens"]
            total_cached = row["total_cached_tokens"]
            saved_percent = round((total_saved / max(1, total_raw)) * 100, 2)
            cache_hit_percent = min(100.0, round((total_cached / max(1, total_opt)) * 100, 2))
            raw_coverage_percent = round((total_cached / max(1, total_raw)) * 100, 2)
            dollars_saved = self._calculate_dollar_savings(project_name=project_name)

            return {
                "total_requests": row["total_requests"],
                "total_raw_tokens": total_raw,
                "total_optimized_tokens": total_opt,
                "total_saved_tokens": total_saved,
                "total_cached_tokens": total_cached,
                "cache_hit_percent": cache_hit_percent,
                "raw_coverage_percent": raw_coverage_percent,
                "overall_saved_percent": saved_percent,
                "avg_latency_ms": round(row["avg_latency_ms"], 2),
                "estimated_dollars_saved": round(dollars_saved, 4),
            }

    def get_project_summaries(self) -> List[Dict[str, Any]]:
        """Aggregate stats grouped by project_name with nested session windows breakdown."""
        with self.db.get_connection() as conn:
            # 1. Project-level aggregation
            proj_cursor = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(project_name, ''), 'CtxGuard-Agent') as project_name,
                    COUNT(*) as request_count,
                    COUNT(DISTINCT session_id) as session_count,
                    COALESCE(SUM(raw_tokens), 0) as total_context_tokens,
                    COALESCE(SUM(optimized_tokens), 0) as total_optimized_tokens,
                    COALESCE(SUM(saved_tokens), 0) as total_saved_tokens,
                    COALESCE(SUM(cached_tokens), 0) as total_cached_tokens,
                    COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms
                FROM requests
                GROUP BY COALESCE(NULLIF(project_name, ''), 'CtxGuard-Agent')
                ORDER BY total_context_tokens DESC
                """
            )
            projects_data = proj_cursor.fetchall()

            # 2. Session-level aggregation (nested under each project)
            sess_cursor = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(project_name, ''), 'CtxGuard-Agent') as project_name,
                    session_id,
                    COUNT(*) as request_count,
                    COALESCE(SUM(raw_tokens), 0) as total_context_tokens,
                    COALESCE(SUM(optimized_tokens), 0) as total_optimized_tokens,
                    COALESCE(SUM(saved_tokens), 0) as total_saved_tokens,
                    COALESCE(SUM(cached_tokens), 0) as total_cached_tokens,
                    COALESCE(AVG(latency_ms), 0.0) as avg_latency_ms,
                    MAX(model) as model,
                    MIN(prompt_preview) as first_prompt,
                    MAX(prompt_preview) as last_prompt,
                    MAX(timestamp) as last_active
                FROM requests
                GROUP BY COALESCE(NULLIF(project_name, ''), 'CtxGuard-Agent'), session_id
                ORDER BY total_context_tokens DESC
                """
            )

            sessions_by_project: Dict[str, List[Dict[str, Any]]] = {}
            for s in sess_cursor.fetchall():
                p_name = s["project_name"]
                ctx = s["total_context_tokens"]
                cached = s["total_cached_tokens"]
                opt = s["total_optimized_tokens"]
                saved = s["total_saved_tokens"]
                hit_rate = round((cached / max(1, ctx)) * 100, 2)
                opt_hit_rate = min(100.0, round((cached / max(1, opt)) * 100, 2))
                saved_rate = round((saved / max(1, ctx)) * 100, 2)
                combined_saved_rate = min(100.0, round(((saved + min(cached, opt)) / max(1, ctx)) * 100, 2))

                # Derive clean, human-readable session summary title
                raw_title = s["last_prompt"] or s["first_prompt"] or s["session_id"]
                clean_title = re.sub(r"[\r\n\t]+", " ", raw_title).strip()
                if len(clean_title) > 45:
                    clean_title = clean_title[:42] + "..."

                session_dict = {
                    "session_id": s["session_id"],
                    "session_title": clean_title if clean_title else s["session_id"],
                    "request_count": s["request_count"],
                    "total_requests": s["request_count"],
                    "total_context_tokens": ctx,
                    "total_optimized_tokens": opt,
                    "total_saved_tokens": saved,
                    "total_cached_tokens": cached,
                    "cache_hit_percent": hit_rate,
                    "opt_cache_hit_percent": opt_hit_rate,
                    "saved_rate_percent": saved_rate,
                    "combined_saved_percent": combined_saved_rate,
                    "model": s["model"],
                    "last_active": s["last_active"],
                    "avg_latency_ms": round(s["avg_latency_ms"], 2),
                }
                sessions_by_project.setdefault(p_name, []).append(session_dict)

            # 3. Assemble nested Project -> Sessions structure
            projects = []
            for row in projects_data:
                p_name = row["project_name"]
                ctx = row["total_context_tokens"]
                cached = row["total_cached_tokens"]
                opt = row["total_optimized_tokens"]
                saved = row["total_saved_tokens"]
                hit_rate = round((cached / max(1, ctx)) * 100, 2)
                opt_hit_rate = min(100.0, round((cached / max(1, opt)) * 100, 2))
                saved_rate = round((saved / max(1, ctx)) * 100, 2)
                combined_saved_rate = min(100.0, round(((saved + min(cached, opt)) / max(1, ctx)) * 100, 2))
                dollars = self._calculate_dollar_savings(project_name=p_name)
                p_sessions = sessions_by_project.get(p_name, [])

                projects.append({
                    "project_name": p_name,
                    "request_count": row["request_count"],
                    "total_requests": row["request_count"],
                    "session_count": row["session_count"],
                    "total_context_tokens": ctx,
                    "total_optimized_tokens": opt,
                    "total_saved_tokens": saved,
                    "total_cached_tokens": cached,
                    "cache_hit_percent": hit_rate,
                    "opt_cache_hit_percent": opt_hit_rate,
                    "saved_rate_percent": saved_rate,
                    "combined_saved_percent": combined_saved_rate,
                    "estimated_dollars_saved": round(dollars, 4),
                    "avg_latency_ms": round(row["avg_latency_ms"], 2),
                    "sessions": p_sessions,
                })
            return projects

    def _calculate_dollar_savings(self, project_name: Optional[str] = None) -> float:
        """Calculate dollars saved across different models."""
        total_dollars = 0.0
        with self.db.get_connection() as conn:
            query = "SELECT model, SUM(saved_tokens) as model_saved_tokens FROM requests"
            params: List[Any] = []
            if project_name and project_name != "ALL":
                query += " WHERE project_name = ?"
                params.append(project_name)
            query += " GROUP BY model"

            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                model_name = row["model"].lower()
                saved_tokens = row["model_saved_tokens"]
                price_per_m = MODEL_PRICING_PER_MILLION.get("default", 3.00)
                for key, price in MODEL_PRICING_PER_MILLION.items():
                    if key in model_name:
                        price_per_m = price
                        break
                total_dollars += (saved_tokens / 1_000_000.0) * price_per_m

        return total_dollars

    def get_model_breakdown(self, project_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve savings aggregated by model."""
        with self.db.get_connection() as conn:
            query = """
                SELECT
                    model,
                    COUNT(*) as count,
                    COALESCE(SUM(raw_tokens), 0) as raw_tokens,
                    COALESCE(SUM(optimized_tokens), 0) as optimized_tokens,
                    COALESCE(SUM(saved_tokens), 0) as saved_tokens
                FROM requests
            """
            params: List[Any] = []
            if project_name and project_name != "ALL":
                query += " WHERE project_name = ?"
                params.append(project_name)
            query += " GROUP BY model ORDER BY saved_tokens DESC"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            result = []
            for r in rows:
                raw_tok = r["raw_tokens"]
                saved_tok = r["saved_tokens"]
                saved_ratio = round((saved_tok / max(1, raw_tok)) * 100, 2)
                
                model_name = r["model"].lower()
                price_per_m = MODEL_PRICING_PER_MILLION.get("default", 3.00)
                for key, price in MODEL_PRICING_PER_MILLION.items():
                    if key in model_name:
                        price_per_m = price
                        break
                dollars = (saved_tok / 1_000_000.0) * price_per_m

                result.append({
                    "model": r["model"],
                    "count": r["count"],
                    "raw_tokens": raw_tok,
                    "optimized_tokens": r["optimized_tokens"],
                    "saved_tokens": saved_tok,
                    "saved_ratio": saved_ratio,
                    "dollars_saved": round(dollars, 4),
                })
            return result

    def get_recent_requests(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent request records with project name, prompt preview, and cache hit metrics."""
        with self.db.get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, project_name, prompt_preview, timestamp,
                       protocol, model, raw_tokens, optimized_tokens, saved_tokens,
                       saved_ratio, latency_ms, applied_compressors,
                       COALESCE(cached_tokens, 0) as cached_tokens,
                       COALESCE(cache_type, 'none') as cache_type
                FROM requests
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            result = []
            for r in rows:
                item = dict(r)
                if not item.get("project_name"):
                    item["project_name"] = "CtxGuard-Agent"
                if not item.get("prompt_preview"):
                    item["prompt_preview"] = ""
                # Parse compressors json
                comp_raw = item.get("applied_compressors", "[]")
                try:
                    item["applied_compressors"] = json.loads(comp_raw) if comp_raw else []
                except Exception:
                    item["applied_compressors"] = []
                result.append(item)
            return result
