"""test_tools.py - Tool registry, protocol compliance, and permission lists."""
from __future__ import annotations

from gauntlet.tools import (
    CONSTRUCTOR_TOOLS,
    EVALUATOR_TOOLS,
    DocumentFetchTool,
    Tool,
    WebSearchTool,
    registry,
)


def test_web_search_is_tool_protocol():
    assert isinstance(WebSearchTool(), Tool)


def test_fetch_document_is_tool_protocol():
    assert isinstance(DocumentFetchTool(), Tool)


def test_web_search_schema_openai_compatible():
    schema = WebSearchTool().openai_schema()
    assert schema["type"] == "function"
    fn = schema["function"]
    assert fn["name"] == "web_search"
    assert "parameters" in fn
    assert "query" in fn["parameters"]["required"]


def test_fetch_document_schema_openai_compatible():
    schema = DocumentFetchTool().openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "fetch_document"


def test_registry_has_builtins():
    assert registry.get("web_search") is not None
    assert registry.get("fetch_document") is not None


def test_registry_get_many_skips_unknown():
    tools = registry.get_many(["web_search", "nonexistent"])
    assert len(tools) == 1


def test_constructor_tools_contain_web_search():
    assert "web_search" in CONSTRUCTOR_TOOLS
    assert "fetch_document" in CONSTRUCTOR_TOOLS


def test_evaluator_tools_contain_web_search():
    assert "web_search" in EVALUATOR_TOOLS
    assert "fetch_document" in EVALUATOR_TOOLS


def test_critique_has_no_tools():
    from gauntlet.agents.critique import run_critique_bundle
    import inspect

    assert "allowed_tools=None" in inspect.getsource(run_critique_bundle)


def test_resolver_has_no_tools():
    from gauntlet.agents.resolver import run_resolver
    import inspect

    assert "allowed_tools=None" in inspect.getsource(run_resolver)


def test_register_custom_tool():
    class CalcTool:
        name = "_test_calc_tool"
        description = "Test tool"

        def openai_schema(self):
            return {"type": "function", "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            }}

        async def execute(self, args):
            return "42"

    registry.register(CalcTool())
    assert registry.get("_test_calc_tool") is not None
    del registry._tools["_test_calc_tool"]
