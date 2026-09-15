"""Knowledge graph memory engine for extracting entities and injecting graph context."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set

from ctxguard.core.context import Message, RequestContext
from ctxguard.storage.graph_models import Entity, Relationship, Subgraph
from ctxguard.storage.repository_graph import SQLiteGraphStore

logger = logging.getLogger(__name__)


class MemoryGraphEngine:
    """Orchestrates knowledge graph learning, multi-hop retrieval, and prompt injection."""

    PREFERENCE_PATTERNS = [
        # "以后用/优先用/使用 pnpm/yarn/uv/bun/npm"
        (
            re.compile(r"(?:以后|优先|必须|请|默认)(?:使用|用|采用)\s*([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
            "preference",
            "prefers",
        ),
        # "系统是/环境是 macOS/Linux/Windows"
        (
            re.compile(r"(?:系统|操作系统|环境|电脑)(?:是|使用|为)\s*([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
            "environment",
            "runs_on",
        ),
        # "项目 X 运行在端口 Y / 端口是 Y"
        (
            re.compile(r"(?:项目)?\s*([a-zA-Z0-9_\-\.]+)?\s*(?:运行在|端口(?:是|为)?)\s*(\d{2,5})", re.IGNORECASE),
            "configuration",
            "runs_on_port",
        ),
        # "技术栈是/用 Next.js / FastAPI / Rust / Python 开发"
        (
            re.compile(r"(?:技术栈|框架|后端|前端)(?:是|采用|使用)\s*([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
            "technology",
            "built_with",
        ),
    ]

    def __init__(self, graph_store: SQLiteGraphStore):
        self.store = graph_store
        self._bootstrap_default_knowledge()

    def _bootstrap_default_knowledge(self) -> None:
        """Seed baseline system entities and relationships if graph is empty."""
        stats = self.store.get_stats()
        if stats.get("total_entities", 0) == 0:
            logger.info("Bootstrapping default knowledge graph entities and relations...")
            # Baseline entities
            user = self.store.add_entity(Entity(name="User", entity_type="person", description="当前系统开发者 / 用户"))
            ctxguard = self.store.add_entity(Entity(name="CtxGuard", entity_type="project", description="轻量级 LLM 上下文优化与智能守护网关 (端口 8787)"))
            pi_web = self.store.add_entity(Entity(name="Pi-Web", entity_type="project", description="Next.js 前端应用 (端口 30141)"))
            ds_flash = self.store.add_entity(Entity(name="DeepSeek-Flash", entity_type="technology", description="官方 DeepSeek 4.1 Flash 极速推理模型"))
            macos = self.store.add_entity(Entity(name="macOS", entity_type="environment", description="Apple Silicon 运行系统"))

            # Baseline relationships
            self.store.add_relationship(Relationship(source_id=user.id, target_id=macos.id, relation_type="operates_on"))
            self.store.add_relationship(Relationship(source_id=user.id, target_id=ds_flash.id, relation_type="prefers_default_model"))
            self.store.add_relationship(Relationship(source_id=ctxguard.id, target_id=pi_web.id, relation_type="services_frontend"))
            self.store.add_relationship(Relationship(source_id=pi_web.id, target_id=ctxguard.id, relation_type="proxied_by"))

    def extract_and_learn_from_text(self, text: str, user_id: str = "default_user") -> List[Relationship]:
        """Extract entities and relationships from user text patterns (Single-pass)."""
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
                if not target_name or target_name.lower() in ("it", "that", "this", "什么", "怎么"):
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
                    "[MemoryGraph] Auto-learned relation: (%s) -[%s]-> (%s)",
                    source_entity.name, rel_type, target_entity.name
                )

        return learned_rels

    def find_relevant_subgraph(
        self,
        text: str,
        user_id: str = "default_user",
        max_hops: int = 2,
    ) -> Optional[Subgraph]:
        """Find relevant subgraph by scanning text against existing entities."""
        all_entities = self.store.list_entities(user_id=user_id, limit=200)
        matched_entities: Set[str] = set()

        text_lower = text.lower()
        for e in all_entities:
            # Check exact or keyword match
            if e.name_lower and len(e.name_lower) >= 3 and e.name_lower in text_lower:
                matched_entities.add(e.id)
            elif e.entity_type in ("preference", "environment") and any(w in text_lower for w in ("偏好", "系统", "环境", "配置", "使用", "规范")):
                matched_entities.add(e.id)

        # If user asks about general preferences or projects, include User node as root
        if not matched_entities and any(w in text_lower for w in ("我", "项目", "怎么做", "端口", "模型", "配置")):
            user_node = self.store.get_entity_by_name("User", user_id=user_id)
            if user_node:
                matched_entities.add(user_node.id)

        if not matched_entities:
            return None

        subgraph = self.store.query_subgraph(list(matched_entities), max_hops=max_hops, user_id=user_id)
        if not subgraph.entities:
            return None

        return subgraph

    def inject_graph_context(self, context: RequestContext) -> Optional[str]:
        """Extract relevant graph knowledge and inject into context messages."""
        user_id = "default_user"
        last_user_text = ""
        for m in reversed(context.request.messages):
            if m.role == "user":
                last_user_text = m.get_text_content()
                break

        # 1. Passive single-pass learning from user input
        self.extract_and_learn_from_text(last_user_text, user_id=user_id)

        # 2. Retrieve relevant subgraph
        subgraph = self.find_relevant_subgraph(last_user_text, user_id=user_id, max_hops=2)
        if not subgraph or (not subgraph.relationships and not subgraph.entities):
            return None

        context_md = subgraph.format_as_context()
        if not context_md.strip():
            return None

        injected_block = (
            f"\n\n[Personal Knowledge Graph Context]\n"
            f"{context_md}\n"
            f"[/Personal Knowledge Graph Context]\n"
        )

        # Inject into system prompt or first message
        messages = context.request.messages
        if messages:
            if messages[0].role == "system":
                content = messages[0].content
                if isinstance(content, str):
                    messages[0].content = content + injected_block
                elif isinstance(content, list):
                    content.append({"type": "text", "text": injected_block})
            else:
                # Prepend a lightweight system message with graph context
                messages.insert(0, Message(role="system", content=injected_block.strip()))

        return context_md
