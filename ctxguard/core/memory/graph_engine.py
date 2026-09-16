"""Knowledge graph memory engine for extracting entities, prompt injection, and piggyback extraction."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ctxguard.core.context import Message, RequestContext
from ctxguard.core.memory.formatter import format_natural_subgraph
from ctxguard.core.memory.relevance import MemoryRelevanceScorer
from ctxguard.core.memory.sanitizer import sanitize_message_content
from ctxguard.storage.graph_models import Entity, Relationship, Subgraph
from ctxguard.storage.repository_graph import SQLiteGraphStore

logger = logging.getLogger(__name__)

# MemoryInjectionBudget defaults (Gap 5)
_DEFAULT_BUDGET_TOKENS = 1024
_DEFAULT_BUDGET_ITEMS = 10

# Regex for parsing piggyback <memory> blocks in model outputs
_MEMORY_TAG_PATTERN = re.compile(r"<memory>(.*?)</memory>", re.DOTALL | re.IGNORECASE)

# Instruction appended to the latest user message when piggyback extraction is enabled
EXTRACTION_PROTOCOL_INSTRUCTION = (
    "\n\n[Memory Extraction Protocol]\n"
    "If this conversation reveals new explicit user facts/preferences, tools/frameworks they use, "
    "or updates an existing fact (marked with [mem_id]), append a single-line memory JSON block at the VERY END of your response:\n"
    '- To add a new memory: <memory>{"op": "add", "entity": "User"|<entity_name>, "relation": "<any_relation_predicate>", '
    '"target": "...", "entity_type": "preference"|"technology"|"environment"|"fact"|"workflow", "desc": "optional description"}</memory>\n'
    '- To update/supersede an existing memory: <memory>{"op": "supersede", "mem_id": "old_mem_id", "target": "new_fact", "desc": "updated description"}</memory>\n'
    "If no new facts or preference changes are present, do NOT output any <memory> tags.\n"
    "[/Memory Extraction Protocol]"
)


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (good enough for budget gating)."""
    return max(1, len(text) // 4)


class MemoryInjectionBudget:
    """Controls how many memories are injected into each prompt.

    Implements the headroom 05-长期记忆 budget rules:
      - max_tokens: hard cap on total injected memory token count (default 1024)
      - max_items:  hard cap on number of memory lines injected (default 10)
      - Line-safe trimming: never cuts mid-sentence; trims at line boundaries.
      - [mem_id] prefix: each injected line is prefixed with its entity ID so the
        model can explicitly reference it in a supersession operation.
    """

    def __init__(self, max_tokens: int = _DEFAULT_BUDGET_TOKENS, max_items: int = _DEFAULT_BUDGET_ITEMS):
        self.max_tokens = max_tokens
        self.max_items = max_items

    def apply(self, lines: List[Tuple[str, str]]) -> str:
        """Select and format memory lines within budget.

        Args:
            lines: List of (entity_id, formatted_line) tuples, in priority order
                   (highest priority first — caller is responsible for ordering).

        Returns:
            Budget-trimmed multiline string with [mem_id] prefixes attached.
        """
        output: List[str] = []
        used_tokens = 0
        used_items = 0

        for entity_id, line in lines:
            if used_items >= self.max_items:
                break
            prefixed = f"[{entity_id}] {line}"
            line_tokens = _estimate_tokens(prefixed)
            if used_tokens + line_tokens > self.max_tokens:
                # Stop rather than cut mid-sentence
                break
            output.append(prefixed)
            used_tokens += line_tokens
            used_items += 1

        return "\n".join(output)


class MemoryGraphEngine:
    """Orchestrates knowledge graph learning, multi-hop retrieval, prompt injection, and piggyback extraction."""

    PREFERENCE_PATTERNS = [
        # "我喜欢/经常使用/主力是 pi agent / 喝可乐 / 吃火锅 / 喝咖啡"
        (
            re.compile(r"(?:主力|常用|主要|经常使用|平时喜欢|喜欢|偏好|爱)(?:\s*使用|\s*用|\s*喝|\s*吃|\s*玩|\s*看)\s*(?:的)?\s*(?:是)?\s*(?:agent|工具|客户端|饮料|食物)?\s*([\u4e00-\u9fa5a-zA-Z0-9_\-\.\+]+(?:\s+[\u4e00-\u9fa5a-zA-Z0-9_\-\.\+]+)?)", re.IGNORECASE),
            "preference",
            "prefers",
        ),
        # "以后用/优先用/使用 pnpm/yarn/uv/bun/npm"
        (
            re.compile(r"(?:以后|优先|必须|请|默认)(?:使用|用|采用)\s*([\u4e00-\u9fa5a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
            "preference",
            "prefers",
        ),
        # "系统是/环境是 macOS/Linux/Windows"
        (
            re.compile(r"(?:系统|操作系统|环境|电脑)(?:是|使用|为)\s*([\u4e00-\u9fa5a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
            "environment",
            "runs_on",
        ),
        # "项目 X 运行在端口 Y / 端口是 Y"
        (
            re.compile(r"(?:项目)?\s*([\u4e00-\u9fa5a-zA-Z0-9_\-\.]+)?\s*(?:运行在|端口(?:是|为)?)\s*(\d{2,5})", re.IGNORECASE),
            "configuration",
            "runs_on_port",
        ),
        # "技术栈是/用 Next.js / FastAPI / Rust / Python 开发"
        (
            re.compile(r"(?:技术栈|框架|后端|前端)(?:是|采用|使用)\s*([\u4e00-\u9fa5a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
            "technology",
            "built_with",
        ),
    ]

    def __init__(
        self,
        graph_store: SQLiteGraphStore,
        injection_budget: Optional[MemoryInjectionBudget] = None,
        piggyback_enabled: bool = True,
    ):
        self.store = graph_store
        self.budget = injection_budget or MemoryInjectionBudget()
        self.piggyback_enabled = piggyback_enabled
        self.relevance_scorer = MemoryRelevanceScorer(min_threshold=0.25)
        self._bootstrap_default_knowledge()

    def _bootstrap_default_knowledge(self) -> None:
        """Seed baseline system entities and relationships if graph is empty."""
        stats = self.store.get_stats()
        if stats.get("total_entities", 0) == 0:
            logger.info("Bootstrapping default knowledge graph entities and relations...")
            user = self.store.add_entity(Entity(name="User", entity_type="person", description="当前系统开发者 / 用户"))
            ctxguard = self.store.add_entity(Entity(name="CtxGuard", entity_type="project", description="轻量级 LLM 上下文优化与智能守护网关 (端口 8787)"))
            pi_web = self.store.add_entity(Entity(name="Pi-Web", entity_type="project", description="Next.js 前端应用 (端口 30141)"))
            ds_flash = self.store.add_entity(Entity(name="DeepSeek-Flash", entity_type="technology", description="官方 DeepSeek 4.1 Flash 极速推理模型"))
            macos = self.store.add_entity(Entity(name="macOS", entity_type="environment", description="Apple Silicon 运行系统"))

            self.store.add_relationship(Relationship(source_id=user.id, target_id=macos.id, relation_type="operates_on"))
            self.store.add_relationship(Relationship(source_id=user.id, target_id=ds_flash.id, relation_type="prefers_default_model"))
            self.store.add_relationship(Relationship(source_id=ctxguard.id, target_id=pi_web.id, relation_type="services_frontend"))
            self.store.add_relationship(Relationship(source_id=pi_web.id, target_id=ctxguard.id, relation_type="proxied_by"))

    def extract_and_learn_from_text(self, text: str, user_id: str = "default_user") -> List[Relationship]:
        """Extract entities and relationships from user text patterns (single-pass regex)."""
        if not text or len(text.strip()) < 3:
            return []

        learned_rels: List[Relationship] = []
        user_entity = self.store.get_entity_by_name("User", user_id=user_id)
        if not user_entity:
            user_entity = self.store.add_entity(Entity(name="User", entity_type="person", user_id=user_id))

        for pattern, etype, rel_type in self.PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                groups = [g for g in match.groups() if g]
                if not groups:
                    continue
                target_name = groups[-1].strip()
                # Exclude interrogative phrases, auxiliary words, and common false-positive sentences
                invalid_stopwords = (
                    "it", "that", "this", "什么", "怎么", "怎样", "吗", "呢", "吧", "啊",
                    "提示词", "没写", "未注册", "工具没有注册"
                )
                if not target_name or any(sw in target_name for sw in invalid_stopwords):
                    continue
                if any(q in text for q in ("吗", "？", "?", "还是")):
                    continue

                target_entity = self.store.add_entity(
                    Entity(name=target_name, entity_type=etype, user_id=user_id)
                )

                source_entity = user_entity
                if len(groups) > 1 and groups[0]:
                    proj_name = groups[0].strip()
                    source_entity = self.store.add_entity(
                        Entity(name=proj_name, entity_type="project", user_id=user_id)
                    )

                rel = self.store.add_relationship(
                    Relationship(
                        source_id=source_entity.id,
                        target_id=target_entity.id,
                        relation_type=rel_type,
                        user_id=user_id,
                    )
                )
                learned_rels.append(rel)
                logger.info(
                    "[MemoryGraph] Auto-learned: (%s) -[%s]-> (%s)",
                    source_entity.name, rel_type, target_entity.name,
                )

        return learned_rels

    def find_relevant_subgraph(
        self,
        text: str,
        user_id: str = "default_user",
        max_hops: int = 2,
    ) -> Optional[Subgraph]:
        """Find relevant subgraph using three-path retrieval: name-match + FTS + User fallback.

        Only active (non-superseded) entities are considered (Iron Rule via active_only=True).
        """
        # --- Path 1: Exact name substring match ---
        all_entities = self.store.list_entities(user_id=user_id, limit=200, active_only=True)
        matched_entity_ids: Set[str] = set()
        text_lower = text.lower()

        for e in all_entities:
            if e.name_lower and len(e.name_lower) >= 3 and e.name_lower in text_lower:
                matched_entity_ids.add(e.id)
            elif e.entity_type in ("preference", "environment") and any(
                w in text_lower for w in ("偏好", "系统", "环境", "配置", "使用", "规范")
            ):
                matched_entity_ids.add(e.id)

        # --- Path 2: FTS5 BM25 keyword search ---
        fts_results = self.store.search_entities(text, user_id=user_id, limit=10, active_only=True)
        for e in fts_results:
            matched_entity_ids.add(e.id)

        # --- Path 3: Fallback to User root node for generic questions ---
        if not matched_entity_ids and any(
            w in text_lower for w in ("我", "项目", "怎么做", "端口", "模型", "配置")
        ):
            user_node = self.store.get_entity_by_name("User", user_id=user_id)
            if user_node:
                matched_entity_ids.add(user_node.id)

        if not matched_entity_ids:
            return None

        subgraph = self.store.query_subgraph(
            list(matched_entity_ids), max_hops=max_hops, user_id=user_id, active_only=True
        )
        if not subgraph.entities:
            return None

        return subgraph

    def inject_graph_context(self, context: RequestContext) -> Optional[str]:
        """Extract relevant graph knowledge and inject into context messages.

        Applies MemoryInjectionBudget (Gap 5):
          - Max 1024 tokens of injected memory
          - Max 10 memory lines
          - Each line prefixed with [mem_id] so model can issue explicit supersede ops

        If piggyback_enabled is True, also appends the EXTRACTION_PROTOCOL_INSTRUCTION
        to the dynamic suffix (latest user message tail) so the upstream LLM extracts
        memories in the same inference pass with 0 extra API calls.

        CACHE INVARIANT: Memory and extraction instructions are appended to the latest
        user message tail only. Never injected into messages[0] or system prompt.
        """
        # 0. Sanitize historical messages to prevent duplicated protocol injection
        for msg in context.request.messages:
            if isinstance(msg.content, str):
                msg.content = sanitize_message_content(msg.content)
            elif isinstance(msg.content, list):
                for part in msg.content:
                    if isinstance(part, dict) and "text" in part:
                        part["text"] = sanitize_message_content(part["text"])

        user_id = "default_user"
        last_user_text = ""
        for m in reversed(context.request.messages):
            if m.role == "user":
                last_user_text = m.get_text_content()
                break

        # 1. Passive single-pass regex learning from user input
        self.extract_and_learn_from_text(last_user_text, user_id=user_id)

        # 2. Retrieve relevant subgraph (active-only, recency-ranked)
        subgraph = self.find_relevant_subgraph(last_user_text, user_id=user_id, max_hops=2)

        injected_block = ""
        context_md = ""

        # Score relevance against user query
        if subgraph and self.relevance_scorer.should_inject(last_user_text, subgraph):
            context_md = format_natural_subgraph(subgraph, self.budget.apply) or ""
            if context_md.strip():
                injected_block = (
                    f"\n\n[Relevant User Context & Preferences]\n"
                    f"{context_md}\n"
                    f"[/Relevant User Context & Preferences]"
                )

        if not injected_block.strip():
            return None

        # 5. Append to latest user message (NEVER to system prompt — cache invariant)
        messages = context.request.messages
        last_user_msg = None
        for m in reversed(messages):
            if m.role == "user":
                last_user_msg = m
                break

        if last_user_msg is not None:
            if isinstance(last_user_msg.content, str):
                last_user_msg.content = last_user_msg.content + injected_block
            elif isinstance(last_user_msg.content, list):
                last_user_msg.content.append({"type": "text", "text": injected_block})
            context.metadata["graph_injected"] = True
            return context_md or "piggyback_protocol_injected"

        return None

    # --------------------------------------------------------------------------
    # Piggyback (搭便车) Extraction: Parsing, Stripping, and Async Application
    # --------------------------------------------------------------------------

    def parse_and_strip_memory(self, text: str) -> Tuple[str, List[Dict[str, Any]]]:
        """Strip <memory> tags from model response and parse their JSON payloads.

        Returns:
            (clean_text, parsed_memories)
            clean_text: Model response with all <memory> blocks stripped and trailing whitespace normalized.
            parsed_memories: List of decoded JSON dictionaries from each <memory> tag.
        """
        if not text:
            return text, []

        memories: List[Dict[str, Any]] = []
        matches = _MEMORY_TAG_PATTERN.findall(text)

        for match_str in matches:
            content = match_str.strip()
            if not content:
                continue
            try:
                payload = json.loads(content)
                if isinstance(payload, dict):
                    memories.append(payload)
            except Exception as exc:
                logger.debug("Failed to decode JSON from <memory> tag: %s (payload: %r)", exc, content)

        # Strip tags and normalize trailing whitespace/newlines
        clean_text = _MEMORY_TAG_PATTERN.sub("", text).rstrip()
        return clean_text, memories

    def apply_extracted_memories(
        self,
        memories: List[Dict[str, Any]],
        user_id: str = "default_user",
    ) -> List[Any]:
        """Apply extracted memory actions into the SQLite knowledge graph.

        Supported operations:
          - "supersede": Atomically replaces an existing memory by its mem_id.
            Payload: {"op": "supersede", "mem_id": "...", "target": "...", "desc": "..."}
          - "add": Adds a new entity and relationship into the graph.
            Payload: {"op": "add", "entity": "User", "relation": "prefers", "target": "Rust", "entity_type": "preference", "desc": "..."}

        Returns:
            List of updated or created entities / relationships.
        """
        applied: List[Any] = []

        for item in memories:
            op = item.get("op", "").lower().strip()

            if op == "supersede":
                mem_id = item.get("mem_id")
                new_target = item.get("target", "").strip()
                if mem_id and new_target:
                    try:
                        updated_entity = self.store.supersede(
                            old_entity_id=mem_id,
                            new_content=new_target,
                            new_description=item.get("desc"),
                            new_metadata={"source": "piggyback_extraction"},
                        )
                        applied.append(updated_entity)
                        logger.info(
                            "[Piggyback] Superseded memory [%s] -> '%s'",
                            mem_id, new_target,
                        )
                    except Exception as err:
                        logger.warning("[Piggyback] Supersession failed for [%s]: %s", mem_id, err)

            elif op == "add":
                target_name = item.get("target", "").strip()
                if not target_name:
                    continue

                entity_name = item.get("entity", "User").strip() or "User"
                rel_type = item.get("relation", "prefers").strip() or "prefers"
                etype = item.get("entity_type", "preference").strip() or "preference"
                desc = item.get("desc", "")

                try:
                    src_entity = self.store.get_entity_by_name(entity_name, user_id=user_id)
                    if not src_entity:
                        src_entity = self.store.add_entity(
                            Entity(name=entity_name, entity_type="person", user_id=user_id)
                        )

                    tgt_entity = self.store.add_entity(
                        Entity(
                            name=target_name,
                            entity_type=etype,
                            description=desc,
                            user_id=user_id,
                            metadata={"source": "piggyback_extraction"},
                        )
                    )

                    rel = self.store.add_relationship(
                        Relationship(
                            source_id=src_entity.id,
                            target_id=tgt_entity.id,
                            relation_type=rel_type,
                            user_id=user_id,
                            metadata={"source": "piggyback_extraction"},
                        )
                    )
                    applied.append(rel)
                    logger.info(
                        "[Piggyback] Added memory: (%s) -[%s]-> (%s)",
                        src_entity.name, rel_type, tgt_entity.name,
                    )
                except Exception as err:
                    logger.warning("[Piggyback] Add memory failed for '%s': %s", target_name, err)

        return applied
