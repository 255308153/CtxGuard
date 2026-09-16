"""Rule Pruning and Eviction Engine aligning with Headroom design."""

from __future__ import annotations
from typing import List, Dict, Set
from ctxguard.learn.causality_extractor import ExtractedRule

class RulePruner:
    """Enforces rule capacity caps, conflict superseding, and priority ordering."""

    MAX_RULES_BUDGET: int = 10

    @classmethod
    def prune_and_merge_rules(
        cls,
        new_rules: List[ExtractedRule],
        prior_rules: List[ExtractedRule] = None,
        max_budget: int = MAX_RULES_BUDGET,
    ) -> List[ExtractedRule]:
        """Merge new rules with prior rules, superseding same-category/triggers, capped by budget."""
        merged_map: Dict[str, ExtractedRule] = {}

        # 1. Load prior rules
        if prior_rules:
            for r in prior_rules:
                key = f"{r.category}:{r.trigger.strip().lower()}"
                merged_map[key] = r

        # 2. Apply new rules (authoritative override / supersede)
        for r in new_rules:
            key = f"{r.category}:{r.trigger.strip().lower()}"
            merged_map[key] = r

        # 3. Sort by priority / category stability
        sorted_rules = sorted(
            merged_map.values(),
            key=lambda x: (x.category, x.trigger),
        )

        # 4. Enforce strict budget cap (e.g. Max 10 rules)
        return sorted_rules[:max_budget]
