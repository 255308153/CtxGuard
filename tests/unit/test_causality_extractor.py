"""Unit tests for causality rule extraction and Markdown rendering."""

from ctxguard.learn.loop_detector import LoopIncident
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.rule_renderer import RuleRenderer


def test_causality_extraction_and_rendering():
    incidents = [
        LoopIncident(
            pattern_type="repeated_query",
            target_identifier="config/dev.env",
            occurrence_count=4,
            error_snippets=["FileNotFoundError: config/dev.env"],
        ),
        LoopIncident(
            pattern_type="repeated_tool_failure",
            target_identifier="db_migrate",
            occurrence_count=3,
            error_snippets=["Error: DB connection timeout"],
        ),
    ]

    extractor = CausalityExtractor()
    rules = extractor.extract_rules(incidents)

    assert len(rules) == 2
    assert "config/dev.env" in rules[0].directive
    assert "db_migrate" in rules[1].directive

    markdown_block = RuleRenderer.render_markdown_block(rules, marker="CUSTOM_MARKER")
    assert "<!-- CUSTOM_MARKER:START -->" in markdown_block
    assert "<!-- CUSTOM_MARKER:END -->" in markdown_block
    assert "config/dev.env" in markdown_block
    assert "db_migrate" in markdown_block
