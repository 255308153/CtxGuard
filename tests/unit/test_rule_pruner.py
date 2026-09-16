from ctxguard.learn.causality_extractor import ExtractedRule
from ctxguard.learn.pruner import RulePruner

def test_rule_pruner_superseding_and_budget():
    # 1. Test duplicate trigger superseding
    rule1 = ExtractedRule(category="Path Corrections", trigger="src/config.json", directive="Use config/config.json", rationale="Discovered path")
    rule2 = ExtractedRule(category="Path Corrections", trigger="src/config.json", directive="Use settings/config.json", rationale="Updated path")

    merged = RulePruner.prune_and_merge_rules([rule2], [rule1])
    assert len(merged) == 1
    assert merged[0].directive == "Use settings/config.json"

    # 2. Test budget cap
    overflow_rules = [
        ExtractedRule(category="Command Patterns", trigger=f"cmd_{i}", directive=f"rule_{i}", rationale=f"rat_{i}")
        for i in range(15)
    ]
    capped = RulePruner.prune_and_merge_rules(overflow_rules, max_budget=10)
    assert len(capped) == 10
