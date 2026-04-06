"""
client.py - Async OpenRouter client.

The client owns schema enforcement. Stages ask for typed output and receive
validated models, with JSON-schema mode when the provider likely supports it
and a JSON-object fallback otherwise.
"""

from __future__ import annotations

import json
import re
from typing import Any, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError as PydanticValidationError

from gauntlet.config import GauntletConfig
from gauntlet.models import TokenUsage

T = TypeVar("T", bound=BaseModel)

_NO_JSON_MODE: frozenset[str] = frozenset({
    "meta-llama/llama-3",
    "mistralai/mistral-7b",
    "google/gemma",
})

_JSON_SCHEMA_PREFIXES: tuple[str, ...] = (
    "openai/",
    "anthropic/",
)


def _supports_json_mode(model: str) -> bool:
    return not any(model.startswith(p) for p in _NO_JSON_MODE)


def _supports_json_schema(model: str) -> bool:
    return _supports_json_mode(model) and any(model.startswith(p) for p in _JSON_SCHEMA_PREFIXES)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _extract_usage(response: Any) -> TokenUsage:
    if response.usage:
        return TokenUsage(
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
        )
    return TokenUsage()


class GauntletClient:
    """Async OpenRouter client. One instance per application lifetime."""

    def __init__(self, config: GauntletConfig) -> None:
        self._oai = AsyncOpenAI(
            api_key=config.openrouter_api_key,
            base_url=config.openrouter_base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/gauntlet-ai/gauntlet",
                "X-Title": "Gauntlet Argumentation Harness",
            },
        )

    async def complete_text(
        self,
        *,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 256,
    ) -> tuple[str, TokenUsage]:
        response = await self._oai.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or "", _extract_usage(response)

    async def complete_structured(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        output_type: Type[T],
        max_tokens: int,
        retries: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[T | None, list[dict[str, Any]], TokenUsage]:
        total = TokenUsage()
        last_err: Exception | None = None
        sys_messages = [{"role": "system", "content": system}]
        schema = output_type.model_json_schema()

        for attempt in range(retries + 1):
            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": sys_messages + messages,
            }
            if tools:
                kwargs["tools"] = tools
            elif _supports_json_schema(model):
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "gauntlet_response",
                        "schema": schema,
                        "strict": True,
                    },
                }
            elif _supports_json_mode(model):
                kwargs["response_format"] = {"type": "json_object"}

            response = await self._oai.chat.completions.create(**kwargs)
            total = total + _extract_usage(response)
            msg = response.choices[0].message

            if msg.tool_calls:
                messages = messages + [msg.model_dump(exclude_none=True)]
                return None, messages, total

            text = msg.content or ""
            try:
                parsed = json.loads(_strip_fences(text))
                result = output_type.model_validate(parsed)
                return result, messages, total
            except (json.JSONDecodeError, ValueError, PydanticValidationError) as exc:
                last_err = exc
                if attempt < retries:
                    messages = messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": (
                            f"Your response did not match the required schema: {exc}\n"
                            f"Required schema:\n{json.dumps(schema, indent=2)}\n"
                            "Respond with a corrected JSON object only."
                        )},
                    ]

        raise ValueError(
            f"Model failed to produce valid structured output after {retries + 1} attempts: {last_err}"
        )
