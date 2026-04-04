"""
agents/base.py — Async agent runner with tool-use loop and tracing.

TWO-PHASE EXECUTION:
  Phase 1 — Tool loop: run until the model stops calling tools OR exhausts
    max_tool_iters. Accumulates all retrieved evidence in the message history.
  Phase 2 — Synthesis: one dedicated call with tools=None. The model sees
    everything it retrieved and is asked to produce its final JSON output.
    This phase only runs if the tool loop did not naturally self-terminate.

The two phases are separated because some models (e.g. Gemini) do not
self-terminate the tool loop — they continue calling tools indefinitely
rather than deciding to finalise. Merging synthesis into the tool loop
forces a choice: either lie about "sufficient evidence" or never get output.
The two-phase split is honest: Phase 2 says "based on what you found" — always true.

Permission enforcement is structural: only tools in `allowed_tools` are
passed to the API call. An agent that isn't given a tool cannot call it.

Every tool call and every completion are emitted to the PipelineTrace.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError as PydanticValidationError

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
    """
    Run one agent invocation with tool-use loop.

    Args:
        name:          Display name for tracing and logs.
        system:        Full system prompt (theory + calibration examples).
        input_model:   Scoped Pydantic input — only designated fields.
        output_type:   Expected output Pydantic model for validation.
        config:        Model, token limit, retry, and tool-iteration settings.
        client:        OpenRouter client.
        trace:         PipelineTrace accumulator — receives all events.
        cycle:         Current pipeline cycle number (for trace attribution).
        allowed_tools: Tool names this agent may call. Structurally enforced.
    """
    tools_available = registry.get_many(allowed_tools or [])
    tool_schemas    = [t.openai_schema() for t in tools_available]
    tool_map        = {t.name: t for t in tools_available}

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": input_model.model_dump_json(indent=2)}
    ]

    total_usage = TokenUsage()
    trace.agent_start(name, cycle)
    print(f"    [{name}] ", file=sys.stderr, end="", flush=True)

    # ── Phase 1: Tool loop ────────────────────────────────────────────────────
    # Run until the model self-terminates (returns JSON) or exhausts the budget.
    # Self-termination is the happy path; budget exhaustion triggers Phase 2.
    naturally_terminated = False

    for _iteration in range(config.max_tool_iters):
        parsed, messages, usage = await client.complete_json(
            model=config.model,
            system=system,
            messages=messages,
            max_tokens=config.max_tokens,
            retries=config.retries if _iteration == 0 else 1,
            tools=tool_schemas if tool_schemas else None,
        )
        total_usage = total_usage + usage

        # ── Tool calls — execute and continue ─────────────────────────────────
        if parsed is None:
            last_msg   = messages[-1]
            tool_calls = last_msg.get("tool_calls") or []
            print(f"[tools:{len(tool_calls)}] ", file=sys.stderr, end="", flush=True)

            tool_results: list[dict[str, Any]] = []
            for tc in tool_calls:
                # OpenAI SDK returns objects; model_dump converts to dicts
                fn    = tc.get("function", {}) if isinstance(tc, dict) else tc.function
                tname = fn.get("name", "")     if isinstance(fn, dict) else fn.name
                targs = fn.get("arguments", "{}") if isinstance(fn, dict) else fn.arguments
                tc_id = tc.get("id", "")       if isinstance(tc, dict) else tc.id

                tool = tool_map.get(tname)
                if tool is None:
                    result_str = f"Error: tool '{tname}' is not permitted for this agent."
                else:
                    try:
                        args       = json.loads(targs) if isinstance(targs, str) else targs
                        result_str = await tool.execute(args)
                        # Emit tool use to trace
                        trace.tool_called(
                            agent=name,
                            tool=tname,
                            query=args.get("query", json.dumps(args)[:80]),
                            result=result_str,
                            cycle=cycle,
                        )
                    except Exception as e:
                        result_str = f"Tool error: {e}"

                tool_results.append({
                    "role":         "tool",
                    "tool_call_id": tc_id,
                    "content":      result_str,
                })

            messages = messages + tool_results
            continue

        # Model returned JSON — self-terminated
        naturally_terminated = True
        parsed_final = parsed
        break

    # ── Phase 2: Synthesis (only if tool loop did not self-terminate) ─────────
    # The model has accumulated all retrieved evidence in the message history.
    # Ask it to synthesize — no tools, no fiction about sufficiency.
    if not naturally_terminated:
        print(f"[synthesize] ", file=sys.stderr, end="", flush=True)
        messages = messages + [{
            "role": "user",
            "content": (
                "Based on the evidence you have retrieved above, "
                "produce your final JSON response now."
            ),
        }]
        parsed_final, messages, usage = await client.complete_json(
            model=config.model,
            system=system,
            messages=messages,
            max_tokens=config.max_tokens,
            retries=config.retries,
            tools=None,  # synthesis phase — no tool calls permitted
        )
        total_usage = total_usage + usage
        if parsed_final is None:
            raise RuntimeError(f"[{name}] synthesis phase returned tool calls instead of JSON")

    # ── Validate against output schema ────────────────────────────────────────
    try:
        result = output_type.model_validate(parsed_final)
        print(f"✓ {total_usage.total()}t", file=sys.stderr)
        return result, total_usage

    except PydanticValidationError as e:
        # One schema-correction retry
        messages = messages + [
            {"role": "assistant", "content": json.dumps(parsed_final)},
            {"role": "user",      "content": (
                f"Your response did not match the required schema: {e}\n"
                f"Required schema:\n{json.dumps(output_type.model_json_schema(), indent=2)}\n"
                "Please respond with a corrected JSON object only."
            )},
        ]
        parsed2, messages, usage2 = await client.complete_json(
            model=config.model,
            system=system,
            messages=messages,
            max_tokens=config.max_tokens,
            retries=1,
            tools=None,  # schema retry — no tools
        )
        total_usage = total_usage + usage2
        if parsed2 is not None:
            result = output_type.model_validate(parsed2)
            print(f"✓(retry) {total_usage.total()}t", file=sys.stderr)
            return result, total_usage
        raise RuntimeError(f"[{name}] schema validation failed after retry: {e}")
