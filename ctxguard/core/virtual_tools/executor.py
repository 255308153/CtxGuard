"""Virtual tool local executor for zero-token operations and transparent memory interception."""

import json
import logging
import uuid
from typing import Any, Dict, Optional
from ctxguard.core.context import NormalizedRequest, NormalizedResponse
from ctxguard.storage.graph_models import Entity, MemoryScope, Relationship
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.storage.repository_graph import SQLiteGraphStore

logger = logging.getLogger(__name__)


class VirtualToolExecutor:
    """Executes virtual tool calls locally without forwarding to upstream LLM."""

    def __init__(
        self,
        fingerprint_repo: Optional[FingerprintRepository] = None,
        graph_store: Optional[SQLiteGraphStore] = None,
    ):
        self.fingerprint_repo = fingerprint_repo
        self.graph_store = graph_store

    def is_virtual_tool(self, tool_name: str) -> bool:
        """Check if tool is handled locally."""
        return tool_name in ("ctx_expand", "memory_save", "memory_search")

    def check_and_execute(self, request: NormalizedRequest) -> Optional[NormalizedResponse]:
        """Intercept and execute virtual tool calls locally."""
        if not request.messages:
            return None

        last_msg = request.messages[-1]
        tool_calls = getattr(last_msg, "tool_calls", None)
        if not tool_calls or not isinstance(tool_calls, list):
            return None

        for tc in tool_calls:
            fname = ""
            args_raw = ""
            if isinstance(tc, dict):
                func = tc.get("function", {})
                fname = func.get("name", "") if isinstance(func, dict) else tc.get("name", "")
                args_raw = func.get("arguments", "") if isinstance(func, dict) else tc.get("arguments", "")

            if fname == "ctx_expand":
                return self._execute_ctx_expand(request, args_raw)
            elif fname == "memory_save":
                return self._execute_memory_save(request, args_raw)

        return None

    def _execute_ctx_expand(self, request: NormalizedRequest, args_raw: Any) -> NormalizedResponse:
        ref_id = ""
        try:
            if isinstance(args_raw, str):
                args = json.loads(args_raw)
            elif isinstance(args_raw, dict):
                args = args_raw
            else:
                args = {}
            ref_id = args.get("ref_id", "")
        except Exception:
            pass

        original_content = ""
        if self.fingerprint_repo and ref_id:
            original_content = self.fingerprint_repo.get_content(ref_id) or ""

        if not original_content:
            original_content = f"Error: Reference {ref_id} not found."

        return NormalizedResponse(
            protocol=request.protocol,
            id=f"local_expand_{uuid.uuid4().hex[:8]}",
            model=request.model,
            content=original_content,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            raw_response={"status": "expanded_locally"},
        )

    def _execute_memory_save(self, request: NormalizedRequest, args_raw: Any) -> NormalizedResponse:
        try:
            if isinstance(args_raw, str):
                args = json.loads(args_raw)
            elif isinstance(args_raw, dict):
                args = args_raw
            else:
                args = {}

            fact = args.get("fact", "").strip()
            scope_str = str(args.get("scope", "USER")).lower()

            scope = MemoryScope.USER
            if "session" in scope_str:
                scope = MemoryScope.SESSION
            elif "agent" in scope_str:
                scope = MemoryScope.AGENT
            elif "turn" in scope_str:
                scope = MemoryScope.TURN

            if self.graph_store and fact:
                # 1. Ensure User entity exists in graph_store
                user_entity = self.graph_store.get_entity_by_name("User")
                if not user_entity:
                    user_entity = Entity(
                        name="User",
                        entity_type="person",
                        description="Default User Entity",
                    )
                    self.graph_store.add_entity(user_entity)

                # 2. Add Preference/Fact Entity
                entity = Entity(
                    name=fact,
                    entity_type="preference",
                    description=fact,
                    scope=scope,
                    properties={"fact": fact, "scope": scope.value},
                )
                self.graph_store.add_entity(entity)

                # 3. Add Relationship
                rel = Relationship(
                    source_id=user_entity.id,
                    target_id=entity.id,
                    relation_type="prefers",
                    properties={"desc": fact, "scope": scope.value},
                )
                self.graph_store.add_relationship(rel)

                res_body = json.dumps({"status": "success", "message": "Memory saved successfully", "mem_id": entity.id})
            else:
                res_body = json.dumps({"status": "error", "message": "Missing fact or graph_store uninitialized"})

        except Exception as e:
            logger.error(f"Error executing memory_save: {e}")
            res_body = json.dumps({"status": "error", "message": str(e)})

        return NormalizedResponse(
            protocol=request.protocol,
            id=f"local_mem_{uuid.uuid4().hex[:8]}",
            model=request.model,
            content=res_body,
            prompt_tokens=0,
            completion_tokens=len(res_body) // 4,
            total_tokens=len(res_body) // 4,
            raw_response={"status": "memory_saved_locally"},
        )
