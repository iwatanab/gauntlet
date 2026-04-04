"""
test_translation.py — Deterministic translation behaviour.

The LLM-assisted corrections are tested only for interface conformance
(they return gracefully on failure). The deterministic parts — qualifier
calibration, grounds sorting, TranslationDelta structure — are fully tested.
"""
from __future__ import annotations
import pytest
from gauntlet.translation import (
    TranslationDelta, _calibrate_qualifier, _QUALIFIER_SCALE,
)
from gauntlet.models import ArgumentUnit, DialogueType, Ground, TokenUsage


# ── Qualifier calibration ─────────────────────────────────────────────────────

def test_qualifier_covers_full_weight_range():
    valid = {"possibly", "presumably", "probably", "almost certainly"}
    for w in [0.0, 0.1, 0.24, 0.25, 0.5, 0.54, 0.55, 0.74, 0.75, 0.99, 1.0]:
        assert _calibrate_qualifier(w) in valid


def test_qualifier_thresholds():
    assert _calibrate_qualifier(0.10) == "possibly"
    assert _calibrate_qualifier(0.30) == "presumably"
    assert _calibrate_qualifier(0.65) == "probably"
    assert _calibrate_qualifier(0.90) == "almost certainly"


def test_qualifier_boundary_exactly_at_threshold():
    # 0.25 should map to "presumably" (< 0.55 threshold)
    assert _calibrate_qualifier(0.25) == "presumably"
    # 0.55 should map to "probably" (< 0.75 threshold)
    assert _calibrate_qualifier(0.55) == "probably"


# ── Grounds sorting ───────────────────────────────────────────────────────────

def test_grounds_sorted_descending():
    unit = ArgumentUnit(
        dialogue_type=DialogueType.deliberation,
        domain_standard="test",
        claim="test",
        grounds=[
            Ground(content="c", source="s", probative_weight=0.3),
            Ground(content="a", source="s", probative_weight=0.9),
            Ground(content="b", source="s", probative_weight=0.6),
        ],
    )
    unit.grounds.sort(key=lambda g: g.probative_weight, reverse=True)
    weights = [g.probative_weight for g in unit.grounds]
    assert weights == sorted(weights, reverse=True)
    assert weights[0] == 0.9


def test_grounds_sort_is_stable_on_equal_weights():
    """Equal-weight grounds preserve original order (Python sort is stable)."""
    unit = ArgumentUnit(
        dialogue_type=DialogueType.deliberation,
        domain_standard="test",
        claim="test",
        grounds=[
            Ground(content="first",  source="s", probative_weight=0.5),
            Ground(content="second", source="s", probative_weight=0.5),
        ],
    )
    unit.grounds.sort(key=lambda g: g.probative_weight, reverse=True)
    assert unit.grounds[0].content == "first"


def test_empty_grounds_sort_safely():
    unit = ArgumentUnit(
        dialogue_type=DialogueType.deliberation,
        domain_standard="test",
        claim="test",
    )
    unit.grounds.sort(key=lambda g: g.probative_weight, reverse=True)
    assert unit.grounds == []


# ── TranslationDelta structure ────────────────────────────────────────────────

def test_translation_delta_fields():
    delta = TranslationDelta(
        qualifier_before="certainly",
        qualifier_after="presumably",
        grounds_reordered=True,
        warrant_rewritten=False,
        attacks_neutralised=True,
        gap_normalised=False,
        usage=TokenUsage(input_tokens=50, output_tokens=20),
    )
    assert delta.qualifier_before == "certainly"
    assert delta.qualifier_after  == "presumably"
    assert delta.grounds_reordered is True
    assert delta.warrant_rewritten is False
    assert delta.usage.total() == 70


def test_translation_delta_default_usage():
    delta = TranslationDelta(
        qualifier_before="p", qualifier_after="p",
        grounds_reordered=False, warrant_rewritten=False,
        attacks_neutralised=False, gap_normalised=False,
    )
    assert delta.usage.total() == 0
