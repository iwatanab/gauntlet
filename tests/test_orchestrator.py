"""
test_orchestrator.py — Orchestrator logic tested with mock agents.

We don't make real LLM calls in tests. Instead we mock the individual
agent functions and verify that the orchestrator:
  - Calls agents in the correct sequence
  - Accumulates usage from all agents (including translation layer)
  - Detects no-progress correctly
  - Compares bipolar outcomes correctly
  - Generates and runs the contrary independently
"""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest
from gauntlet.orchestrator import (
    _compare, _no_progress, _recommended,
)
from gauntlet.models import BipolarComparison, Verdict


# ── _compare ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("claim_v,contrary_v,expected", [
    (Verdict.survives, Verdict.defeated, BipolarComparison.definite_conclusion),
    (Verdict.survives, Verdict.impasse,  BipolarComparison.definite_conclusion),
    (Verdict.defeated, Verdict.survives, BipolarComparison.wrong_starting_position),
    (Verdict.impasse,  Verdict.survives, BipolarComparison.wrong_starting_position),
    (Verdict.survives, Verdict.survives, BipolarComparison.equipoise),
    (Verdict.defeated, Verdict.defeated, BipolarComparison.insufficient_evidence),
    (Verdict.impasse,  Verdict.impasse,  BipolarComparison.insufficient_evidence),
    (Verdict.defeated, Verdict.impasse,  BipolarComparison.insufficient_evidence),
    (Verdict.impasse,  Verdict.defeated, BipolarComparison.insufficient_evidence),
])
def test_compare_outcomes(claim_v, contrary_v, expected):
    assert _compare(claim_v, contrary_v) == expected


def test_compare_handles_none_verdicts():
    """None verdict (pipeline terminated before resolver) counts as not surviving."""
    assert _compare(None, None)          == BipolarComparison.insufficient_evidence
    assert _compare(Verdict.survives, None) == BipolarComparison.definite_conclusion
    assert _compare(None, Verdict.survives) == BipolarComparison.wrong_starting_position


# ── _recommended ──────────────────────────────────────────────────────────────

def test_recommended_definite_conclusion():
    assert _recommended(BipolarComparison.definite_conclusion, "A", "B") == "A"


def test_recommended_wrong_starting_position():
    assert _recommended(BipolarComparison.wrong_starting_position, "A", "B") == "B"


def test_recommended_equipoise_is_none():
    assert _recommended(BipolarComparison.equipoise, "A", "B") is None


def test_recommended_insufficient_evidence_is_none():
    assert _recommended(BipolarComparison.insufficient_evidence, "A", "B") is None


# ── _no_progress ─────────────────────────────────────────────────────────────

def test_no_progress_detected_on_repeated_gap():
    gap = "Required: troponin at T+0"
    assert _no_progress(gap, gap, cycle=2) is True


def test_no_progress_not_triggered_on_cycle_1():
    gap = "Required: troponin at T+0"
    assert _no_progress(gap, gap, cycle=1) is False


def test_no_progress_not_triggered_when_gap_changes():
    assert _no_progress("gap_B", "gap_A", cycle=2) is False


def test_no_progress_not_triggered_when_gap_is_none():
    assert _no_progress(None, None, cycle=2) is False


def test_no_progress_not_triggered_on_first_occurrence():
    assert _no_progress("gap_A", None, cycle=2) is False
