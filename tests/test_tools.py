"""test_tools.py - Tool registry, protocol compliance, and permission lists."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from gauntlet.config import AgentConfig
from gauntlet.models import ConstructorInput, EvaluatorInput, StageAudit, TokenUsage
from gauntlet.tools import (
    DocumentFetchTool,
    PlaceholderSearchTool,
    Tool,
    WebSearchTool,
    retrieval_tools,
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
    assert registry.get("pubmed_search") is not None
    assert registry.get("finance_search") is not None


def test_registry_get_many_skips_unknown():
    tools = registry.get_many(["web_search", "nonexistent"])
    assert len(tools) == 1


def test_placeholder_tool_is_tool_protocol():
    assert isinstance(PlaceholderSearchTool("x", "y", "z"), Tool)


def test_retrieval_tools_are_mode_gated():
    assert retrieval_tools("base") == ["web_search", "fetch_document"]
    assert retrieval_tools("clinical") == ["web_search", "fetch_document", "pubmed_search"]
    assert retrieval_tools("financial") == ["web_search", "fetch_document", "finance_search"]


def test_critique_has_no_tools():
    from gauntlet.agents.critique import run_critique_bundle
    import inspect

    assert "allowed_tools=None" in inspect.getsource(run_critique_bundle)


def test_resolver_has_no_tools():
    from gauntlet.agents.resolver import run_resolver
    import inspect

    assert "allowed_tools=None" in inspect.getsource(run_resolver)


@pytest.mark.asyncio
async def test_constructor_adds_mode_prompt_and_tools():
    from gauntlet.agents.constructor import run_constructor

    with patch("gauntlet.agents.constructor.run_agent", new_callable=AsyncMock) as runner:
        runner.return_value = (SimpleNamespace(grounds=[], warrant=None, backing=None, qualifier="presumably"), TokenUsage())
        await run_constructor(
            ConstructorInput(claim="x"),
            AgentConfig(model="test"),
            object(),
            SimpleNamespace(agent_complete=lambda *_args, **_kwargs: None),
            1,
            "clinical",
        )
    kwargs = runner.await_args.kwargs
    assert "Clinical mode is active" in kwargs["system"]
    assert kwargs["allowed_tools"] == ["web_search", "fetch_document", "pubmed_search"]


@pytest.mark.asyncio
async def test_evaluator_adds_mode_prompt_and_tools():
    from gauntlet.agents.evaluator import run_evaluator

    with patch("gauntlet.agents.evaluator.run_agent", new_callable=AsyncMock) as runner:
        runner.return_value = (SimpleNamespace(acceptance=True, required_gap=None), TokenUsage())
        await run_evaluator(
            EvaluatorInput(
                claim="x",
                grounds=[],
                warrant=None,
                backing=None,
                qualifier="presumably",
                domain_standard="standard",
                stage_audit=StageAudit(confrontation="ok", opening="ok", argumentation="ok", blocked=False),
                rule_violations=[],
            ),
            AgentConfig(model="test"),
            object(),
            SimpleNamespace(agent_complete=lambda *_args, **_kwargs: None),
            1,
            "financial",
        )
    kwargs = runner.await_args.kwargs
    assert "Financial mode is active" in kwargs["system"]
    assert kwargs["allowed_tools"] == ["web_search", "fetch_document", "finance_search"]


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
