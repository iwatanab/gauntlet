"""
test_trace.py — PipelineTrace event accumulation and structure.

The trace is a first-class output. These tests verify that events are
emitted with correct kind, position, cycle, and detail keys — and that
the snapshot is an immutable copy of the accumulated state.
"""
from __future__ import annotations
import pytest
from gauntlet.trace import EventKind, PipelineTrace
from gauntlet.models import TokenUsage


def make_trace(pos="claim") -> PipelineTrace:
    return PipelineTrace(pos)


def test_pipeline_start_captured():
    t = make_trace()
    t.pipeline_start("test claim", "test domain", 3)
    events = t.snapshot()
    assert len(events) == 1
    e = events[0]
    assert e.kind     == EventKind.pipeline_start
    assert e.position == "claim"
    assert e.detail["claim"] == "test claim"
    assert e.detail["termination_limit"] == 3


def test_cycle_start_captured():
    t = make_trace()
    t.cycle_start(2, 3)
    e = t.snapshot()[0]
    assert e.kind            == EventKind.cycle_start
    assert e.cycle           == 2
    assert e.detail["total_cycles"] == 3


def test_agent_start_and_complete():
    t = make_trace("contrary")
    t.agent_start("Constructor", cycle=1)
    t.agent_complete("Constructor", cycle=1,
                     tokens=TokenUsage(input_tokens=100, output_tokens=40),
                     grounds_count=3, qualifier="presumably")

    events = t.snapshot()
    assert events[0].kind == EventKind.agent_start
    assert events[1].kind == EventKind.agent_complete
    assert events[1].tokens.total() == 140
    assert events[1].detail["grounds_count"] == 3
    assert events[1].detail["agent"] == "Constructor"
    assert events[1].position == "contrary"


def test_tool_called_captures_result_preview():
    t = make_trace()
    t.tool_called("Constructor", "web_search", "NICE NG185", "Result: " + "x" * 400, cycle=1)
    e = t.snapshot()[0]
    assert e.kind == EventKind.tool_called
    assert e.detail["tool"] == "web_search"
    assert e.detail["query"] == "NICE NG185"
    assert e.detail["result_chars"] == 408   # "Result: " + 400 chars
    assert len(e.detail["result_preview"]) <= 300


def test_translation_applied_records_delta():
    t = make_trace()
    t.translation_applied(
        cycle=1,
        qualifier_before="certainly",
        qualifier_after="presumably",
        grounds_reordered=True,
        warrant_rewritten=True,
        attacks_neutralised=False,
        gap_normalised=False,
        tokens=TokenUsage(input_tokens=50, output_tokens=20),
    )
    e = t.snapshot()[0]
    assert e.kind == EventKind.translation_applied
    assert e.detail["qualifier_before"] == "certainly"
    assert e.detail["qualifier_after"]  == "presumably"
    assert e.detail["warrant_rewritten"] is True
    assert e.tokens.total() == 70


def test_auditor_blocked_captures_gap():
    t = make_trace()
    t.auditor_blocked(1, "Rule 2 — Burden", "opening", "Required: cost on table")
    e = t.snapshot()[0]
    assert e.kind          == EventKind.auditor_blocked
    assert e.detail["gap"] == "Required: cost on table"
    assert e.detail["rule"] == "Rule 2 — Burden"


def test_evaluator_rejected_captures_gap():
    t = make_trace()
    t.evaluator_rejected(2, "Required: troponin at T+0")
    e = t.snapshot()[0]
    assert e.kind          == EventKind.evaluator_rejected
    assert e.detail["gap"] == "Required: troponin at T+0"


def test_no_progress_halt():
    t = make_trace()
    t.no_progress_halt(3, "Required: troponin at T+0")
    e = t.snapshot()[0]
    assert e.kind                    == EventKind.no_progress_halt
    assert e.detail["repeated_gap"]  == "Required: troponin at T+0"


def test_verdict_reached():
    t = make_trace()
    t.verdict_reached(2, "survives")
    e = t.snapshot()[0]
    assert e.kind              == EventKind.verdict_reached
    assert e.detail["verdict"] == "survives"
    assert e.detail["cycles_used"] == 2


def test_snapshot_is_independent_copy():
    """Mutations to the trace after snapshot should not affect earlier snapshot."""
    t = make_trace()
    t.pipeline_start("c", "d", 3)
    snap1 = t.snapshot()
    t.verdict_reached(1, "survives")
    snap2 = t.snapshot()
    assert len(snap1) == 1
    assert len(snap2) == 2


def test_position_is_propagated():
    for pos in ("claim", "contrary", "system"):
        t = PipelineTrace(pos)
        t.verdict_reached(1, "survives")
        assert t.snapshot()[0].position == pos


def test_all_events_have_timestamp():
    t = make_trace()
    t.pipeline_start("c", "d", 3)
    t.cycle_start(1, 3)
    t.agent_start("Constructor", 1)
    t.verdict_reached(1, "survives")
    for e in t.snapshot():
        assert e.ts and "T" in e.ts  # ISO 8601 format


def test_full_single_cycle_trace_sequence():
    """Walk through a complete happy-path cycle and verify event order."""
    t = make_trace()
    u = TokenUsage(input_tokens=100, output_tokens=50)
    t.pipeline_start("claim", "domain", 3)
    t.cycle_start(1, 3)
    t.agent_start("Constructor", 1)
    t.agent_complete("Constructor", 1, u, grounds_count=3, qualifier="presumably")
    t.translation_applied(1, "presumably", "presumably", False, False, False, False, TokenUsage())
    t.agent_start("Classifier", 1)
    t.agent_complete("Classifier", 1, u, scheme="argument_from_sign",
                     open_attacks_count=2, answered_cqs=1, unanswered_cqs=1)
    t.agent_start("Auditor", 1)
    t.agent_complete("Auditor", 1, u, blocked=False, violations_count=0)
    t.agent_start("Evaluator", 1)
    t.agent_complete("Evaluator", 1, u, accepted=True, gap_preview=None)
    t.agent_start("Resolver", 1)
    t.agent_complete("Resolver", 1, u, verdict="survives",
                     surviving_attacks=0, defeated_attacks=2)
    t.verdict_reached(1, "survives")

    events = t.snapshot()
    kinds = [e.kind for e in events]
    # Verify the expected sequence
    assert EventKind.pipeline_start    in kinds
    assert EventKind.cycle_start       in kinds
    assert EventKind.agent_start       in kinds
    assert EventKind.agent_complete    in kinds
    assert EventKind.verdict_reached   in kinds
    # pipeline_start is first
    assert events[0].kind == EventKind.pipeline_start
    # verdict_reached is last
    assert events[-1].kind == EventKind.verdict_reached
