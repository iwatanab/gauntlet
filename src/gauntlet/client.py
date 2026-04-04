"""
client.py — Async OpenRouter client.

Key design decisions:
  - complete_text() returns (str, TokenUsage) — usage is never discarded
  - complete_json() handles the tool-call/JSON branching + retry loop
  - Model capability registry gates json_mode per model prefix
  - One client instance per application lifetime (created at startup)
"""

from __future__ import annotations

import json
import re
from typing import Any

from openai import AsyncOpenAI

from gauntlet.config import GauntletConfig
from gauntlet.models import TokenUsage

# Models known not to support response_format: json_object.
# Add prefixes as you encounter them on OpenRouter.
_NO_JSON_MODE: frozenset[str] = frozenset({
    "meta-llama/llama-3",
    "mistralai/mistral-7b",
    "google/gemma",
})


def _supports_json_mode(model: str) -> bool:
    return not any(model.startswith(p) for p in _NO_JSON_MODE)


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that some models wrap JSON in."""
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
                "X-Title":      "Gauntlet Argumentation Harness",
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
        """
        Plain text completion. Returns (text, usage).
        Used for translation layer and contrary generation.
        Usage is ALWAYS returned — never silently discarded.
        """
        response = await self._oai.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return response.choices[0].message.content or "", _extract_usage(response)

    async def complete_json(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        retries: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], TokenUsage]:
        """
        Completion with JSON parsing and retry on failure.

        Returns:
          (None,  updated_messages, usage)  — model made tool calls; caller executes them
          (dict,  updated_messages, usage)  — parsed JSON response
        Raises ValueError after retries exhausted.
        """
        total = TokenUsage()
        last_err: Exception | None = None
        sys_messages = [{"role": "system", "content": system}]

        for attempt in range(retries + 1):
            kwargs: dict[str, Any] = {
                "model":      model,
                "max_tokens": max_tokens,
                "messages":   sys_messages + messages,
            }
            if tools:
                kwargs["tools"] = tools
            elif _supports_json_mode(model):
                kwargs["response_format"] = {"type": "json_object"}

            response = await self._oai.chat.completions.create(**kwargs)
            total    = total + _extract_usage(response)
            msg      = response.choices[0].message

            # Tool calls — return to caller's tool loop for execution
            if msg.tool_calls:
                messages = messages + [msg.model_dump(exclude_none=True)]
                return None, messages, total

            text = msg.content or ""
            try:
                parsed = json.loads(_strip_fences(text))
                return parsed, messages, total
            except (json.JSONDecodeError, ValueError) as e:
                last_err = e
                if attempt < retries:
                    messages = messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": (
                            f"That response could not be parsed as JSON: {e}. "
                            "Respond with a valid JSON object only — no markdown, "
                            "no preamble, no explanation."
                        )},
                    ]

        raise ValueError(
            f"Model failed to produce valid JSON after {retries + 1} attempts: {last_err}"
        )
