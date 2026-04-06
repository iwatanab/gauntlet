"""test_client.py - Structured-output client behavior."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig, GauntletConfig


class DemoOutput(BaseModel):
    value: str


def _cfg() -> GauntletConfig:
    return GauntletConfig(
        primary=AgentConfig(model="openai/test"),
        preflight=AgentConfig(model="openai/preflight"),
        openrouter_api_key="k",
        openrouter_base_url="u",
    )


def _response(content: str):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
    )


@pytest.mark.asyncio
async def test_complete_structured_uses_json_schema_for_supported_models():
    calls: list[dict] = []

    async def create(**kwargs):
        calls.append(kwargs)
        return _response('{"value":"ok"}')

    client = GauntletClient(_cfg())
    client._oai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result, _messages, usage = await client.complete_structured(
        model="openai/gpt-4.1",
        system="system",
        messages=[{"role": "user", "content": "hi"}],
        output_type=DemoOutput,
        max_tokens=100,
        retries=0,
    )

    assert result is not None
    assert result.value == "ok"
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert usage.total() == 14


@pytest.mark.asyncio
async def test_complete_structured_falls_back_to_json_object():
    calls: list[dict] = []

    async def create(**kwargs):
        calls.append(kwargs)
        return _response('{"value":"ok"}')

    client = GauntletClient(_cfg())
    client._oai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result, _messages, _usage = await client.complete_structured(
        model="cohere/command-r",
        system="system",
        messages=[{"role": "user", "content": "hi"}],
        output_type=DemoOutput,
        max_tokens=100,
        retries=0,
    )

    assert result is not None
    assert calls[0]["response_format"]["type"] == "json_object"


@pytest.mark.asyncio
async def test_complete_structured_retries_on_schema_failure():
    calls = 0

    async def create(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _response('{"wrong":"shape"}')
        return _response('{"value":"fixed"}')

    client = GauntletClient(_cfg())
    client._oai = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    result, messages, _usage = await client.complete_structured(
        model="openai/gpt-4.1",
        system="system",
        messages=[{"role": "user", "content": "hi"}],
        output_type=DemoOutput,
        max_tokens=100,
        retries=1,
    )

    assert result is not None
    assert result.value == "fixed"
    assert calls == 2
    assert any(msg["role"] == "assistant" for msg in messages)
