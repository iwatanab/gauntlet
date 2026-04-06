"""
agents/base.py - Async stage runner with tool-use loop and structured outputs.

Tool-using stages still run in two phases:
1. A tool loop that executes permitted tools.
2. A synthesis pass if the model never self-terminates.

The client owns schema enforcement. This runner owns execution context and
tool scoping.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig
from gauntlet.models import TokenUsage
from gauntlet.tools import registry
from gauntlet.trace import PipelineTrace

T = TypeVar("T", bound=BaseModel)


async def run_agent(
    *,
    name: str,
    system: str,
    input_model: BaseModel,
    output_type: Type[T],
    config: AgentConfig,
    client: GauntletClient,
    trace: PipelineTrace,
    cycle: int,
    allowed_tools: list[str] | None = None,
) -> tuple[T, TokenUsage]:
    tools_available = registry.get_many(allowed_tools or [])
    tool_schemas = [tool.openai_schema() for tool in tools_available]
    tool_map = {tool.name: tool for tool in tools_available}

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": input_model.model_dump_json()}
    ]

    total_usage = TokenUsage()
    print(f"    [{name}] ", file=sys.stderr, end="", flush=True)

    parsed_final: T | None = None

    for iteration in range(config.max_tool_iters):
        parsed, messages, usage = await client.complete_structured(
            model=config.model,
            system=system,
            messages=messages,
            output_type=output_type,
            max_tokens=config.max_tokens,
            retries=config.retries if iteration == 0 else 1,
            tools=tool_schemas if tool_schemas else None,
        )
        total_usage = total_usage + usage

        if parsed is None:
            last_msg = messages[-1]
            tool_calls = last_msg.get("tool_calls") or []
            print(f"[tools:{len(tool_calls)}] ", file=sys.stderr, end="", flush=True)

            tool_results: list[dict[str, Any]] = []
            for tc in tool_calls:
                fn = tc.get("function", {}) if isinstance(tc, dict) else tc.function
                tool_name = fn.get("name", "") if isinstance(fn, dict) else fn.name
                tool_args = fn.get("arguments", "{}") if isinstance(fn, dict) else fn.arguments
                tool_call_id = tc.get("id", "") if isinstance(tc, dict) else tc.id

                tool = tool_map.get(tool_name)
                if tool is None:
                    result_str = f"Error: tool '{tool_name}' is not permitted for this stage."
                else:
                    try:
                        args = json.loads(tool_args) if isinstance(tool_args, str) else tool_args
                        result_str = await tool.execute(args)
                        trace.tool_called(
                            agent=name,
                            tool=tool_name,
                            query=args.get("query", json.dumps(args)[:80]),
                            result=result_str,
                            cycle=cycle,
                        )
                    except Exception as exc:
                        result_str = f"Tool error: {exc}"

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_str,
                })

            messages = messages + tool_results
            continue

        parsed_final = parsed
        break
    else:
        print("[synthesize] ", file=sys.stderr, end="", flush=True)
        messages = messages + [{
            "role": "user",
            "content": (
                "Based on the evidence you have retrieved above, "
                "produce your final structured response now."
            ),
        }]
        parsed_final, messages, usage = await client.complete_structured(
            model=config.model,
            system=system,
            messages=messages,
            output_type=output_type,
            max_tokens=config.max_tokens,
            retries=1,
            tools=None,
        )
        total_usage = total_usage + usage
        if parsed_final is None:
            raise RuntimeError(f"[{name}] synthesis phase returned tool calls instead of output")

    print(f"✓ {total_usage.total()}t", file=sys.stderr)
    return parsed_final, total_usage
