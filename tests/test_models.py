"""
test_models.py — Field isolation, view functions, model arithmetic.

The critical invariant tested here: each view function exposes ONLY the
fields that agent is permitted to see. Isolation is structural — the
field simply does not exist in the projected model.
"""
from __future__ import annotations
import pytest
from gauntlet.models import (
    ArgumentUnit, BipolarComparison, DialogueType, Ground, TokenUsage,
    constructor_view, classifier_view, auditor_view, evaluator_view, resolver_view,
    EvaluatorInput, ResolverInput,
)


def make_unit(**kw) -> ArgumentUnit:
    defaults = dict(
        dialogue_type=DialogueType.deliberation,
        domain_standard="senior engineer, distributed systems",
        claim="decompose the monolith",
    )
    return ArgumentUnit(**{**defaults, **kw})


# ── Evaluator is the only agent that sees domain_standard ─────────────────────

def test_evaluator_sees_domain_standard(unit_with_grounds):
    v = evaluator_view(unit_with_grounds)
    assert isinstance(v, EvaluatorInput)
    assert v.domain_standard == unit_with_grounds.domain_standard


def test_constructor_cannot_see_domain_standard(unit_with_grounds):
    v = constructor_view(unit_with_grounds)
    assert not hasattr(v, "domain_standard")


def test_classifier_cannot_see_domain_standard(unit_with_grounds):
    v = classifier_view(unit_with_grounds)
    assert not hasattr(v, "domain_standard")


def test_auditor_cannot_see_domain_standard(unit_with_grounds):
    v = auditor_view(unit_with_grounds)
    assert not hasattr(v, "domain_standard")


def test_resolver_cannot_see_domain_standard(unit_with_grounds):
    v = resolver_view(unit_with_grounds)
    assert not hasattr(v, "domain_standard")


# ── No agent can see verdict (prevents circular reasoning) ────────────────────

def test_constructor_cannot_see_verdict(unit_with_grounds):
    assert not hasattr(constructor_view(unit_with_grounds), "verdict")


def test_classifier_cannot_see_verdict(unit_with_grounds):
    assert not hasattr(classifier_view(unit_with_grounds), "verdict")


def test_evaluator_cannot_see_verdict(unit_with_grounds):
    assert not hasattr(evaluator_view(unit_with_grounds), "verdict")


# ── Evaluator cannot see open_attacks (independence requirement) ──────────────

def test_evaluator_cannot_see_open_attacks(unit_with_grounds):
    assert not hasattr(evaluator_view(unit_with_grounds), "open_attacks")


def test_evaluator_cannot_see_rebuttal_log(unit_with_grounds):
    assert not hasattr(evaluator_view(unit_with_grounds), "rebuttal_log")


# ── Classifier cannot see rebuttal_log ───────────────────────────────────────

def test_classifier_cannot_see_rebuttal_log(unit_with_grounds):
    assert not hasattr(classifier_view(unit_with_grounds), "rebuttal_log")


# ── Resolver receives cycle and termination_limit ─────────────────────────────

def test_resolver_receives_cycle_info(unit_with_grounds):
    unit_with_grounds.cycle = 2
    v = resolver_view(unit_with_grounds)
    assert isinstance(v, ResolverInput)
    assert v.cycle == 2
    assert v.termination_limit == unit_with_grounds.termination_limit


def test_resolver_cannot_see_domain_standard(unit_with_grounds):
    assert not hasattr(resolver_view(unit_with_grounds), "domain_standard")


# ── Constructor view: grounds sentinel ───────────────────────────────────────

def test_constructor_view_grounds_none_when_empty():
    """Empty grounds → None, signalling Constructor to retrieve from scratch."""
    unit = make_unit()
    v = constructor_view(unit)
    assert v.grounds is None


def test_constructor_view_grounds_present_when_set(unit_with_grounds):
    v = constructor_view(unit_with_grounds)
    assert v.grounds is not None
    assert len(v.grounds) == 3


def test_constructor_view_carries_acceptance_gap():
    unit = make_unit()
    unit.acceptance_gap = "Required: troponin at T+0"
    v = constructor_view(unit)
    assert v.acceptance_gap == "Required: troponin at T+0"


# ── TokenUsage arithmetic ─────────────────────────────────────────────────────

def test_token_usage_addition():
    a = TokenUsage(input_tokens=100, output_tokens=50)
    b = TokenUsage(input_tokens=200, output_tokens=75)
    c = a + b
    assert c.input_tokens == 300
    assert c.output_tokens == 125
    assert c.total() == 425


def test_token_usage_identity():
    z = TokenUsage()
    a = TokenUsage(input_tokens=10, output_tokens=5)
    assert (z + a).total() == 15
    assert (a + z).total() == 15


# ── BipolarComparison enum (typo fixed from BipolarlComparison) ───────────────

def test_bipolar_comparison_values():
    assert BipolarComparison.definite_conclusion.value     == "definite_conclusion"
    assert BipolarComparison.wrong_starting_position.value == "wrong_starting_position"
    assert BipolarComparison.equipoise.value               == "equipoise"
    assert BipolarComparison.insufficient_evidence.value   == "insufficient_evidence"


def test_bipolar_comparison_no_typo():
    """Guard against the BipolarlComparison typo regressing."""
    import gauntlet.models as m
    assert hasattr(m, "BipolarComparison")
    assert not hasattr(m, "BipolarlComparison")


# ── ArgumentUnit gets unique IDs ──────────────────────────────────────────────

def test_argument_unit_unique_ids():
    u1 = make_unit()
    u2 = make_unit()
    assert u1.id != u2.id
    assert len(u1.id) == 36  # UUID4
