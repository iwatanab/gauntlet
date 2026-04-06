"""
test_orchestrator.py - Orchestrator logic with mocked stages.

These tests focus on the reduced runtime shape:
Constructor -> Critique Bundle -> Evaluator -> Resolver
with canonical required_gap flow and bipolar independence.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from gauntlet.config import AgentConfig, GauntletConfig
from gauntlet.models import (
    AttackGraph,
    BipolarComparison,
    ClaimEvaluation,
    CriticalQuestion,
    CritiqueOutput,
    EvaluationIssues,
    FinalArgument,
    PositionTrace,
    ResolverOutput,
    RuleViolation,
    StageAudit,
    TokenUsage,
    Verdict,
    Severity,
)
from gauntlet.orchestrator import (
    _compare,
    _no_progress,
    _recommended,
    run_claim_pipeline,
    run_pipeline,
    PreparedEvaluationInput,
)
from gauntlet.models import EvaluateRequest, ConstructorOutput, EvaluatorOutput


def _cfg() -> GauntletConfig:
    return GauntletConfig(
        primary=AgentConfig(model="primary"),
        preflight=AgentConfig(model="preflight"),
        openrouter_api_key="k",
        openrouter_base_url="u",
    )


def _claim_eval(claim: str, verdict: Verdict) -> ClaimEvaluation:
    return ClaimEvaluation(
        claim=claim,
        verdict=verdict,
        final_argument=FinalArgument(grounds=[], warrant=None, backing=None, qualifier="presumably"),
        issues=EvaluationIssues(),
        required_gap=None,
        rebuttal_log=[],
        cycles_run=1,
        no_progress=False,
        trace=PositionTrace(position="claim"),
        usage=TokenUsage(input_tokens=1, output_tokens=1),
    )


@pytest.mark.parametrize("claim_v,contrary_v,expected", [
    (Verdict.survives, Verdict.defeated, BipolarComparison.definite_conclusion),
    (Verdict.survives, Verdict.impasse, BipolarComparison.definite_conclusion),
    (Verdict.defeated, Verdict.survives, BipolarComparison.wrong_starting_position),
    (Verdict.impasse, Verdict.survives, BipolarComparison.wrong_starting_position),
    (Verdict.survives, Verdict.survives, BipolarComparison.equipoise),
    (Verdict.defeated, Verdict.defeated, BipolarComparison.insufficient_evidence),
    (Verdict.impasse, Verdict.impasse, BipolarComparison.insufficient_evidence),
])
def test_compare_outcomes(claim_v, contrary_v, expected):
    assert _compare(claim_v, contrary_v) == expected


def test_recommended_helpers():
    assert _recommended(BipolarComparison.definite_conclusion, "A", "B") == "A"
    assert _recommended(BipolarComparison.wrong_starting_position, "A", "B") == "B"
    assert _recommended(BipolarComparison.equipoise, "A", "B") is None


def test_no_progress_detected_on_repeated_gap():
    assert _no_progress("Required: troponin at T+0", "Required: troponin at T+0", cycle=2) is True
    assert _no_progress("Required: troponin at T+0", "troponin at T+0", cycle=2) is True


@pytest.mark.asyncio
async def test_run_claim_pipeline_loops_on_critique_required_gap():
    constructor_calls = []

    async def constructor_side_effect(inp, *_args, **_kwargs):
        constructor_calls.append(inp)
        return ConstructorOutput(
            grounds=[],
            warrant="It is assumed that: the evidence supports the claim.",
            backing=None,
            qualifier="presumably",
        ), TokenUsage(input_tokens=10, output_tokens=5)

    critique_outputs = [
        CritiqueOutput(
            scheme="argument_from_sign",
            critical_questions=[CriticalQuestion(question="CQ1", answered=False, answer=None)],
            open_attacks=[],
            burden_bearer="action-recommender",
            stage_audit=StageAudit(confrontation="ok", opening="blocked", argumentation="ok", blocked=True),
            rule_violations=[RuleViolation(
                rule="Rule 2 - Burden of Proof",
                stage="opening",
                severity=Severity.blocking,
                description="Cost of the alternative action is not placed on the table.",
            )],
            required_gap="Required: troponin result at T+0",
        ),
        CritiqueOutput(
            scheme="argument_from_sign",
            critical_questions=[CriticalQuestion(question="CQ1", answered=True, answer="yes")],
            open_attacks=[],
            burden_bearer="action-recommender",
            stage_audit=StageAudit(confrontation="ok", opening="ok", argumentation="ok", blocked=False),
            rule_violations=[],
            required_gap=None,
        ),
    ]

    with patch("gauntlet.orchestrator.run_constructor", side_effect=constructor_side_effect):
        with patch("gauntlet.orchestrator.run_critique_bundle", side_effect=[
            (critique_outputs[0], TokenUsage(input_tokens=8, output_tokens=4)),
            (critique_outputs[1], TokenUsage(input_tokens=8, output_tokens=4)),
        ]):
            with patch("gauntlet.orchestrator.run_evaluator", side_effect=[
                (EvaluatorOutput(acceptance=True, required_gap=None), TokenUsage(input_tokens=7, output_tokens=3))
            ]):
                with patch("gauntlet.orchestrator.run_resolver", side_effect=[
                    (ResolverOutput(
                        attack_graph=AttackGraph(nodes=[], edges=[]),
                        extension="preferred",
                        verdict=Verdict.survives,
                        rebuttal_log=[],
                    ), TokenUsage(input_tokens=6, output_tokens=2))
                ]):
                    result = await run_claim_pipeline(
                        claim="do the thing",
                        domain_standard="balance of probabilities",
                        qualifier="presumably",
                        config=_cfg(),
                        client=object(),
                        position="claim",
                        preflight_summary={"claim": "do the thing"},
                        preflight_usage=TokenUsage(),
                    )

    assert result.verdict == Verdict.survives
    assert result.cycles_run == 2
    assert constructor_calls[0].required_gap is None
    assert constructor_calls[1].required_gap == "Required: troponin result at T+0"


@pytest.mark.asyncio
async def test_run_claim_pipeline_halts_on_repeated_required_gap():
    with patch("gauntlet.orchestrator.run_constructor", side_effect=[
        (ConstructorOutput(grounds=[], warrant="It is assumed that: x", backing=None, qualifier="presumably"), TokenUsage()),
        (ConstructorOutput(grounds=[], warrant="It is assumed that: x", backing=None, qualifier="presumably"), TokenUsage()),
    ]):
        critique_result = CritiqueOutput(
            scheme="argument_from_sign",
            critical_questions=[],
            open_attacks=[],
            burden_bearer="action-recommender",
            stage_audit=StageAudit(confrontation="ok", opening="blocked", argumentation="ok", blocked=True),
            rule_violations=[RuleViolation(
                rule="Rule 2 - Burden of Proof",
                stage="opening",
                severity=Severity.blocking,
                description="Cost remains unstated.",
            )],
            required_gap="Required: cost comparison for the alternative action",
        )
        with patch("gauntlet.orchestrator.run_critique_bundle", side_effect=[
            (critique_result, TokenUsage()),
            (critique_result, TokenUsage()),
        ]):
            result = await run_claim_pipeline(
                claim="do the thing",
                domain_standard="balance of probabilities",
                qualifier="presumably",
                config=_cfg(),
                client=object(),
                position="claim",
                preflight_summary={"claim": "do the thing"},
                preflight_usage=TokenUsage(),
            )

    assert result.verdict == Verdict.impasse
    assert result.no_progress is True
    assert result.required_gap == "Required: cost comparison for the alternative action"
    assert result.cycles_run == 2


@pytest.mark.asyncio
async def test_run_pipeline_keeps_contrary_construction_independent():
    prepared = PreparedEvaluationInput(
        claim="do the thing",
        grounds=[],
        warrant="It is assumed that: x",
        backing=None,
        qualifier="presumably",
        domain_standard="balance of probabilities",
        usage=TokenUsage(),
    )
    with patch("gauntlet.orchestrator._generate_contrary", new_callable=AsyncMock) as contrary:
        contrary.return_value = ("do not the thing", TokenUsage())
        with patch("gauntlet.orchestrator.run_claim_pipeline", new_callable=AsyncMock) as pipeline:
            pipeline.side_effect = [
                _claim_eval("do the thing", Verdict.survives),
                _claim_eval("do not the thing", Verdict.defeated),
            ]
            result = await run_pipeline(EvaluateRequest.model_validate("do the thing"), _cfg(), object(), prepared=prepared)

    assert result.comparison == BipolarComparison.definite_conclusion
    first_call = pipeline.await_args_list[0].kwargs
    second_call = pipeline.await_args_list[1].kwargs
    assert first_call["initial_warrant"] == "It is assumed that: x"
    assert second_call["initial_grounds"] is None
    assert second_call["initial_warrant"] is None
    assert second_call["initial_backing"] is None
