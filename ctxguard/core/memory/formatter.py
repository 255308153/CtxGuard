from typing import Any, Callable, List, Optional, Set, Tuple
from ctxguard.storage.graph_models import Entity, Subgraph

def format_natural_subgraph(
    subgraph: Subgraph,
    budget_applier,
    score_fn: Optional[Callable[[str, str], float]] = None,
) -> Optional[str]:
    """Format a subgraph into readable natural language facts.

    ``score_fn`` optionally reorders the candidate lines by a priority value
    (typically relevance × recency). Order matters because ``budget_applier``
    trims the *tail* when the token budget runs out: without an explicit ordering,
    whichever line happened to be emitted first survives, and BFS insertion order
    is arbitrary with respect to what the user actually asked about.
    """
    if not subgraph or (not subgraph.relationships and not subgraph.entities):
        return None

    entity_by_id = {e.id: e for e in subgraph.entities}
    budget_lines: List[Tuple[str, str]] = []
    rendered_rels: Set[tuple] = set()

    for r in subgraph.relationships:
        src = entity_by_id.get(r.source_id)
        tgt = entity_by_id.get(r.target_id)
        if src and tgt:
            rel_key = (src.name, r.relation_type, tgt.name)
            if rel_key not in rendered_rels:
                rendered_rels.add(rel_key)
                if src.name == "User":
                    line = f"User {r.relation_type.replace('_', ' ')}: {tgt.name}"
                else:
                    line = f"{src.name} {r.relation_type.replace('_', ' ')} {tgt.name}"
                # The line is keyed by the TARGET entity, not the source. The target is the
                # fact's payload ("User prefers: vim" is a memory *about vim*), so this is
                # what [mem_id] must name for a supersede to mean anything — keying on the
                # source emitted "User"'s id for every preference, and superseding those
                # would have replaced the user entity itself. It also makes the recency
                # ordering below reflect the age of the fact rather than of its owner,
                # which otherwise scored every one of a user's preferences identically.
                budget_lines.append((tgt.id, line))

    for e in subgraph.entities:
        if e.description and not any(e.name in ln for _, ln in budget_lines):
            budget_lines.append((e.id, f"{e.name} ({e.entity_type}): {e.description}"))

    if score_fn is not None and budget_lines:
        # Stable descending sort: equal scores keep their original relationship-before-
        # description order, so output stays deterministic across turns (which keeps the
        # upstream KV cache stable, since these lines are injected into the live zone).
        budget_lines = sorted(budget_lines, key=lambda item: score_fn(item[0], item[1]), reverse=True)

    return budget_applier(budget_lines)
