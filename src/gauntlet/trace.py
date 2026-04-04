"""
trace.py — Pipeline traceability as a first-class output.

Every meaningful step emits a TraceEvent. The full trace is included in the
API response, answering questions that matter in high-stakes decisions:
  - What evidence did the Constructor retrieve and from where?
  - What scheme did the Classifier assign, and which CQs were unanswered?
  - What rule did the Auditor trigger?
  - What did the Evaluator require before it would accept?
  - What changed during each translation step?
  - Which attacks survived and which were reinstated?

Events are structured (not free-form text) so downstream tools can filter,
display, and summarise them without string parsing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from gauntlet.models import TokenUsage


class EventKind(str, Enum):
    # System-level
    pipeline_start      = "pipeline_start"
    contrary_generated  = "contrary_generated"
    pipeline_complete   = "pipeline_complete"

    # Per-cycle
    cycle_start         = "cycle_start"

    # Per-agent
    agent_start         = "agent_start"
    agent_complete      = "agent_complete"
    tool_called         = "tool_called"

    # Translation
    translation_applied = "translation_applied"

    # Decision points
    auditor_blocked     = "auditor_blocked"
    evaluator_rejected  = "evaluator_rejected"
    no_progress_halt    = "no_progress_halt"
    verdict_reached     = "verdict_reached"


class TraceEvent(BaseModel):
    """
    A single timestamped pipeline event.

    position: "claim" | "contrary" | "system"
    cycle:    0 for system events, 1..n for cycle events

    Detail schemas per kind — all fields are strings or primitives:
      pipeline_start:      {claim, domain_standard, termination_limit}
      contrary_generated:  {contrary}
      pipeline_complete:   {comparison, recommended_position}
      cycle_start:         {cycle, total_cycles}
      agent_start:         {agent}
      agent_complete:      {agent, ...agent-specific...}
        Constructor:  {grounds_count, qualifier, warrant_preview, tools_used}
        Classifier:   {scheme, open_attacks_count, answered_cqs, unanswered_cqs, burden_bearer}
        Auditor:      {blocked, violations_count, blocking_rule, gap_preview}
        Evaluator:    {accepted, gap_preview}
        Resolver:     {verdict, surviving_attacks, defeated_attacks}
      tool_called:         {agent, tool, query, result_chars, result_preview}
      translation_applied: {qualifier_before, qualifier_after, grounds_reordered,
                            warrant_rewritten, attacks_neutralised, gap_normalised}
      auditor_blocked:     {rule, stage, gap}
      evaluator_rejected:  {gap}
      no_progress_halt:    {repeated_gap, cycle}
      verdict_reached:     {verdict, cycles_used}
    """
    ts:       str                  # ISO 8601 UTC
    kind:     EventKind
    position: str                  # "claim" | "contrary" | "system"
    cycle:    int                  = 0
    tokens:   Optional[TokenUsage] = None
    detail:   dict[str, Any]       = Field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PipelineTrace:
    """
    Mutable event accumulator for one pipeline run (claim or contrary).
    Passed into agent runners so they can record tool calls inline.
    Call .snapshot() to get an immutable list of events for the response.
    """

    def __init__(self, position: str) -> None:
        self.position = position
        self._events: list[TraceEvent] = []

    def _emit(
        self,
        kind: EventKind,
        cycle: int = 0,
        tokens: Optional[TokenUsage] = None,
        **detail: Any,
    ) -> None:
        self._events.append(TraceEvent(
            ts=_now(),
            kind=kind,
            position=self.position,
            cycle=cycle,
            tokens=tokens,
            detail=dict(detail),
        ))

    # ── Named emitters — explicit at call sites ────────────────────────────────

    def pipeline_start(self, claim: str, domain_standard: str, termination_limit: int) -> None:
        self._emit(EventKind.pipeline_start,
                   claim=claim, domain_standard=domain_standard,
                   termination_limit=termination_limit)

    def cycle_start(self, cycle: int, total: int) -> None:
        self._emit(EventKind.cycle_start, cycle=cycle,
                   cycle_number=cycle, total_cycles=total)

    def agent_start(self, agent: str, cycle: int) -> None:
        self._emit(EventKind.agent_start, cycle=cycle, agent=agent)

    def agent_complete(self, agent: str, cycle: int, tokens: TokenUsage, **detail: Any) -> None:
        self._emit(EventKind.agent_complete, cycle=cycle, tokens=tokens,
                   agent=agent, **detail)

    def tool_called(self, agent: str, tool: str, query: str, result: str, cycle: int) -> None:
        self._emit(EventKind.tool_called, cycle=cycle,
                   agent=agent, tool=tool, query=query,
                   result_chars=len(result), result_preview=result[:300])

    def translation_applied(
        self, cycle: int,
        qualifier_before: str, qualifier_after: str,
        grounds_reordered: bool,
        warrant_rewritten: bool,
        attacks_neutralised: bool,
        gap_normalised: bool,
        tokens: TokenUsage,
    ) -> None:
        self._emit(EventKind.translation_applied, cycle=cycle, tokens=tokens,
                   qualifier_before=qualifier_before, qualifier_after=qualifier_after,
                   grounds_reordered=grounds_reordered,
                   warrant_rewritten=warrant_rewritten,
                   attacks_neutralised=attacks_neutralised,
                   gap_normalised=gap_normalised)

    def auditor_blocked(self, cycle: int, rule: str, stage: str, gap: str) -> None:
        self._emit(EventKind.auditor_blocked, cycle=cycle, rule=rule, stage=stage, gap=gap)

    def evaluator_rejected(self, cycle: int, gap: str) -> None:
        self._emit(EventKind.evaluator_rejected, cycle=cycle, gap=gap)

    def no_progress_halt(self, cycle: int, repeated_gap: str) -> None:
        self._emit(EventKind.no_progress_halt, cycle=cycle, repeated_gap=repeated_gap)

    def verdict_reached(self, cycle: int, verdict: str) -> None:
        self._emit(EventKind.verdict_reached, cycle=cycle,
                   verdict=verdict, cycles_used=cycle)

    def snapshot(self) -> list[TraceEvent]:
        return list(self._events)

    def print_progress(self) -> None:
        """Write a compact progress line to stderr for live monitoring."""
        import sys
        last = self._events[-1] if self._events else None
        if last:
            agent = last.detail.get("agent", "")
            suffix = f" [{agent}]" if agent else ""
            print(f"  [{self.position}] {last.kind}{suffix}", file=sys.stderr, flush=True)
