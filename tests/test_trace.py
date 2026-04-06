"""
test_trace.py - Hierarchical PipelineTrace accumulation.

The public trace is position-shaped: preflight facts, cycles, stage
summaries, and halt reason.
"""
from __future__ import annotations

from gauntlet.models import PreflightSummary, StageSummary, TokenUsage, Verdict
from gauntlet.trace import PipelineTrace


def make_trace(pos: str = "claim") -> PipelineTrace:
    return PipelineTrace(pos)


def test_preflight_summary_and_usage_accumulate():
    trace = make_trace()
    trace.set_preflight(
        PreflightSummary(
            claim="test claim",
            domain_standard="balance of probabilities",
            termination_limit=3,
        ),
        TokenUsage(input_tokens=15, output_tokens=3),
    )
    snapshot = trace.snapshot()
    assert snapshot.preflight is not None
    assert snapshot.preflight.claim == "test claim"
    assert snapshot.preflight.domain_standard == "balance of probabilities"
    assert snapshot.preflight_usage.total() == 18


def test_constructor_stage_collects_tool_calls():
    trace = make_trace("contrary")
    trace.cycle_start(1, 3)
    trace.tool_called("Constructor", "web_search", "NICE NG185", "Result: " + "x" * 400, cycle=1)
    trace.agent_complete(
        "Constructor",
        cycle=1,
        tokens=TokenUsage(input_tokens=100, output_tokens=40),
        summary=StageSummary(
            grounds_count=3,
            qualifier="presumably",
            warrant_preview="It is assumed that: x",
            has_backing=False,
        ),
    )
    stage = trace.snapshot().cycles[0].constructor
    assert stage is not None
    assert stage.tokens.total() == 140
    assert stage.summary.grounds_count == 3
    assert stage.tool_calls[0].tool == "web_search"
    assert stage.tool_calls[0].result_chars == 408


def test_critique_blocked_updates_stage_status():
    trace = make_trace()
    trace.cycle_start(1, 3)
    trace.agent_complete(
        "Critique Bundle",
        cycle=1,
        tokens=TokenUsage(),
        summary=StageSummary(
            scheme="argument_from_sign",
            open_attacks_count=0,
            answered_cqs=0,
            unanswered_cqs=0,
            blocked=True,
            violations_count=0,
            blocking_violations=0,
        ),
    )
    trace.critique_blocked(1, "Rule 2 - Burden", "opening", "Required: cost on table")
    cycle = trace.snapshot().cycles[0]
    assert cycle.critique is not None
    assert cycle.critique.status == "blocked"
    assert cycle.critique.summary.blocking_rule == "Rule 2 - Burden"
    assert cycle.decision == "critique_blocked"


def test_evaluator_rejected_updates_stage_status():
    trace = make_trace()
    trace.cycle_start(2, 3)
    trace.agent_complete(
        "Evaluator",
        cycle=2,
        tokens=TokenUsage(),
        summary=StageSummary(accepted=False),
    )
    trace.evaluator_rejected(2, "Required: troponin at T+0")
    cycle = trace.snapshot().cycles[0]
    assert cycle.evaluator is not None
    assert cycle.evaluator.status == "rejected"
    assert cycle.evaluator.summary.required_gap == "Required: troponin at T+0"


def test_no_progress_sets_halt_reason():
    trace = make_trace()
    trace.cycle_start(3, 3)
    trace.no_progress_halt(3, "Required: troponin at T+0")
    snapshot = trace.snapshot()
    assert snapshot.halt_reason == "no_progress"
    assert snapshot.cycles[0].decision == "no_progress_halt"


def test_verdict_reached_updates_halt_reason_and_metrics():
    trace = make_trace()
    trace.cycle_start(1, 3)
    trace.agent_complete(
        "Resolver",
        cycle=1,
        tokens=TokenUsage(input_tokens=10, output_tokens=5),
        summary=StageSummary(verdict=Verdict.survives, surviving_attacks=0, defeated_attacks=1),
    )
    trace.verdict_reached(1, "survives")
    snapshot = trace.snapshot()
    assert snapshot.halt_reason == "survives"
    assert snapshot.cycles[0].decision == "verdict:survives"
    assert snapshot.metrics.stage_calls == 1
    assert snapshot.metrics.cycles_used == 1
