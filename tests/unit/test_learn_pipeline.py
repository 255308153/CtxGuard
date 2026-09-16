"""Unit tests for the offline Learn pipeline (Headroom 08-失败学习 implementation).

Validates:
1. PivotAnalyzer: Success Correlation (Failure -> Exploration -> Success).
2. LoopDetector: Re-fetch Loops with Canonical Signature stripping (200 OK loops).
3. User Rejection / Inversion preference detection.
4. DigestBuilder: Filtering chitchat & enforcing token budget.
5. AtomicRuleWriter: Marker isolation & .gitignore auto-safety.
"""

import tempfile
from pathlib import Path
import pytest

from ctxguard.learn.scanner import LogEvent
from ctxguard.learn.digest import DigestBuilder
from ctxguard.learn.pivot_analyzer import PivotAnalyzer
from ctxguard.learn.loop_detector import LoopDetector
from ctxguard.learn.causality_extractor import CausalityExtractor
from ctxguard.learn.rule_renderer import RuleRenderer
from ctxguard.learn.atomic_writer import AtomicRuleWriter


def test_pivot_analyzer_path_correction():
    """Verify Success Correlation captures the Pivot Point when a file read fails then succeeds at another path."""
    analyzer = PivotAnalyzer()
    events = [
        LogEvent(
            timestamp=100.0,
            session_id="ses_1",
            tool_name="Read",
            tool_input={"path": "axion-formats/src/Entity.java"},
            role="assistant",
        ),
        LogEvent(
            timestamp=100.1,
            session_id="ses_1",
            tool_name="Read",
            output="FileNotFoundError: No such file or directory: axion-formats/src/Entity.java",
            is_error=True,
            role="tool",
        ),
        # Agent searches
        LogEvent(
            timestamp=100.2,
            session_id="ses_1",
            tool_name="Grep",
            tool_input={"query": "Entity"},
            output="axion-scala-common/src/Entity.scala:1: class Entity",
            is_error=False,
            role="tool",
        ),
        # Agent reads correct path
        LogEvent(
            timestamp=100.3,
            session_id="ses_1",
            tool_name="Read",
            tool_input={"path": "axion-scala-common/src/Entity.scala"},
            output="package axion\nclass Entity { def id = 1 }\n" * 10,
            is_error=False,
            role="tool",
        ),
    ]

    pivots = analyzer.analyze_events(events)
    assert len(pivots) == 1
    p = pivots[0]
    assert p.category == "Path Corrections"
    assert "axion-formats/src/Entity.java" in p.wrong_attempt
    assert "axion-scala-common/src/Entity.scala" in p.correct_solution


def test_pivot_analyzer_environment_mismatch():
    """Verify Success Correlation captures runtime environment pivots (e.g. python3 -> uv run python)."""
    analyzer = PivotAnalyzer()
    events = [
        LogEvent(
            timestamp=200.0,
            session_id="ses_2",
            tool_name="Bash",
            tool_input={"command": "python3 train.py"},
            role="assistant",
        ),
        LogEvent(
            timestamp=200.1,
            session_id="ses_2",
            tool_name="Bash",
            output="ModuleNotFoundError: No module named 'torch'",
            is_error=True,
            role="tool",
        ),
        LogEvent(
            timestamp=200.2,
            session_id="ses_2",
            tool_name="Bash",
            tool_input={"command": "uv run python train.py"},
            role="assistant",
        ),
        LogEvent(
            timestamp=200.3,
            session_id="ses_2",
            tool_name="Bash",
            output="Epoch 1/10: loss 0.42. Training completed successfully.",
            is_error=False,
            role="tool",
        ),
    ]

    pivots = analyzer.analyze_events(events)
    assert len(pivots) == 1
    p = pivots[0]
    assert p.category == "Environment"
    assert "python3 train.py" in p.wrong_attempt
    assert "uv run python train.py" in p.correct_solution


def test_refetch_loop_canonical_signature():
    """Verify Canonical Signature extraction strips paging noise to catch hidden 200 OK Re-fetch loops."""
    detector = LoopDetector(threshold=3)

    # 3 consecutive commands with different head/limit parameters (all returning 200 OK)
    events = [
        LogEvent(
            timestamp=300.0,
            session_id="ses_3",
            tool_name="Bash",
            tool_input={"command": "grep -rn 'AuthenticationError' . | head -50"},
            output="line 1\nline 2" * 25,
            is_error=False,
            role="tool",
        ),
        LogEvent(
            timestamp=300.1,
            session_id="ses_3",
            tool_name="Bash",
            tool_input={"command": "grep -rn 'AuthenticationError' . | head -100"},
            output="line 1\nline 2" * 50,
            is_error=False,
            role="tool",
        ),
        LogEvent(
            timestamp=300.2,
            session_id="ses_3",
            tool_name="Bash",
            tool_input={"command": "grep -rn 'AuthenticationError' . | head -200"},
            output="line 1\nline 2" * 100,
            is_error=False,
            role="tool",
        ),
    ]

    incidents = detector.detect_loops_from_events(events)
    refetch_loops = [inc for inc in incidents if inc.pattern_type == "re_fetch_loop"]
    assert len(refetch_loops) == 1
    assert "grep -rn 'authenticationerror' ." in refetch_loops[0].target_identifier
    assert refetch_loops[0].occurrence_count == 3


def test_user_rejection_preference_inversion():
    """Verify user interruption/rejection triggers command pattern preferences."""
    analyzer = PivotAnalyzer()
    events = [
        LogEvent(
            timestamp=400.0,
            session_id="ses_4",
            tool_name="Bash",
            tool_input={"command": "gradle build --continuous"},
            role="assistant",
        ),
        LogEvent(
            timestamp=400.1,
            session_id="ses_4",
            tool_name="user_input",
            output="n",
            role="user",
            user_interrupt=True,
        ),
    ]

    pivots = analyzer.analyze_events(events)
    assert len(pivots) == 1
    assert pivots[0].category == "Command Patterns"
    assert "gradle build --continuous" in pivots[0].wrong_attempt
    assert "manual user execution" in pivots[0].correct_solution


def test_digest_builder_filtering_and_budget():
    """Verify DigestBuilder filters out pure chitchat and retains high-density failure/recovery episodes."""
    builder = DigestBuilder(token_budget=500)

    events = [
        # Normal chitchat (should be omitted)
        LogEvent(timestamp=1.0, session_id="s1", tool_name="user_input", output="Hello AI", role="user"),
        LogEvent(timestamp=1.1, session_id="s1", tool_name="assistant_reply", output="Hello human!", role="assistant"),
        # Failure episode (should be kept)
        LogEvent(timestamp=2.0, session_id="s1", tool_name="Read", tool_input={"path": "foo.py"}, role="assistant"),
        LogEvent(timestamp=2.1, session_id="s1", tool_name="Read", output="FileNotFoundError: foo.py", is_error=True, role="tool"),
        LogEvent(timestamp=2.2, session_id="s1", tool_name="Read", tool_input={"path": "bar.py"}, output="print('hello')", is_error=False, role="tool"),
    ]

    digest = builder.build_digest(events)
    assert len(digest) >= 2
    assert any(e.is_error for e in digest)


def test_atomic_writer_and_gitignore_guard():
    """Verify AtomicRuleWriter idempotently replaces marker blocks and protects local files via .gitignore."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        rule_file = tmp_path / "CLAUDE.local.md"
        rule_file.write_text("# My Personal Notes\nDo not delete me!\n", encoding="utf-8")

        extractor = CausalityExtractor()
        renderer = RuleRenderer()

        from ctxguard.learn.pivot_analyzer import PivotIncident
        pivots = [
            PivotIncident(
                category="Path Corrections",
                wrong_attempt="src/old.py",
                correct_solution="src/new.py",
                rationale="Moved file",
            ),
        ]
        rules = extractor.extract_rules(pivots=pivots)
        rendered = renderer.render_markdown_block(rules)

        # 1. First write
        AtomicRuleWriter.write_rules_to_file(str(rule_file), rendered)
        content_v1 = rule_file.read_text(encoding="utf-8")
        assert "Do not delete me!" in content_v1
        assert "<!-- CTXGUARD_AUTO_RULES:START -->" in content_v1
        assert "src/new.py" in content_v1

        # 2. Check .gitignore was created and protects CLAUDE.local.md
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert "CLAUDE.local.md" in gitignore.read_text(encoding="utf-8")

        # 3. Second write with updated rules should idempotently replace without duplicating notes
        pivots_v2 = [
            PivotIncident(
                category="Environment",
                wrong_attempt="python3",
                correct_solution="uv run python",
                rationale="Use uv",
            ),
        ]
        rules_v2 = extractor.extract_rules(pivots=pivots_v2)
        rendered_v2 = renderer.render_markdown_block(rules_v2)
        AtomicRuleWriter.write_rules_to_file(str(rule_file), rendered_v2)

        content_v2 = rule_file.read_text(encoding="utf-8")
        assert "Do not delete me!" in content_v2
        assert "uv run python" in content_v2
        assert content_v2.count("<!-- CTXGUARD_AUTO_RULES:START -->") == 1
