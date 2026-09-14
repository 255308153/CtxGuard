"""Unit tests for dead loop and failure pattern detection."""

from ctxguard.learn.loop_detector import LoopDetector, LoopIncident


def test_detect_repeated_missing_file():
    detector = LoopDetector(threshold=3)

    messages = [
        {"role": "user", "content": "Read config"},
        {"role": "tool", "content": "FileNotFoundError: src/secret_config.json"},
        {"role": "assistant", "content": "Trying again..."},
        {"role": "tool", "content": "No such file or directory: 'src/secret_config.json'"},
        {"role": "assistant", "content": "Let me check again..."},
        {"role": "tool", "content": "FileNotFoundError: src/secret_config.json"},
    ]

    incidents = detector.detect_loops_from_messages(messages)
    assert len(incidents) == 1
    assert incidents[0].pattern_type == "repeated_query"
    assert incidents[0].target_identifier == "src/secret_config.json"
    assert incidents[0].occurrence_count == 3


def test_detect_repeated_tool_errors():
    detector = LoopDetector(threshold=3)

    messages = [
        {"role": "user", "content": "Run tests"},
        {"role": "tool", "name": "run_command", "content": "Error: Command 'pytest' failed with code 1"},
        {"role": "tool", "name": "run_command", "content": "Error: Command 'pytest' failed with code 1"},
        {"role": "tool", "name": "run_command", "content": "Error: Command 'pytest' failed with code 1"},
    ]

    incidents = detector.detect_loops_from_messages(messages)
    assert len(incidents) == 1
    assert incidents[0].pattern_type == "repeated_tool_failure"
    assert incidents[0].target_identifier == "run_command"
    assert incidents[0].occurrence_count == 3
