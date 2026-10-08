"""Virtual tool local executor for zero-token operations and transparent memory interception."""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from ctxguard.core.context import NormalizedRequest, NormalizedResponse
from ctxguard.storage.graph_models import Entity, MemoryScope, Relationship
from ctxguard.storage.repository_fingerprint import FingerprintRepository
from ctxguard.storage.repository_graph import SQLiteGraphStore

logger = logging.getLogger(__name__)


#: Values the memory_save / memory_search schemas can send, mapped onto the storage enum.
#: Ordered longest-keyword-first so a compound value such as "project_session" resolves
#: deterministically instead of by dict ordering.
_SCOPE_KEYWORDS = (
    ("session", MemoryScope.SESSION),
    ("project", MemoryScope.PROJECT),
    ("agent", MemoryScope.AGENT),
    ("turn", MemoryScope.TURN),
    ("user", MemoryScope.USER),
)


def resolve_memory_scope(raw: Any) -> MemoryScope:
    """Resolve a tool-supplied scope string to a :class:`MemoryScope`.

    Why this is explicit rather than a default-plus-overrides chain: the schema advertises
    ``USER``/``PROJECT``/``SESSION`` while ``MemoryScope`` also carries ``AGENT``/``TURN``.
    A resolver that starts at ``USER`` and only special-cases three keywords silently
    downgrades every unrecognised value — which is how ``scope=PROJECT`` used to be stored
    as a user-level fact. A well-formed write landing in the wrong bucket is harder to
    notice than a rejection, so anything unresolvable is logged instead of passed quietly.
    """
    if isinstance(raw, MemoryScope):
        return raw
    text = str(raw or "").strip().lower()
    if not text:
        return MemoryScope.USER
    for keyword, scope in _SCOPE_KEYWORDS:
        if keyword in text:
            return scope
    logger.warning("Unrecognised memory scope %r; storing as USER", raw)
    return MemoryScope.USER


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
        """Check if tool is handled locally.

        Must stay in sync with the dispatch table in :meth:`check_and_execute`: a name
        listed here but missing a branch is worse than not listing it, because the
        interception layer reports the call as handled and it is then forwarded upstream
        verbatim, where the downstream client has no such tool registered.
        """
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
            elif fname == "memory_search":
                return self._execute_memory_search(request, args_raw)

        return None

    @staticmethod
    def _parse_args(args_raw: Any) -> Dict[str, Any]:
        """Best-effort decode of a tool-call argument payload into a dict."""
        if isinstance(args_raw, dict):
            return args_raw
        if isinstance(args_raw, str):
            try:
                decoded = json.loads(args_raw)
                return decoded if isinstance(decoded, dict) else {}
            except Exception:
                return {}
        return {}

    def _execute_ctx_expand(self, request: NormalizedRequest, args_raw: Any) -> NormalizedResponse:
        args = self._parse_args(args_raw)
        ref_id = str(args.get("ref_id", "") or "")

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
            args = self._parse_args(args_raw)

            fact = str(args.get("fact", "")).strip()
            scope = resolve_memory_scope(args.get("scope"))
            # `entity` is part of the schema the model is shown; it used to be silently
            # discarded, which meant the subject of a fact never survived the write and
            # every memory came back bound to the same User node.
            subject = str(args.get("entity", "") or "").strip()

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
                properties = {"fact": fact, "scope": scope.value}
                if subject:
                    properties["subject"] = subject
                entity = Entity(
                    name=fact,
                    entity_type="preference",
                    description=fact,
                    scope=scope,
                    properties=properties,
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

                res_body = json.dumps({
                    "status": "success",
                    "message": "Memory saved successfully",
                    "mem_id": entity.id,
                    "scope": scope.value,
                })
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

    def _execute_memory_search(self, request: NormalizedRequest, args_raw: Any) -> NormalizedResponse:
        """Answer a memory_search call from the local graph, at zero API tokens.

        This closes a declaration/implementation gap: ``is_virtual_tool`` already recognised
        ``memory_search`` while ``check_and_execute`` had no branch for it, so such a call
        would have been neither intercepted nor executed and would have flowed upstream as
        an unregistered tool — the exact failure the virtual-tool invariant exists to stop.

        Results carry ``mem_id`` so a follow-up correction can address the stored fact
        explicitly instead of appending a near-duplicate.
        """
        try:
            args = self._parse_args(args_raw)

            query = str(args.get("query") or args.get("q") or "").strip()
            scope_filter = args.get("scope")
            try:
                limit = int(args.get("limit") or 5)
            except (TypeError, ValueError):
                limit = 5
            limit = max(1, min(limit, 50))

            matches: List[Dict[str, Any]] = []
            if self.graph_store and query:
                entities = self.graph_store.search_entities(query, user_id="default_user", limit=limit)
                wanted_scope = resolve_memory_scope(scope_filter) if scope_filter else None
                for entity in entities:
                    if wanted_scope is not None and entity.scope != wanted_scope:
                        continue
                    matches.append({
                        "mem_id": entity.id,
                        "fact": entity.name,
                        "entity_type": entity.entity_type,
                        "scope": entity.scope.value,
                        "subject": entity.properties.get("subject", ""),
                        "created_at": entity.created_at.isoformat(),
                    })
                res_body = json.dumps({
                    "status": "success",
                    "count": len(matches),
                    "results": matches,
                })
            else:
                res_body = json.dumps({
                    "status": "error",
                    "message": "Missing query or graph_store uninitialized",
                })

        except Exception as e:
            logger.error(f"Error executing memory_search: {e}")
            res_body = json.dumps({"status": "error", "message": str(e)})

        return NormalizedResponse(
            protocol=request.protocol,
            id=f"local_mems_{uuid.uuid4().hex[:8]}",
            model=request.model,
            content=res_body,
            prompt_tokens=0,
            completion_tokens=len(res_body) // 4,
            total_tokens=len(res_body) // 4,
            raw_response={"status": "memory_searched_locally"},
        )
