"""Unit tests for SemanticPruner and information density scoring."""

from ctxguard.plugins.onnx.scorer import SemanticPruner


def test_semantic_pruner_protected_keywords():
    pruner = SemanticPruner(protected_keywords=["CRITICAL_FLAG", "SECRET_KEY"], target_prune_ratio=0.5)
    text = (
        "Basically, you should actually configure the system properly. "
        "Furthermore, please make sure the CRITICAL_FLAG is set to True. "
        "Moreover, essentially ensure that SECRET_KEY is not leaked."
    )

    pruned = pruner.prune_text(text, keep_ratio=0.6)
    assert len(pruned) < len(text)
    # Protected words must strictly be preserved
    assert "CRITICAL_FLAG" in pruned
    assert "SECRET_KEY" in pruned


def test_semantic_pruner_compress_text():
    pruner = SemanticPruner(target_prune_ratio=0.7)
    text = "Basically and essentially, we can actually optimize this function easily."
    pruned = pruner.compress_text(text)
    assert len(pruned) <= len(text)
