"""
trace.py - Hierarchical per-position trace accumulation.

The public trace is intentionally stage-shaped rather than event-shaped:
preflight facts, per-cycle stage summaries, and final halt reason.
"""

from __future__ import annotations

from typing import Iterator, Literal

from gauntlet.models import (
    CycleTrace,
    PositionMetrics,
    PositionTrace,
    PreflightSummary,
    StageSummary,
    StageTrace,
    TokenUsage,
    ToolCallTrace,
)


_STAGE_KEY = {
    "Constructor": "constructor",
    "Critique Bundle": "critique",
    "Evaluator": "evaluator",
    "Resolver": "resolver",
}


class PipelineTrace:
    """Mutable hierarchical trace accumulator for one position."""

    def __init__(self, position: str) -> None:
        self._trace = PositionTrace(position=position)
        self._pending_tools: dict[tuple[int, str], list[ToolCallTrace]] = {}

    def _cycle(self, cycle: int) -> CycleTrace:
        if self._trace.cycles and self._trace.cycles[-1].cycle == cycle:
            return self._trace.cycles[-1]
        item = CycleTrace(cycle=cycle)
        self._trace.cycles.append(item)
        return item

    def _stage_key(self, agent: str) -> str:
        return _STAGE_KEY.get(agent, agent.lower())

    def _stages(self, cycle: CycleTrace) -> Iterator[StageTrace]:
        for stage in (cycle.constructor, cycle.critique, cycle.evaluator, cycle.resolver):
            if stage is not None:
                yield stage

    def set_preflight(self, summary: PreflightSummary, tokens: TokenUsage | None = None) -> None:
        self._trace.preflight = summary
        if tokens:
            self._trace.preflight_usage = self._trace.preflight_usage + tokens

    def cycle_start(self, cycle: int, total: int) -> None:
        self._cycle(cycle).decision = f"cycle_started:{cycle}/{total}"

    def tool_called(self, agent: str, tool: str, query: str, result: str, cycle: int) -> None:
        key = (cycle, self._stage_key(agent))
        self._pending_tools.setdefault(key, []).append(ToolCallTrace(
            tool=tool,
            query=query,
            result_chars=len(result),
            result_preview=result[:300],
        ))

    def agent_complete(
        self,
        agent: str,
        cycle: int,
        tokens: TokenUsage,
        summary: StageSummary,
        status: Literal["completed", "blocked", "rejected"] = "completed",
    ) -> None:
        stage_key = self._stage_key(agent)
        setattr(
            self._cycle(cycle),
            stage_key,
            StageTrace(
                status=status,
                tokens=tokens,
                summary=summary,
                tool_calls=self._pending_tools.pop((cycle, stage_key), []),
            ),
        )

    def critique_blocked(self, cycle: int, rule: str, stage: str, required_gap: str) -> None:
        cycle_trace = self._cycle(cycle)
        if cycle_trace.critique:
            cycle_trace.critique.status = "blocked"
            cycle_trace.critique.summary.blocking_rule = rule
            cycle_trace.critique.summary.blocking_stage = stage
            cycle_trace.critique.summary.required_gap = required_gap
        cycle_trace.decision = "critique_blocked"

    def evaluator_rejected(self, cycle: int, required_gap: str) -> None:
        cycle_trace = self._cycle(cycle)
        if cycle_trace.evaluator:
            cycle_trace.evaluator.status = "rejected"
            cycle_trace.evaluator.summary.required_gap = required_gap
        cycle_trace.decision = "evaluator_rejected"

    def no_progress_halt(self, cycle: int, repeated_gap: str) -> None:
        self._trace.halt_reason = "no_progress"
        cycle_trace = self._cycle(cycle)
        cycle_trace.decision = "no_progress_halt"
        for stage in (cycle_trace.critique, cycle_trace.evaluator):
            if stage is not None:
                stage.summary.repeated_gap = repeated_gap

    def verdict_reached(self, cycle: int, verdict: str) -> None:
        self._cycle(cycle).decision = f"verdict:{verdict}"
        self._trace.halt_reason = verdict

    def snapshot(self) -> PositionTrace:
        self._trace.metrics = PositionMetrics(
            stage_calls=sum(1 for cycle in self._trace.cycles for _stage in self._stages(cycle)),
            tool_calls=sum(len(stage.tool_calls) for cycle in self._trace.cycles for stage in self._stages(cycle)),
            cycles_used=len(self._trace.cycles),
        )
        return self._trace.model_copy(deep=True)
