from typing import List, Tuple, Optional, Set
from ctxguard.storage.graph_models import Entity, Subgraph

def format_natural_subgraph(subgraph: Subgraph, budget_applier) -> Optional[str]:
    """Format a subgraph into readable natural language facts."""
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
                budget_lines.append((src.id, line))

    for e in subgraph.entities:
        if e.description and not any(e.name in ln for _, ln in budget_lines):
            budget_lines.append((e.id, f"{e.name} ({e.entity_type}): {e.description}"))

    return budget_applier(budget_lines)
