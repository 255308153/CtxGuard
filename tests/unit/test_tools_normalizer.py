import pytest
from ctxguard.core.guards.tools_normalizer import ToolsNormalizer
from ctxguard.core.context import NormalizedRequest, Message


def test_tools_normalizer_empty_or_none():
    normalizer = ToolsNormalizer()
    req = NormalizedRequest(protocol="openai", model="gpt-4o", messages=[Message(role="user", content="hi")])
    normalizer.normalize_request_tools(req)
    assert req.tools is None


def test_tools_normalizer_openai_format():
    normalizer = ToolsNormalizer()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "zebra_tool",
                "description": "Zebra",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "z_param": {"type": "string", "description": "Z param"},
                        "a_param": {"type": "number", "description": "A param"},
                    },
                    "required": ["z_param", "a_param"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "alpha_tool",
                "description": "Alpha",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "beta": {"type": "string"},
                        "alpha": {"type": "string"},
                    },
                },
            },
        },
    ]
    req = NormalizedRequest(
        protocol="openai",
        model="gpt-4o",
        messages=[Message(role="user", content="hi")],
        tools=tools,
    )
    normalizer.normalize_request_tools(req)

    # Check tool ordering by name: alpha_tool comes before zebra_tool
    assert len(req.tools) == 2
    assert req.tools[0]["function"]["name"] == "alpha_tool"
    assert req.tools[1]["function"]["name"] == "zebra_tool"

    # Check properties key order in alpha_tool
    alpha_props = list(req.tools[0]["function"]["parameters"]["properties"].keys())
    assert alpha_props == ["alpha", "beta"]

    # Check properties key order in zebra_tool
    zebra_props = list(req.tools[1]["function"]["parameters"]["properties"].keys())
    assert zebra_props == ["a_param", "z_param"]


def test_tools_normalizer_anthropic_format():
    normalizer = ToolsNormalizer()
    tools = [
        {
            "name": "write_file",
            "description": "Write file",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "bash",
            "description": "Run bash",
            "input_schema": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "number"},
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    ]
    req = NormalizedRequest(
        protocol="anthropic",
        model="claude-3-5-sonnet",
        messages=[Message(role="user", content="hi")],
        tools=tools,
    )
    normalizer.normalize_request_tools(req)

    # Check tool ordering by name: bash comes before write_file
    assert len(req.tools) == 2
    assert req.tools[0]["name"] == "bash"
    assert req.tools[1]["name"] == "write_file"

    # Check input_schema properties key order
    bash_props = list(req.tools[0]["input_schema"]["properties"].keys())
    assert bash_props == ["command", "timeout"]

    write_props = list(req.tools[1]["input_schema"]["properties"].keys())
    assert write_props == ["content", "path"]


def test_tools_normalizer_nested_recursive_schema():
    normalizer = ToolsNormalizer()
    schema = {
        "z": 1,
        "a": {
            "d": 4,
            "c": [
                {"y": 2, "x": 1},
                3,
            ],
        },
    }
    normalized = normalizer.normalize_schema(schema)
    assert list(normalized.keys()) == ["a", "z"]
    assert list(normalized["a"].keys()) == ["c", "d"]
    assert list(normalized["a"]["c"][0].keys()) == ["x", "y"]
