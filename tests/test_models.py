"""
test_models.py - Field isolation, stage views, and model helpers.

The critical invariant tested here is structural isolation: a stage cannot
see fields that are not present in its input model.
"""
from __future__ import annotations

from gauntlet.models import (
    BipolarComparison,
    CritiqueInput,
    EvaluateRequest,
    EvaluatorInput,
    Ground,
    PositionState,
    ResolverInput,
    TokenUsage,
    constructor_view,
    critique_view,
    evaluator_view,
    resolver_view,
)


def make_state(**kw) -> PositionState:
    defaults = dict(
        claim="decompose the monolith",
        domain_standard="senior engineer, distributed systems",
        grounds=[],
        warrant=None,
        backing=None,
        qualifier="presumably",
    )
    return PositionState(**{**defaults, **kw})


def test_evaluate_request_is_single_string():
    req = EvaluateRequest.model_validate("Use feature flags for this rollout.")
    assert req.input == "Use feature flags for this rollout."


def test_evaluator_sees_domain_standard(state_with_grounds):
    view = evaluator_view(state_with_grounds)
    assert isinstance(view, EvaluatorInput)
    assert view.domain_standard == state_with_grounds.domain_standard


def test_constructor_cannot_see_domain_standard(state_with_grounds):
    assert not hasattr(constructor_view(state_with_grounds), "domain_standard")


def test_critique_cannot_see_domain_standard(state_with_grounds):
    view = critique_view(state_with_grounds)
    assert isinstance(view, CritiqueInput)
    assert not hasattr(view, "domain_standard")


def test_evaluator_cannot_see_open_attacks(state_with_grounds):
    state_with_grounds.open_attacks = []
    assert not hasattr(evaluator_view(state_with_grounds), "open_attacks")


def test_resolver_cannot_see_domain_standard(state_with_grounds):
    assert not hasattr(resolver_view(state_with_grounds), "domain_standard")


def test_resolver_receives_final_cycle_and_required_gap(state_with_grounds):
    state_with_grounds.final_cycle = True
    state_with_grounds.required_gap = "Required: evidence X"
    view = resolver_view(state_with_grounds)
    assert isinstance(view, ResolverInput)
    assert view.final_cycle is True
    assert view.required_gap == "Required: evidence X"


def test_constructor_cannot_see_rebuttal_history(state_with_grounds):
    assert not hasattr(constructor_view(state_with_grounds), "rebuttal_log")


def test_constructor_view_grounds_none_when_empty():
    state = make_state()
    view = constructor_view(state)
    assert view.grounds is None


def test_constructor_view_carries_required_gap():
    state = make_state()
    state.required_gap = "Required: troponin at T+0"
    view = constructor_view(state)
    assert view.required_gap == "Required: troponin at T+0"


def test_critique_view_preserves_canonical_warrant():
    state = make_state(
        warrant="It is assumed that: feature flags make the rollout reversible.",
        grounds=[Ground(content="evidence", source="ops")],
    )
    view = critique_view(state)
    assert view.warrant == "It is assumed that: feature flags make the rollout reversible."


def test_token_usage_addition():
    a = TokenUsage(input_tokens=100, output_tokens=50)
    b = TokenUsage(input_tokens=200, output_tokens=75)
    c = a + b
    assert c.input_tokens == 300
    assert c.output_tokens == 125
    assert c.total() == 425


def test_bipolar_comparison_values():
    assert BipolarComparison.definite_conclusion.value == "definite_conclusion"
    assert BipolarComparison.wrong_starting_position.value == "wrong_starting_position"
    assert BipolarComparison.equipoise.value == "equipoise"
    assert BipolarComparison.insufficient_evidence.value == "insufficient_evidence"
