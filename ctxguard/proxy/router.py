"""API route definitions for OpenAI and Anthropic proxy endpoints, Web Dashboard, and Admin APIs."""

import time
from pathlib import Path
from typing import Any, Dict, Optional
from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
import orjson

from ctxguard.config.schema import AppConfig
from ctxguard.core.context import Message, NormalizedRequest
from ctxguard.core.pipeline import CompressionPipeline
from ctxguard.core.virtual_tools.executor import VirtualToolExecutor
from ctxguard.learn.scanner import LogScanner
from ctxguard.learn.pivot_analyzer import PivotAnalyzer
from ctxguard.learn.loop_detector import LoopDetector
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.rule_renderer import RuleRenderer
from ctxguard.learn.atomic_writer import AtomicRuleWriter
from ctxguard.proxy.adapters.openai import OpenAIAdapter
from ctxguard.proxy.adapters.anthropic import AnthropicAdapter
from ctxguard.proxy.dashboard import get_dashboard_html
from ctxguard.proxy.upstream import UpstreamClient
from ctxguard.proxy.sse import SSEStreamHandler
from ctxguard.storage.repository_stats import StatsRepository
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.storage.repository_graph import SQLiteGraphStore
from ctxguard.storage.graph_models import Entity, Relationship, RelationshipDirection
from ctxguard.core.memory.graph_engine import MemoryGraphEngine
from ctxguard.core.semantic_cache import SemanticCache
from ctxguard.core.context import RequestContext
from ctxguard.storage.savings_ledger import record_savings_event
from ctxguard.utils.token_counter import estimate_tokens_from_text


def extract_session_and_project(request: Request, norm_req: NormalizedRequest) -> tuple[str, str, str]:
    """Extract (session_id, project_name, prompt_preview) from request headers, client origin, and message content."""
    import hashlib
    import re

    # 1. Inspect URL path parameter, headers, or client cookies for explicit project & session metadata
    path_project = request.path_params.get("project") if hasattr(request, "path_params") and request.path_params else ""
    project_name = (
        path_project
        or request.headers.get("x-project-name")
        or request.headers.get("x-project")
        or request.headers.get("x-project-path")
        or request.headers.get("x-headroom-project")
        or request.headers.get("x-cwd")
        or request.headers.get("x-workspace")
        or ""
    ).strip()

    session_id = (
        request.headers.get("x-session-id")
        or request.headers.get("x-conversation-id")
        or request.headers.get("x-chat-id")
        or request.headers.get("session-id")
        or request.headers.get("conversation-id")
        or request.cookies.get("session_id")
        or request.cookies.get("conversation_id")
        or ""
    ).strip()

    # 2. Extract latest user prompt preview & find the first user message for stable session fingerprinting
    prompt_preview = ""
    first_user_text = ""
    full_text = ""

    # Reverse iterate to find the most recent user prompt
    for m in reversed(norm_req.messages):
        if m.role == "user":
            t = m.get_text_content().strip()
            if t and not prompt_preview:
                prompt_preview = re.sub(r"\s+", " ", t)[:120]
                break

    # Forward iterate to collect all text and find the initial user root prompt
    for m in norm_req.messages:
        text = m.get_text_content().strip()
        if text:
            if m.role == "user" and not first_user_text:
                first_user_text = text[:300]
            full_text += " " + text

    # 3. Detect client origin (Pi Web / Browser vs CLI vs IDE)
    user_agent = request.headers.get("user-agent", "").lower()
    origin = request.headers.get("origin", "").lower()
    referer = request.headers.get("referer", "").lower()

    is_browser_web = (
        "mozilla" in user_agent
        or "chrome" in user_agent
        or "safari" in user_agent
        or "webkit" in user_agent
        or bool(origin)
        or bool(referer)
    )

    # 4. Project name heuristics if not provided in headers
    if not project_name:
        # Check system prompt / context for working directory
        cwd_match = re.search(r"(?:Working directory|workspace|cwd|Project root|Repo):\s*([/\w\-\.]+)", full_text, re.IGNORECASE)
        if cwd_match:
            raw_path = cwd_match.group(1).rstrip("/")
            project_name = raw_path.split("/")[-1]
        else:
            # Check user file paths in prompt
            path_match = re.search(r"/(?:Users|home|root)/[^/\s]+/([^/\s\n]+)", full_text)
            if path_match:
                candidate = path_match.group(1)
                if candidate.lower() in ("downloads", "desktop", "documents", "projects", "workspace", "code"):
                    # Check next subfolder
                    sub_match = re.search(r"/(?:Users|home|root)/[^/\s]+/(?:Downloads|Desktop|Documents|Projects|Workspace|Code)/([^/\s\n]+)", full_text, re.IGNORECASE)
                    project_name = sub_match.group(1) if sub_match else candidate
                else:
                    project_name = candidate
            elif is_browser_web:
                project_name = "Pi-Web"
            else:
                project_name = "Pi-Agent"

    # 5. Session ID derivation if not provided in headers
    if not session_id or session_id == "default":
        if first_user_text:
            # Stable hash based on the root user message of the conversation thread
            short_hash = hashlib.sha256(first_user_text.encode("utf-8")).hexdigest()[:8]
            session_id = f"ses_{short_hash}"
        elif norm_req.messages:
            # Fallback to combined text hash
            all_text_sample = "".join(m.get_text_content()[:100] for m in norm_req.messages[:3])
            short_hash = hashlib.sha256(all_text_sample.encode("utf-8")).hexdigest()[:8]
            session_id = f"ses_{short_hash}"
        else:
            session_id = f"ses_{int(time.time()) % 10000:04d}"

    if not prompt_preview:
        prompt_preview = "(无用户提问文本)"

    return session_id, project_name, prompt_preview


def parse_cache_stats(resp_content: bytes, protocol: str = "openai") -> tuple[int, str]:
    """Parse cached tokens and cache provider type from upstream response JSON."""
    try:
        data = orjson.loads(resp_content)
    except Exception:
        return 0, "none"

    cached_tokens = 0
    cache_type = "none"

    if isinstance(data, dict):
        usage = data.get("usage")
        if isinstance(usage, dict):
            # 1. DeepSeek: prompt_cache_hit_tokens
            if "prompt_cache_hit_tokens" in usage:
                val = usage.get("prompt_cache_hit_tokens") or 0
                if val > 0:
                    cached_tokens = val
                    cache_type = "deepseek_cache"

            # 2. Anthropic: cache_read_input_tokens
            if cached_tokens == 0 and "cache_read_input_tokens" in usage:
                val = usage.get("cache_read_input_tokens") or 0
                if val > 0:
                    cached_tokens = val
                    cache_type = "anthropic_cache"

            # 3. OpenAI / Gemini OpenAI-compatible: prompt_tokens_details.cached_tokens
            if cached_tokens == 0:
                details = usage.get("prompt_tokens_details")
                if isinstance(details, dict):
                    val = details.get("cached_tokens") or 0
                    if val > 0:
                        cached_tokens = val
                        cache_type = "openai_cache"

            # 4. Gemini direct usage field: cachedContentTokenCount
            if cached_tokens == 0:
                val = usage.get("cachedContentTokenCount") or 0
                if val > 0:
                    cached_tokens = val
                    cache_type = "gemini_cache"

        # 5. Gemini native API format: usageMetadata.cachedContentTokenCount
        if cached_tokens == 0 and isinstance(data.get("usageMetadata"), dict):
            val = data["usageMetadata"].get("cachedContentTokenCount") or 0
            if val > 0:
                cached_tokens = val
                cache_type = "gemini_cache"

    return cached_tokens, cache_type


def create_router(
    config: AppConfig,
    pipeline: CompressionPipeline,
    upstream: UpstreamClient,
    stats_repo: Optional[StatsRepository] = None,
    fingerprint_repo: Optional[FingerprintRepository] = None,
    graph_store: Optional[SQLiteGraphStore] = None,
    semantic_cache: Optional[SemanticCache] = None,
) -> APIRouter:
    router = APIRouter()

    openai_adapter = OpenAIAdapter()
    anthropic_adapter = AnthropicAdapter()
    virtual_tool_executor = VirtualToolExecutor(fingerprint_repo=fingerprint_repo, graph_store=graph_store)
    pb_enabled = getattr(getattr(config, "piggyback_extraction", None), "enabled", True)
    graph_engine = MemoryGraphEngine(graph_store, piggyback_enabled=pb_enabled) if graph_store else None
    if semantic_cache is None:
        sc_config = getattr(config, "semantic_cache", None)
        semantic_cache = SemanticCache(config=sc_config)

    # Track session last request timestamps for TTL expiry and cold recompact
    session_last_activity: Dict[str, float] = {}
    sim_state: Dict[str, Any] = {"session_id": f"ses_agent_{int(time.time()) % 10000:04d}", "turn": 0}

    # --------------------------------------------------------------------------
    # Web Dashboard Endpoints
    # --------------------------------------------------------------------------
    @router.get("/", response_class=HTMLResponse)
    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_view():
        """Serve the interactive CtxGuard Web Control Panel."""
        return HTMLResponse(content=get_dashboard_html(), status_code=200)

    @router.get("/api/stats")
    async def get_dashboard_stats(project: Optional[str] = None):
        """API returning summary statistics, project breakdowns, and recent requests directly from SQLite."""
        if stats_repo:
            summary = stats_repo.get_summary(project_name=project)
            project_summaries = stats_repo.get_project_summaries()
            recent = stats_repo.get_recent_requests(limit=500)
        else:
            summary = {
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
            project_summaries = []
            recent = []
        return {"summary": summary, "project_summaries": project_summaries, "recent": recent}

    @router.get("/api/memory/stats")
    async def get_memory_stats():
        """API returning memory repository metrics and learned knowledge rules (100% real dynamic data)."""
        if not stats_repo:
            return {
                "total_fingerprints": 0,
                "total_memorized_chars": 0,
                "recent_fingerprints": [],
                "learned_rules": [],
                "rendered_markdown": "",
            }

        with stats_repo.db.get_connection() as conn:
            cur_count = conn.execute("SELECT COUNT(*) as count, COALESCE(SUM(char_length), 0) as total_chars FROM fingerprints")
            count_row = cur_count.fetchone()
            total_fp = count_row["count"] if count_row else 0
            total_chars = count_row["total_chars"] if count_row else 0

            cur_fps = conn.execute("SELECT hash_id, session_id, char_length, created_at, content FROM fingerprints ORDER BY created_at DESC LIMIT 20")
            fps = []
            for r in cur_fps.fetchall():
                item = dict(r)
                item["snippet"] = item["content"][:150] + ("..." if len(item["content"]) > 150 else "")
                del item["content"]
                fps.append(item)

        # 1. Multi-source real event mining from SQLite database and Claude Code logs
        raw_events = []
        try:
            if stats_repo and stats_repo.db and stats_repo.db.db_path.exists():
                raw_events.extend(LogScanner.scan_ctxguard_db(stats_repo.db.db_path, limit=1000))
        except Exception:
            pass

        try:
            claude_events = LogScanner.scan_claude_logs()
            if claude_events:
                raw_events.extend(claude_events)
        except Exception:
            pass

        # 2. Real incident & pivot extraction
        detector = LoopDetector(threshold=config.learn.detect_loop_threshold)
        pivot_analyzer = PivotAnalyzer()
        extractor = CausalityExtractor()

        pivots = pivot_analyzer.analyze_events(raw_events)
        incidents = detector.detect_loops_from_events(raw_events)
        mined_rules = extractor.extract_rules(incidents=incidents, pivots=pivots)

        dynamic_learned_rules = []
        for r in mined_rules:
            dynamic_learned_rules.append({
                "category": r.category,
                "trigger": r.trigger,
                "directive": r.directive,
                "rationale": r.rationale,
            })

        # 3. Dynamic parse of user workspace rule files (AGENTS.md, INSTRUCTIONS.md, .pi/rules.md, etc.)
        rule_files = [Path("AGENTS.md"), Path("INSTRUCTIONS.md"), Path(".pi/rules.md"), Path(".cursorrules"), Path("CLAUDE.local.md")]
        import re
        for rf in rule_files:
            if rf.exists():
                try:
                    content = rf.read_text(encoding="utf-8", errors="replace")
                    # Ignore auto-rules marker block to prevent recursive duplication
                    clean_content = re.sub(r'<!-- CTXGUARD_AUTO_RULES:START -->[\s\S]*?<!-- CTXGUARD_AUTO_RULES:END -->', '', content)
                    sections = re.split(r'\n(?=##?\s+)', clean_content)
                    for sec in sections:
                        sec = sec.strip()
                        if not sec:
                            continue
                        lines = sec.splitlines()
                        header = lines[0].replace("#", "").strip()
                        body = "\n".join(lines[1:]).strip()
                        if header and body:
                            dynamic_learned_rules.append({
                                "category": f" {rf.name}: {header}",
                                "trigger": f"匹配 {header} 对应场景",
                                "directive": body[:300] + ("..." if len(body) > 300 else ""),
                                "rationale": f"从工作区 {rf.name} 真实规则提取",
                            })
                except Exception:
                    pass

        # Deduplicate dynamic rules by category and directive
        seen_keys = set()
        unique_rules = []
        for r in dynamic_learned_rules:
            key = (r["category"], r["directive"])
            if key not in seen_keys:
                seen_keys.add(key)
                unique_rules.append(r)

        rendered = RuleRenderer.render_markdown_block(mined_rules, marker="CTXGUARD_AUTO_RULES")

        return {
            "total_fingerprints": total_fp,
            "total_memorized_chars": total_chars,
            "recent_fingerprints": fps,
            "learned_rules": unique_rules,
            "rendered_markdown": rendered,
        }

    @router.get("/api/db/raw")
    async def get_raw_database_records():
        """API returning direct SQLite database records for verification."""
        if not stats_repo:
            return {"requests": [], "fingerprints": []}

        with stats_repo.db.get_connection() as conn:
            cur1 = conn.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 50")
            requests_rows = [dict(r) for r in cur1.fetchall()]

            cur2 = conn.execute("SELECT hash_id, session_id, char_length, created_at FROM fingerprints ORDER BY created_at DESC LIMIT 50")
            fp_rows = [dict(r) for r in cur2.fetchall()]

        return {"requests": requests_rows, "fingerprints": fp_rows}

    # --------------------------------------------------------------------------
    # Personal Knowledge Graph Endpoints
    # --------------------------------------------------------------------------
    @router.get("/api/graph/stats")
    async def get_graph_stats():
        """Return knowledge graph summary stats: total entities, relations, types."""
        if not graph_store:
            return {"total_entities": 0, "total_relationships": 0, "entity_types": {}, "top_entities": []}
        return graph_store.get_stats()

    @router.get("/api/graph/entities")
    async def get_graph_entities(type: Optional[str] = None, limit: int = 100):
        """List entities in the personal knowledge graph."""
        if not graph_store:
            return {"entities": []}
        entities = graph_store.list_entities(entity_type=type, limit=limit)
        return {"entities": [e.to_dict() for e in entities]}

    @router.get("/api/graph/full")
    async def get_full_graph_api():
        """Return all entities and relationships for network graph visualization."""
        if not graph_store:
            return {"entities": [], "relationships": []}
        subgraph = graph_store.get_full_graph(limit=500)
        return {
            "entities": [e.to_dict() for e in subgraph.entities],
            "relationships": [r.to_dict() for r in subgraph.relationships],
        }

    @router.get("/api/graph/query")
    async def query_subgraph_api(q: str, hops: int = 2):
        """Run BFS multi-hop subgraph query for a given entity or keyword."""
        if not graph_store or not q.strip():
            return {"entities": [], "relationships": [], "context_markdown": ""}
        subgraph = graph_store.query_subgraph([q.strip()], max_hops=min(3, max(1, hops)))
        return {
            "entities": [e.to_dict() for e in subgraph.entities],
            "relationships": [r.to_dict() for r in subgraph.relationships],
            "context_markdown": subgraph.format_as_context(),
        }

    @router.post("/api/graph/entity")
    async def create_graph_entity(request: Request):
        """Create or update an entity manually."""
        if not graph_store:
            return JSONResponse(status_code=503, content={"error": "Graph store disabled"})
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"error": "Entity name required"})
        entity = graph_store.add_entity(Entity(
            name=name,
            entity_type=body.get("entity_type", "preference"),
            description=body.get("description", ""),
            properties=body.get("properties", {}),
        ))
        return {"status": "success", "entity": entity.to_dict()}

    @router.post("/api/graph/relationship")
    async def create_graph_relationship(request: Request):
        """Create or update a relationship between two entities."""
        if not graph_store:
            return JSONResponse(status_code=503, content={"error": "Graph store disabled"})
        body = await request.json()
        src_name = body.get("source_name", "").strip()
        tgt_name = body.get("target_name", "").strip()
        rel_type = body.get("relation_type", "related_to").strip()

        if not src_name or not tgt_name:
            return JSONResponse(status_code=400, content={"error": "source_name and target_name required"})

        # Resolve or auto-create entities
        src_e = graph_store.get_entity_by_name(src_name) or graph_store.add_entity(Entity(name=src_name, entity_type="concept"))
        tgt_e = graph_store.get_entity_by_name(tgt_name) or graph_store.add_entity(Entity(name=tgt_name, entity_type="preference"))

        rel = graph_store.add_relationship(Relationship(
            source_id=src_e.id,
            target_id=tgt_e.id,
            relation_type=rel_type,
            weight=float(body.get("weight", 1.0)),
        ))
        return {"status": "success", "relationship": rel.to_dict()}

    @router.delete("/api/graph/entity/{entity_id}")
    async def delete_graph_entity(entity_id: str):
        """Delete an entity and cascade its connected relationships."""
        if not graph_store:
            return JSONResponse(status_code=503, content={"error": "Graph store disabled"})
        deleted = graph_store.delete_entity(entity_id)
        return {"status": "success" if deleted else "not_found", "deleted": deleted}

    @router.post("/api/graph/entity/{entity_id}/supersede")
    async def supersede_graph_entity(entity_id: str, request: Request):
        """Supersede an existing entity with new content (Supersession Chain, Gap 1).

        Atomically stamps the old entity as valid_until=now and creates a new
        replacement entity with supersedes=old.id. The old entity is immediately
        removed from FTS5 and vector indexes (Iron Rule, Issue #2143).

        Body: {"new_content": "...", "new_description": "...", "new_metadata": {...}}
        """
        if not graph_store:
            return JSONResponse(status_code=503, content={"error": "Graph store disabled"})
        body = await request.json()
        new_content = body.get("new_content", "").strip()
        if not new_content:
            return JSONResponse(status_code=400, content={"error": "new_content required"})
        try:
            new_entity = graph_store.supersede(
                old_entity_id=entity_id,
                new_content=new_content,
                new_description=body.get("new_description"),
                new_metadata=body.get("new_metadata"),
            )
            return {"status": "superseded", "new_entity": new_entity.to_dict()}
        except ValueError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})

    @router.get("/api/graph/entity/{entity_id}/history")
    async def get_entity_history(entity_id: str):
        """Return the full supersession chain for an entity (oldest to newest).

        Useful for audit trails — lets you see how a fact evolved over time.
        """
        if not graph_store:
            return JSONResponse(status_code=503, content={"error": "Graph store disabled"})
        history = graph_store.get_history(entity_id)
        return {
            "entity_id": entity_id,
            "history": [
                {**e.to_dict(), "is_current": is_current}
                for e, is_current in history
            ],
        }

    @router.post("/api/graph/entity/detach-supersession")
    async def detach_supersession_api(request: Request):
        """Undo an incorrect supersession — restore old entity as active.

        Body: {"old_entity_id": "...", "new_entity_id": "..."}
        """
        if not graph_store:
            return JSONResponse(status_code=503, content={"error": "Graph store disabled"})
        body = await request.json()
        old_id = body.get("old_entity_id", "").strip()
        new_id = body.get("new_entity_id", "").strip()
        if not old_id or not new_id:
            return JSONResponse(status_code=400, content={"error": "old_entity_id and new_entity_id required"})
        ok = graph_store.detach_supersession(old_id, new_id)
        return {"status": "detached" if ok else "chain_not_found", "success": ok}

    @router.post("/api/simulate/request")
    async def simulate_live_proxy_request(request: Request):
        """Simulate a real agent conversational request, run through pipeline, and persist to SQLite."""
        body = await request.json()
        model = body.get("model", "deepseek-flash")
        prompt = body.get("prompt", "Please optimize context pipeline and analyze cache safety.")
        tool_output = body.get("tool_output", "[\n  {\"id\": 1, \"status\": \"ok\", \"latency\": 12.5},\n  {\"id\": 2, \"status\": \"ok\", \"latency\": 14.1}\n]")
        project_name = body.get("project_name", "MathTutor-Agent")

        start_time = time.perf_counter()

        # Progress multi-turn conversational session
        sim_state["turn"] += 1
        turn = sim_state["turn"]
        if turn > 4:
            sim_state["session_id"] = f"ses_agent_{int(time.time()) % 10000:04d}"
            sim_state["turn"] = 1
            turn = 1
        session_id = sim_state["session_id"]

        # Realistic engineering Agent context (system rules + codebase AST > 1024 tokens)
        system_rules = (
            "You are an expert autonomous software engineer working inside the MathTutor-Agent workspace.\n"
            "System Environment: AST Graph indexed, SQLite stats persistent, CacheGuard active.\n"
            + ("Directive: Strictly preserve cached prompt prefix, prevent jitter, and compress tool output.\n" * 20)
        )
        code_context = (
            "def evaluate_policy_network(state_tensor, temperature=0.7):\n"
            "    # Multi-head attention forward pass with cached KV states\n"
            "    hidden_states = state_tensor.transpose(1, 2)\n"
            + ("    # Constraint checking: gradient norms must remain bounded\n" * 15)
            + "    return hidden_states.softmax(dim=-1)\n"
        )

        if turn == 1:
            # Turn 1: Cold start writing cache
            messages = [
                Message(role="system", content=system_rules),
                Message(role="user", content=f"Initialize engineering workspace for {project_name}:\n{code_context}"),
                Message(role="assistant", content="Engineering workspace initialized and cached in memory."),
            ]
            sim_cached_tokens = 0
            sim_cache_type = "none"
            preview_prefix = "第 1 轮 [冷启动写入缓存]"
        elif turn == 2:
            # Turn 2: KV Cache Read Hit! Reusing Turn 1 prefix (>1024 tokens)
            messages = [
                Message(role="system", content=system_rules),
                Message(role="user", content=f"Initialize engineering workspace for {project_name}:\n{code_context}"),
                Message(role="assistant", content="Engineering workspace initialized and cached in memory."),
                Message(role="user", content=prompt),
            ]
            sim_cached_tokens = 1180
            sim_cache_type = "deepseek_cache" if "deepseek" in model.lower() else ("anthropic_cache" if "claude" in model.lower() else "openai_cache")
            preview_prefix = "第 2 轮 [ 云端KV缓存命中]"
        else:
            # Turn 3+: KV Cache Read Hit + Fingerprint Dedup
            messages = [
                Message(role="system", content=system_rules),
                Message(role="user", content=f"Initialize engineering workspace for {project_name}:\n{code_context}"),
                Message(role="assistant", content="Engineering workspace initialized and cached in memory."),
                Message(role="user", content=prompt),
                Message(role="tool", content=tool_output + ("\n" + tool_output) * 5),
                Message(role="user", content="Execute regression test suite and verify latency."),
            ]
            sim_cached_tokens = 1380
            sim_cache_type = "deepseek_cache" if "deepseek" in model.lower() else ("anthropic_cache" if "claude" in model.lower() else "openai_cache")
            preview_prefix = f"第 {turn} 轮 [ KV缓存+指纹命中]"

        norm_req = NormalizedRequest(
            protocol="anthropic" if "claude" in model else "openai",
            model=model,
            messages=messages,
            session_id=session_id,
        )

        req_ctx = await pipeline.process(norm_req)
        duration_ms = (time.perf_counter() - start_time) * 1000
        full_preview = f"{preview_prefix}: {prompt}"

        if stats_repo:
            stats_repo.record_request(
                session_id=session_id,
                protocol=norm_req.protocol,
                model=model,
                raw_tokens=req_ctx.original_tokens,
                optimized_tokens=req_ctx.optimized_tokens,
                latency_ms=duration_ms,
                applied_compressors=req_ctx.applied_compressors,
                project_name=project_name,
                prompt_preview=full_preview[:150],
                cached_tokens=sim_cached_tokens,
                cache_type=sim_cache_type,
            )

        # Update cache_guard turn record
        if hasattr(pipeline, "cache_guard") and pipeline.cache_guard:
            pipeline.cache_guard.record_forwarded_turn(session_id, req_ctx.request.messages, cached_tokens=sim_cached_tokens)
        session_last_activity[session_id] = time.time()

        return {
            "status": "success",
            "session_id": session_id,
            "project_name": project_name,
            "turn": turn,
            "prompt_preview": full_preview[:150],
            "raw_tokens": req_ctx.original_tokens,
            "optimized_tokens": req_ctx.optimized_tokens,
            "saved_tokens": max(0, req_ctx.original_tokens - req_ctx.optimized_tokens),
            "saved_percent": round((max(0, req_ctx.original_tokens - req_ctx.optimized_tokens) / max(1, req_ctx.original_tokens)) * 100, 2),
            "cached_tokens": sim_cached_tokens,
            "cache_type": sim_cache_type,
            "latency_ms": round(duration_ms, 2),
            "applied_compressors": req_ctx.applied_compressors,
        }

    @router.post("/api/test/compress")
    async def test_compress_endpoint(request: Request):
        """API for interactive compression playground testing."""
        body = await request.json()
        input_text = str(body.get("text", ""))

        test_msg = Message(role="user", content=input_text)
        test_req = NormalizedRequest(
            protocol="openai",
            model="gpt-4o",
            messages=[test_msg],
            session_id="playground_test",
        )

        ctx = await pipeline.process(test_req)
        optimized_text = test_req.messages[0].get_text_content() if test_req.messages else ""

        raw_tokens = estimate_tokens_from_text(input_text)
        opt_tokens = estimate_tokens_from_text(optimized_text)
        saved_tokens = max(0, raw_tokens - opt_tokens)
        saved_pct = round((saved_tokens / max(1, raw_tokens)) * 100, 2)

        return {
            "raw_tokens": raw_tokens,
            "optimized_tokens": opt_tokens,
            "saved_tokens": saved_tokens,
            "saved_percent": saved_pct,
            "optimized_text": optimized_text,
            "applied_compressors": ctx.applied_compressors,
        }

    @router.post("/api/learn/run")
    async def run_learn_api():
        """API to trigger offline failure incident mining and generate rule block (100% real dynamic data)."""
        raw_events = []
        try:
            if stats_repo and stats_repo.db and stats_repo.db.db_path.exists():
                raw_events.extend(LogScanner.scan_ctxguard_db(stats_repo.db.db_path, limit=1000))
        except Exception:
            pass

        try:
            claude_events = LogScanner.scan_claude_logs()
            if claude_events:
                raw_events.extend(claude_events)
        except Exception:
            pass

        detector = LoopDetector(threshold=config.learn.detect_loop_threshold)
        pivot_analyzer = PivotAnalyzer()
        extractor = CausalityExtractor()

        pivots = pivot_analyzer.analyze_events(raw_events)
        incidents = detector.detect_loops_from_events(raw_events)
        rules = extractor.extract_rules(incidents=incidents, pivots=pivots)

        marker = "CTXGUARD_AUTO_RULES"
        rendered = RuleRenderer.render_markdown_block(rules, marker=marker)

        # Atomically sync to target files defined in config
        target_files = config.learn.target_files or []
        for tf in target_files:
            try:
                AtomicRuleWriter.write_rules_to_file(tf.path, rendered, marker=tf.marker or marker)
            except Exception:
                pass

        return {
            "status": "ok",
            "discovered_pivots": len(pivots),
            "detected_loops": len(incidents),
            "rules_count": len(rules),
            "rendered_rules": rendered,
        }

    # --------------------------------------------------------------------------
    # Health & Models Endpoints
    # --------------------------------------------------------------------------
    @router.get("/health")
    async def health_check() -> Dict[str, str]:
        return {"status": "ok", "service": "CtxGuard", "version": "0.1.0"}

    @router.get("/v1/models")
    @router.get("/p/{project}/v1/models")
    @router.get("/p/{project}/models")
    async def list_models() -> Dict[str, Any]:
        """Simple model list endpoint for OpenAI client compatibility."""
        return {
            "object": "list",
            "data": [
                {"id": "gemini-3.7-flash-high", "object": "model", "owned_by": "antigravity"},
                {"id": "gemini-3.8-flash-high", "object": "model", "owned_by": "antigravity"},
                {"id": "claude-3-5-sonnet-20241022", "object": "model", "owned_by": "anthropic"},
                {"id": "claude-sonnet-4-6", "object": "model", "owned_by": "antigravity"},
                {"id": "grok-4.6", "object": "model", "owned_by": "xai"},
                {"id": "deepseek-flash", "object": "model", "owned_by": "deepseek"},
                {"id": "deepseek-v4-pro", "object": "model", "owned_by": "deepseek"},
                {"id": "gpt-4o", "object": "model", "owned_by": "openai"},
            ],
        }

    # --------------------------------------------------------------------------
    # Proxy Gateway Endpoints
    # --------------------------------------------------------------------------
    @router.post("/v1/chat/completions")
    @router.post("/chat/completions")
    @router.post("/p/{project}/v1/chat/completions")
    @router.post("/p/{project}/chat/completions")
    async def openai_chat_completions(request: Request) -> Response:
        """Handle OpenAI chat completions proxy."""
        start_time = time.perf_counter()
        body_bytes = await request.body()
        raw_body: Dict[str, Any] = orjson.loads(body_bytes) if body_bytes else {}

        raw_session_id = request.headers.get("x-session-id", "default")
        norm_req = openai_adapter.parse_request(raw_body, session_id=raw_session_id)
        session_id, project_name, prompt_preview = extract_session_and_project(request, norm_req)
        norm_req.session_id = session_id

        # Resolve provider and idle time for cache safety & cold recompact
        model_lower = norm_req.model.lower()
        provider_name = request.headers.get("x-ctxguard-provider")
        if not provider_name:
            if "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
                provider_name = "openai"
            elif "deepseek" in model_lower:
                provider_name = "deepseek"
            elif "grok" in model_lower:
                provider_name = "grok"
            elif "claude" in model_lower:
                provider_name = "antigravity" if "antigravity" in config.upstream.providers else "anthropic"
            elif "gemini" in model_lower:
                provider_name = "antigravity" if "antigravity" in config.upstream.providers else "google"
            else:
                provider_name = config.upstream.default_provider

        now = time.time()
        last_req_time = session_last_activity.get(session_id)
        idle_seconds = (now - last_req_time) if last_req_time is not None else 0.0
        norm_req.idle_seconds = idle_seconds
        norm_req.provider = provider_name

        # 1. Virtual tool local execution check (0 upstream tokens!)
        local_tool_resp = virtual_tool_executor.check_and_execute(norm_req)
        if local_tool_resp:
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="openai",
                    model=norm_req.model,
                    raw_tokens=0,
                    optimized_tokens=0,
                    latency_ms=duration_ms,
                    applied_compressors=["virtual_tool_local_expand"],
                    project_name=project_name,
                    prompt_preview=prompt_preview,
                )
            return JSONResponse(
                content=local_tool_resp.raw_response,
                headers={
                    "X-CtxGuard-Virtual-Tool": "true",
                    "X-CtxGuard-Process-Time-Ms": f"{duration_ms:.2f}",
                },
            )

        # 1.2 Semantic Cache Lookup (0 upstream tokens, 100% savings, ~1ms latency)
        # Snapshot pristine messages before any pipeline or graph injections
        pristine_messages = [Message(role=m.role, content=m.content) for m in norm_req.messages]
        user_query_text = ""
        for m in reversed(norm_req.messages):
            if m.role == "user":
                user_query_text = m.get_text_content()
                break

        if semantic_cache and semantic_cache.config.enabled:
            cached_hit = semantic_cache.get(
                query=user_query_text,
                messages=pristine_messages,
                model=norm_req.model,
            )
            if cached_hit:
                entry, sim, hit_type = cached_hit
                duration_ms = (time.perf_counter() - start_time) * 1000
                record_savings_event(
                    tokens_before=entry.raw_tokens or 150,
                    tokens_after=0,
                    model=norm_req.model,
                    client=project_name,
                    source="semantic_cache",
                )
                if stats_repo:
                    stats_repo.record_request(
                        session_id=session_id,
                        protocol="openai",
                        model=norm_req.model,
                        raw_tokens=entry.raw_tokens or 150,
                        optimized_tokens=0,
                        latency_ms=duration_ms,
                        applied_compressors=[f"semantic_cache_{hit_type}_hit"],
                        project_name=project_name,
                        prompt_preview=prompt_preview,
                    )
                resp_headers = {
                    "X-CtxGuard-Semantic-Cache": f"HIT-{hit_type.upper()}",
                    "X-CtxGuard-Semantic-Similarity": f"{sim:.4f}",
                    "X-CtxGuard-Process-Time-Ms": f"{duration_ms:.2f}",
                    "Content-Type": "application/json",
                }
                return Response(
                    content=entry.response_body,
                    headers=resp_headers,
                    media_type="application/json",
                )

        # 1.5 Personal Knowledge Graph Injection & Learning (Controlled by Config Switch)
        if graph_engine and getattr(getattr(config, "piggyback_extraction", None), "enabled", True):
            try:
                temp_ctx = RequestContext(request=norm_req)
                graph_engine.inject_graph_context(temp_ctx)
            except Exception as ge_err:
                pass

        # 2. Process through Compression Pipeline
        req_ctx = await pipeline.process(norm_req)

        # 3. Build upstream payload
        upstream_payload = openai_adapter.build_upstream_payload(req_ctx.request)
        client_headers = dict(request.headers)

        provider = upstream.resolve_provider(provider_name)
        headers = upstream.build_headers("openai", provider, client_headers)

        # Normalize model aliases for upstream providers.
        # DeepSeek API now only supports "deepseek-flash" and "deepseek-v4-pro";
        # map legacy aliases to "deepseek-flash" (do NOT map to the retired "deepseek-chat").
        if provider_name == "deepseek":
            if upstream_payload.get("model") in ("deepseek-v4-flash", "deepseek-v4-flash-vision-exp"):
                upstream_payload["model"] = "deepseek-flash"

        # Check if request payload was modified by compressors, graph injection, model aliasing,
        # or if historical prefix was compressed and frozen in prior turns.
        # CRITICAL CACHE INVARIANT (Iron Invariant 1 & 2):
        # Forward raw client bytes ONLY when the entire payload is genuinely identical to client input (no compression anywhere).
        has_compressed_history = False
        if hasattr(pipeline, "cache_guard") and pipeline.cache_guard:
            prev_forwarded = pipeline.cache_guard._last_forwarded_messages.get(session_id)
            if prev_forwarded and (req_ctx.original_tokens > req_ctx.optimized_tokens or req_ctx.optimized_tokens < req_ctx.original_tokens):
                has_compressed_history = True

        can_passthrough_raw = (
            not req_ctx.applied_compressors
            and not has_compressed_history
            and (req_ctx.original_tokens == req_ctx.optimized_tokens)
            and not req_ctx.metadata.get("graph_injected")
            and (raw_body.get("model") == upstream_payload.get("model"))
            and (not norm_req.stream or bool(raw_body.get("stream_options")))
        )
        raw_bytes_to_send = body_bytes if can_passthrough_raw else None
        fwd_kwargs = {"raw_body": raw_bytes_to_send} if raw_bytes_to_send is not None else {}

        if norm_req.stream:
            # Ensure OpenAI / DeepSeek returns usage in stream chunks
            if "stream_options" not in upstream_payload:
                upstream_payload["stream_options"] = {"include_usage": True}

            stream_gen = upstream.forward_stream(
                "v1/chat/completions", upstream_payload, headers, provider_name, **fwd_kwargs
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            if req_ctx.original_tokens > req_ctx.optimized_tokens:
                record_savings_event(
                    tokens_before=req_ctx.original_tokens,
                    tokens_after=req_ctx.optimized_tokens,
                    model=norm_req.model,
                    client=project_name,
                    source="proxy_pipeline",
                )
            req_id = None
            if stats_repo:
                req_id = stats_repo.record_request(
                    session_id=session_id,
                    protocol="openai",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                    project_name=project_name,
                    prompt_preview=prompt_preview,
                )

            def on_openai_stream_complete(cached_toks: int, c_type: str):
                if req_id and stats_repo and cached_toks > 0:
                    stats_repo.update_cache_stats(req_id, cached_toks, c_type)
                if hasattr(pipeline, "cache_guard") and pipeline.cache_guard:
                    pipeline.cache_guard.record_forwarded_turn(session_id, req_ctx.request.messages, cached_tokens=cached_toks)
                session_last_activity[session_id] = time.time()

            return StreamingResponse(
                SSEStreamHandler.passthrough_stream(stream_gen, on_complete=on_openai_stream_complete, protocol="openai"),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio),
                },
            )
        else:
            resp = await upstream.forward_request(
                "v1/chat/completions", upstream_payload, headers, provider_name, **fwd_kwargs
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            if req_ctx.original_tokens > req_ctx.optimized_tokens:
                record_savings_event(
                    tokens_before=req_ctx.original_tokens,
                    tokens_after=req_ctx.optimized_tokens,
                    model=norm_req.model,
                    client=project_name,
                    source="proxy_pipeline",
                )
            cached_toks, c_type = parse_cache_stats(resp.content, protocol="openai")
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="openai",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                    project_name=project_name,
                    prompt_preview=prompt_preview,
                    cached_tokens=cached_toks,
                    cache_type=c_type,
                )
            if hasattr(pipeline, "cache_guard") and pipeline.cache_guard:
                pipeline.cache_guard.record_forwarded_turn(session_id, req_ctx.request.messages, cached_tokens=cached_toks)
            session_last_activity[session_id] = time.time()

            response_bytes_to_return = resp.content
            if resp.status_code == 200 and graph_engine and graph_engine.piggyback_enabled:
                try:
                    resp_json = orjson.loads(resp.content)
                    choices = resp_json.get("choices")
                    if isinstance(choices, list) and choices:
                        delta_or_msg = choices[0].get("message", {})
                        orig_text = delta_or_msg.get("content", "")
                        if isinstance(orig_text, str) and "<memory>" in orig_text.lower():
                            clean_text, extracted_memories = graph_engine.parse_and_strip_memory(orig_text)
                            delta_or_msg["content"] = clean_text
                            response_bytes_to_return = orjson.dumps(resp_json)
                            if extracted_memories:
                                graph_engine.apply_extracted_memories(extracted_memories)
                except Exception as pb_err:
                    pass

            if resp.status_code == 200 and semantic_cache and semantic_cache.config.enabled:
                semantic_cache.put(
                    query=user_query_text,
                    messages=pristine_messages,
                    model=norm_req.model,
                    response_body=response_bytes_to_return,
                    raw_tokens=req_ctx.original_tokens,
                )

            return Response(
                content=response_bytes_to_return,
                status_code=resp.status_code,
                media_type="application/json",
                headers={"X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio)},
            )

    @router.post("/v1/responses")
    @router.post("/responses")
    @router.post("/v1/codex/responses")
    @router.post("/backend-api/codex/responses")
    @router.post("/backend-api/responses")
    @router.post("/p/{project}/v1/responses")
    @router.post("/p/{project}/responses")
    @router.post("/p/{project}/v1/codex/responses")
    @router.post("/p/{project}/backend-api/codex/responses")
    @router.post("/p/{project}/backend-api/responses")
    async def openai_responses(request: Request) -> Response:
        """Proxy OpenAI Responses API requests used by Codex."""
        start_time = time.perf_counter()
        body_bytes = await request.body()
        raw_body: Dict[str, Any] = orjson.loads(body_bytes) if body_bytes else {}
        # Collect mutable text references (container, key_or_index)
        text_refs = []
        messages = []

        instructions = raw_body.get("instructions")
        system_str = instructions if isinstance(instructions, str) else None

        def walk_input(obj: Any, role: str = "user") -> None:
            if isinstance(obj, dict):
                r = obj.get("role", role)
                # Skip additional_tools containers from text mutation
                if obj.get("type") == "additional_tools":
                    return
                for k, v in list(obj.items()):
                    if k in {"text", "content", "input_text", "output_text"} and isinstance(v, str):
                        text_refs.append((obj, k))
                        messages.append(Message(role=r, content=v))
                    elif k not in {"signature", "encrypted_content", "tools"}:
                        walk_input(v, r)
            elif isinstance(obj, list):
                for idx, item in enumerate(obj):
                    if isinstance(item, str):
                        text_refs.append((obj, idx))
                        messages.append(Message(role=role, content=item))
                    else:
                        walk_input(item, role)
            elif isinstance(obj, str):
                text_refs.append((raw_body, "input"))
                messages.append(Message(role=role, content=obj))

        walk_input(raw_body.get("input", []))

        norm_req = NormalizedRequest(
            protocol="openai",
            model=str(raw_body.get("model", "gpt-5")),
            messages=messages,
            system=system_str,
            stream=bool(raw_body.get("stream", False)),
            raw_payload=raw_body,
            session_id=request.headers.get("x-session-id", "default"),
        )
        session_id, project_name, prompt_preview = extract_session_and_project(request, norm_req)
        norm_req.session_id = session_id
        provider_name = request.headers.get("x-ctxguard-provider")
        if not provider_name:
            provider_name = "codex" if "codex" in config.upstream.providers else config.upstream.default_provider
        norm_req.provider = provider_name

        req_ctx = await pipeline.process(norm_req)

        # Only mutate JSON fields if compression was actually applied and lengths strictly match
        if req_ctx.applied_compressors and len(text_refs) == len(req_ctx.request.messages):
            for (container, key), message in zip(text_refs, req_ctx.request.messages):
                container[key] = message.get_text_content()

        can_passthrough_raw = not req_ctx.applied_compressors
        fwd_bytes = body_bytes if can_passthrough_raw else orjson.dumps(raw_body)
        upstream_payload = raw_body
        headers = upstream.build_headers("openai", upstream.resolve_provider(provider_name), dict(request.headers))
        
        req_path = request.url.path
        if "/backend-api/" in req_path:
            idx = req_path.find("/backend-api/")
            path = req_path[idx + 1:]
        elif "/v1/codex/" in req_path:
            idx = req_path.find("/v1/codex/")
            path = req_path[idx + 1:]
        else:
            path = "v1/responses"
        fwd_kwargs = {"raw_body": fwd_bytes}
        duration_ms = (time.perf_counter() - start_time) * 1000
        if req_ctx.original_tokens > req_ctx.optimized_tokens:
            record_savings_event(
                tokens_before=req_ctx.original_tokens,
                tokens_after=req_ctx.optimized_tokens,
                model=norm_req.model,
                client=project_name,
                source="proxy_pipeline",
            )

        if stats_repo:
            stats_repo.record_request(
                session_id=session_id,
                protocol="openai-responses",
                model=norm_req.model,
                raw_tokens=req_ctx.original_tokens,
                optimized_tokens=req_ctx.optimized_tokens,
                latency_ms=duration_ms,
                applied_compressors=req_ctx.applied_compressors,
                project_name=project_name,
                prompt_preview=prompt_preview,
            )

        if norm_req.stream:
            try:
                upstream_resp = await upstream.send_stream_request(
                    path, headers=headers, provider_name=provider_name, **fwd_kwargs
                )
            except Exception as exc:
                return JSONResponse(
                    {"error": {"message": f"CtxGuard upstream connection error: {str(exc)}", "code": 502}},
                    status_code=502,
                )

            if upstream_resp.status_code >= 400:
                try:
                    error_bytes = await upstream_resp.aread()
                finally:
                    await upstream_resp.aclose()
                return Response(
                    content=error_bytes,
                    status_code=upstream_resp.status_code,
                    media_type=upstream_resp.headers.get("content-type") or "application/json",
                )

            async def body_generator():
                try:
                    async for chunk in upstream_resp.aiter_bytes():
                        if chunk:
                            yield chunk
                finally:
                    await upstream_resp.aclose()

            media_type = upstream_resp.headers.get("content-type") or "text/event-stream"
            return StreamingResponse(
                SSEStreamHandler.passthrough_stream(body_generator(), protocol="openai"),
                media_type=media_type,
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
                status_code=upstream_resp.status_code,
            )

        resp = await upstream.forward_request(path, headers=headers, provider_name=provider_name, **fwd_kwargs)
        return Response(
            content=resp.content,
            status_code=resp.status_code,
            media_type="application/json",
            headers={"X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio)},
        )

    @router.get("/backend-api/codex/models")
    @router.get("/backend-api/models")
    @router.get("/backend-api/me")
    @router.api_route("/backend-api/{sub_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    @router.api_route("/v1/codex/{sub_path:path}", methods=["GET", "POST", "PUT", "DELETE"])
    async def codex_backend_passthrough(request: Request, sub_path: str = "") -> Response:
        """Generic passthrough for auxiliary Codex client backend routes."""
        provider_name = request.headers.get("x-ctxguard-provider") or ("codex" if "codex" in config.upstream.providers else config.upstream.default_provider)
        headers = upstream.build_headers("openai", upstream.resolve_provider(provider_name), dict(request.headers))
        req_path = request.url.path.lstrip("/")
        body_bytes = await request.body()
        client = upstream.get_client()
        provider = upstream.resolve_provider(provider_name)
        full_url = upstream.build_full_url(provider, req_path)
        if request.url.query:
            full_url = f"{full_url}?{request.url.query}"
        try:
            resp = await client.request(
                method=request.method,
                url=full_url,
                headers=headers,
                content=body_bytes if body_bytes else None,
            )
            return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))
        except Exception as exc:
            return JSONResponse({"error": {"message": f"CtxGuard upstream error: {str(exc)}", "code": 502}}, status_code=502)

    @router.post("/v1/messages")
    @router.post("/messages")
    @router.post("/p/{project}/v1/messages")
    @router.post("/p/{project}/messages")
    async def anthropic_messages(request: Request) -> Response:
        """Handle Anthropic messages proxy."""
        start_time = time.perf_counter()
        body_bytes = await request.body()
        raw_body: Dict[str, Any] = orjson.loads(body_bytes) if body_bytes else {}

        raw_session_id = request.headers.get("x-session-id", "default")
        norm_req = anthropic_adapter.parse_request(raw_body, session_id=raw_session_id)
        session_id, project_name, prompt_preview = extract_session_and_project(request, norm_req)
        norm_req.session_id = session_id

        # Resolve provider and idle time for cache safety & cold recompact
        provider_name = request.headers.get("x-ctxguard-provider", "anthropic")
        now = time.time()
        last_req_time = session_last_activity.get(session_id)
        idle_seconds = (now - last_req_time) if last_req_time is not None else 0.0
        norm_req.idle_seconds = idle_seconds
        norm_req.provider = provider_name

        # 1. Virtual tool local execution check (0 upstream tokens!)
        local_tool_resp = virtual_tool_executor.check_and_execute(norm_req)
        if local_tool_resp:
            duration_ms = (time.perf_counter() - start_time) * 1000
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="anthropic",
                    model=norm_req.model,
                    raw_tokens=0,
                    optimized_tokens=0,
                    latency_ms=duration_ms,
                    applied_compressors=["virtual_tool_local_expand"],
                    project_name=project_name,
                    prompt_preview=prompt_preview,
                )
            return JSONResponse(
                content=local_tool_resp.raw_response,
                headers={
                    "X-CtxGuard-Virtual-Tool": "true",
                    "X-CtxGuard-Process-Time-Ms": f"{duration_ms:.2f}",
                },
            )

        # 1.2 Semantic Cache Lookup (0 upstream tokens, 100% savings, ~1ms latency)
        # Snapshot pristine messages before any pipeline or graph injections
        pristine_messages = [Message(role=m.role, content=m.content) for m in norm_req.messages]
        user_query_text = ""
        for m in reversed(norm_req.messages):
            if m.role == "user":
                user_query_text = m.get_text_content()
                break

        if semantic_cache and semantic_cache.config.enabled:
            cached_hit = semantic_cache.get(
                query=user_query_text,
                messages=pristine_messages,
                model=norm_req.model,
                system=norm_req.system,
            )
            if cached_hit:
                entry, sim, hit_type = cached_hit
                duration_ms = (time.perf_counter() - start_time) * 1000
                record_savings_event(
                    tokens_before=entry.raw_tokens or 150,
                    tokens_after=0,
                    model=norm_req.model,
                    client=project_name,
                    source="semantic_cache",
                )
                if stats_repo:
                    stats_repo.record_request(
                        session_id=session_id,
                        protocol="anthropic",
                        model=norm_req.model,
                        raw_tokens=entry.raw_tokens or 150,
                        optimized_tokens=0,
                        latency_ms=duration_ms,
                        applied_compressors=[f"semantic_cache_{hit_type}_hit"],
                        project_name=project_name,
                        prompt_preview=prompt_preview,
                    )
                resp_headers = {
                    "X-CtxGuard-Semantic-Cache": f"HIT-{hit_type.upper()}",
                    "X-CtxGuard-Semantic-Similarity": f"{sim:.4f}",
                    "X-CtxGuard-Process-Time-Ms": f"{duration_ms:.2f}",
                    "Content-Type": "application/json",
                }
                return Response(
                    content=entry.response_body,
                    headers=resp_headers,
                    media_type="application/json",
                )

        # 1.5 Personal Knowledge Graph Injection & Learning (Controlled by Config Switch)
        if graph_engine and getattr(getattr(config, "piggyback_extraction", None), "enabled", True):
            try:
                temp_ctx = RequestContext(request=norm_req)
                graph_engine.inject_graph_context(temp_ctx)
            except Exception as ge_err:
                pass

        # 2. Process through Compression Pipeline
        req_ctx = await pipeline.process(norm_req)

        # 3. Build upstream payload
        upstream_payload = anthropic_adapter.build_upstream_payload(req_ctx.request)
        client_headers = dict(request.headers)

        provider = upstream.resolve_provider(provider_name)
        headers = upstream.build_headers("anthropic", provider, client_headers)

        # Check if request payload was modified by compressors, graph injection, or model changes.
        # CRITICAL CACHE INVARIANT (Iron Invariant 3 & 1):
        # If no modifications occurred, forward raw client bytes verbatim to ensure 100% SHA-256 byte parity!
        can_passthrough_raw = (
            not req_ctx.applied_compressors
            and not req_ctx.metadata.get("graph_injected")
            and (raw_body.get("model") == upstream_payload.get("model"))
        )
        raw_bytes_to_send = body_bytes if can_passthrough_raw else None
        fwd_kwargs = {"raw_body": raw_bytes_to_send} if raw_bytes_to_send is not None else {}

        if norm_req.stream:
            stream_gen = upstream.forward_stream(
                "v1/messages", upstream_payload, headers, provider_name, **fwd_kwargs
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            if req_ctx.original_tokens > req_ctx.optimized_tokens:
                record_savings_event(
                    tokens_before=req_ctx.original_tokens,
                    tokens_after=req_ctx.optimized_tokens,
                    model=norm_req.model,
                    client=project_name,
                    source="proxy_pipeline",
                )
            req_id = None
            if stats_repo:
                req_id = stats_repo.record_request(
                    session_id=session_id,
                    protocol="anthropic",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                    project_name=project_name,
                    prompt_preview=prompt_preview,
                )

            def on_anthropic_stream_complete(cached_toks: int, c_type: str):
                if req_id and stats_repo and cached_toks > 0:
                    stats_repo.update_cache_stats(req_id, cached_toks, c_type)
                if hasattr(pipeline, "cache_guard") and pipeline.cache_guard:
                    pipeline.cache_guard.record_forwarded_turn(session_id, req_ctx.request.messages, cached_tokens=cached_toks)
                session_last_activity[session_id] = time.time()

            return StreamingResponse(
                SSEStreamHandler.passthrough_stream(stream_gen, on_complete=on_anthropic_stream_complete, protocol="anthropic"),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio),
                },
            )
        else:
            resp = await upstream.forward_request(
                "v1/messages", upstream_payload, headers, provider_name, **fwd_kwargs
            )
            duration_ms = (time.perf_counter() - start_time) * 1000
            if req_ctx.original_tokens > req_ctx.optimized_tokens:
                record_savings_event(
                    tokens_before=req_ctx.original_tokens,
                    tokens_after=req_ctx.optimized_tokens,
                    model=norm_req.model,
                    client=project_name,
                    source="proxy_pipeline",
                )
            cached_toks, c_type = parse_cache_stats(resp.content, protocol="anthropic")
            if stats_repo:
                stats_repo.record_request(
                    session_id=session_id,
                    protocol="anthropic",
                    model=norm_req.model,
                    raw_tokens=req_ctx.original_tokens,
                    optimized_tokens=req_ctx.optimized_tokens,
                    latency_ms=duration_ms,
                    applied_compressors=req_ctx.applied_compressors,
                    project_name=project_name,
                    prompt_preview=prompt_preview,
                    cached_tokens=cached_toks,
                    cache_type=c_type,
                )
            if hasattr(pipeline, "cache_guard") and pipeline.cache_guard:
                pipeline.cache_guard.record_forwarded_turn(session_id, req_ctx.request.messages, cached_tokens=cached_toks)
            session_last_activity[session_id] = time.time()

            response_bytes_to_return = resp.content
            if resp.status_code == 200 and graph_engine and graph_engine.piggyback_enabled:
                try:
                    resp_json = orjson.loads(resp.content)
                    content_blocks = resp_json.get("content")
                    if isinstance(content_blocks, list):
                        for block in content_blocks:
                            if isinstance(block, dict) and block.get("type") == "text":
                                orig_text = block.get("text", "")
                                if "<memory>" in orig_text.lower():
                                    clean_text, extracted_memories = graph_engine.parse_and_strip_memory(orig_text)
                                    block["text"] = clean_text
                                    response_bytes_to_return = orjson.dumps(resp_json)
                                    if extracted_memories:
                                        graph_engine.apply_extracted_memories(extracted_memories)
                except Exception as pb_err:
                    pass

            if resp.status_code == 200 and semantic_cache and semantic_cache.config.enabled:
                semantic_cache.put(
                    query=user_query_text,
                    messages=pristine_messages,
                    model=norm_req.model,
                    response_body=response_bytes_to_return,
                    raw_tokens=req_ctx.original_tokens,
                    system=norm_req.system,
                )

            return Response(
                content=response_bytes_to_return,
                status_code=resp.status_code,
                media_type="application/json",
                headers={"X-CtxGuard-Saved-Ratio": str(req_ctx.compression_ratio)},
            )

    return router
