"""Rule Pruning and Eviction Engine aligning with CtxGuard Engine design."""

from __future__ import annotations
from typing import List, Optional, Sequence
from ctxguard.learn.causality_extractor import ExtractedRule
from ctxguard.learn.models import LearnedRule


class RulePruner:
    """Enforces rule capacity caps, conflict superseding, and priority ordering."""

    MAX_RULES_BUDGET: int = 10

    # ------------------------------------------------------------------
    # Round-trip API (LearnedRule) — used by the write path
    # ------------------------------------------------------------------
    @classmethod
    def prune(
        cls,
        rules: Sequence[LearnedRule],
        max_rules: Optional[int] = MAX_RULES_BUDGET,
    ) -> List[LearnedRule]:
        """Cap an already-merged rule set, evicting the least valuable rules first.

        Why a cap exists at all: the rule block is injected into *every* future prompt.
        An uncapped block converts a one-time discovery into a permanent per-request tax,
        and the historical rules that stop being re-observed never get evicted. headroom
        has no cap (it relies on section overwrite plus manual deletion), which is why its
        ``CLAUDE.local.md`` grows without bound; CtxGuard keeps the cap deliberately.

        The cap keeps the **top N of the same priority ordering that is rendered**, so the
        eviction rule is auditable rather than incidental. That ordering is:
          1. Rules observed in this run (fresh) before carried-forward ones.
          2. Higher measured ``wasted_tokens`` first.
          3. Higher ``occurrence_count`` first.
        """
        if max_rules is None or max_rules <= 0:
            return list(rules)

        ranked = sorted(rules, key=cls.priority_key)
        return ranked[:max_rules]

    @classmethod
    def priority_key(cls, rule: LearnedRule):
        """Sort key shared with the rendered ordering (see ``RuleMerger.merge_rules``)."""
        return (
            0 if not getattr(rule, "carried_forward", False) else 1,
            -int(getattr(rule, "wasted_tokens", 0) or 0),
            -int(getattr(rule, "occurrence_count", 1) or 1),
        )

    # ------------------------------------------------------------------
    # Legacy API (ExtractedRule) — heuristic fallback path
    # ------------------------------------------------------------------
    @classmethod
    def prune_and_merge_rules(
        cls,
        new_rules: List[ExtractedRule],
        prior_rules: List[ExtractedRule] = None,
        max_budget: int = MAX_RULES_BUDGET,
    ) -> List[ExtractedRule]:
        """Merge new rules with prior rules, superseding same-category/triggers, capped by budget."""
        merged_map: dict = {}

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
