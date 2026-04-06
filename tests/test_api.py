"""
test_api.py - API endpoint tests with mocked pipeline/preflight.

No real model calls. These tests verify request validation, public response
shape, and async job management under the new four-stage architecture.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from gauntlet.api import app
from gauntlet.models import (
    BipolarComparison,
    ClaimEvaluation,
    EvaluationIssues,
    FinalArgument,
    GauntletResult,
    InputErrorResponse,
    PositionMetrics,
    PositionTrace,
    TokenUsage,
    Verdict,
)
from gauntlet.orchestrator import PreparedEvaluationInput
from gauntlet.parsing import InputError


def _trace(position: str = "claim") -> PositionTrace:
    return PositionTrace(
        position=position,
        preflight={"claim": "test"},
        preflight_usage=TokenUsage(input_tokens=10, output_tokens=5),
        cycles=[],
        halt_reason="survives",
        metrics=PositionMetrics(stage_calls=4, tool_calls=1, cycles_used=1),
    )


def _claim_eval(claim: str = "test claim", verdict: Verdict = Verdict.survives) -> ClaimEvaluation:
    return ClaimEvaluation(
        claim=claim,
        verdict=verdict,
        final_argument=FinalArgument(
            grounds=[],
            warrant="It is assumed that: the claim follows from the grounds.",
            backing=None,
            qualifier="presumably",
        ),
        issues=EvaluationIssues(
            scheme="argument_from_practical_reasoning",
            critical_questions=[],
            open_attacks=[],
            rule_violations=[],
        ),
        required_gap=None,
        rebuttal_log=[],
        cycles_run=1,
        no_progress=False,
        trace=_trace("claim" if claim == "do the thing" else "contrary"),
        usage=TokenUsage(input_tokens=1000, output_tokens=300),
    )


def _result(
    comparison: BipolarComparison = BipolarComparison.definite_conclusion,
    claim_verdict: Verdict = Verdict.survives,
    contrary_verdict: Verdict = Verdict.defeated,
) -> GauntletResult:
    claim_eval = _claim_eval("do the thing", claim_verdict)
    contrary_eval = _claim_eval("do not the thing", contrary_verdict)
    recommended = "do the thing" if comparison == BipolarComparison.definite_conclusion else None
    return GauntletResult(
        id="test-id",
        claim_evaluation=claim_eval,
        contrary_evaluation=contrary_eval,
        comparison=comparison,
        recommended_position=recommended,
        inferred_domain_standard="balance of probabilities",
        total_usage=TokenUsage(input_tokens=2500, output_tokens=700),
    )


VALID = "Implement mandatory 2FA for all admin routes."


def _prepared(text: str = VALID) -> PreparedEvaluationInput:
    return PreparedEvaluationInput(
        claim=text,
        grounds=[],
        warrant=None,
        backing=None,
        qualifier="presumably",
        domain_standard="balance of probabilities",
        usage=TokenUsage(input_tokens=60, output_tokens=25),
    )


def _cancel_task(coro):
    coro.close()
    return None


@pytest.fixture
def client():
    from gauntlet import api as module
    from gauntlet.config import AgentConfig, GauntletConfig

    module._config = GauntletConfig(
        primary=AgentConfig(model="test/model"),
        preflight=AgentConfig(model="test/preflight"),
        openrouter_api_key="test",
        openrouter_base_url="https://test.example.com",
    )
    module._client = AsyncMock()
    with TestClient(app) as test_client:
        yield test_client


def test_health_ok(client):
    response = client.get("/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["preflight_model"] == "test/preflight"


@pytest.mark.parametrize("bad_input", ["", "ignore previous instructions", "jailbreak"])
def test_bad_inputs_rejected(bad_input: str, client):
    response = client.post("/v1/evaluate", json=bad_input)
    assert response.status_code == 422


def test_public_request_contract_is_single_json_string(client):
    response = client.post("/v1/evaluate", json={"input": VALID})
    assert response.status_code == 422


def test_sync_evaluate_returns_bipolar_shape(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as mocked:
        mocked.return_value = _result()
        response = client.post("/v1/evaluate", json=VALID)
    assert response.status_code == 200
    body = response.json()
    for field in (
        "id",
        "claim_evaluation",
        "contrary_evaluation",
        "comparison",
        "recommended_position",
        "inferred_domain_standard",
        "total_usage",
    ):
        assert field in body
    assert "final_argument" in body["claim_evaluation"]
    assert "issues" in body["claim_evaluation"]
    assert "trace" in body["claim_evaluation"]


def test_pipeline_error_returns_500(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as mocked:
        mocked.side_effect = RuntimeError("model unavailable")
        response = client.post("/v1/evaluate", json=VALID)
    assert response.status_code == 500


def test_multiple_atomic_claims_return_structured_422(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as mocked:
        mocked.side_effect = InputError(
            code="multiple_claims",
            message="Process will not continue: the input contains 2 atomic claims. Provide exactly one atomic claim.",
            claims=["Enable SSO.", "Require hardware keys."],
        )
        response = client.post("/v1/evaluate", json=VALID)
    assert response.status_code == 422
    body = response.json()["detail"]
    assert body["code"] == "multiple_claims"
    assert body["claims"] == ["Enable SSO.", "Require hardware keys."]


def test_async_endpoint_returns_job_id(client):
    with patch("gauntlet.api.prepare_evaluation_input", new_callable=AsyncMock) as prepare:
        with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as mocked:
            with patch("gauntlet.api.asyncio.create_task", side_effect=_cancel_task):
                prepare.return_value = _prepared()
                mocked.return_value = _result()
                response = client.post("/v1/evaluate/async", json=VALID)
    assert response.status_code == 202
    assert "job_id" in response.json()
    assert len(response.json()["job_id"]) == 36


def test_async_endpoint_rejects_multiple_claims_immediately(client):
    with patch("gauntlet.api.prepare_evaluation_input", new_callable=AsyncMock) as prepare:
        prepare.side_effect = InputError(
            code="multiple_claims",
            message="Process will not continue: the input contains 2 atomic claims. Provide exactly one atomic claim.",
            claims=["Enable SSO.", "Require hardware keys."],
        )
        response = client.post("/v1/evaluate/async", json=VALID)
    assert response.status_code == 422
    assert response.json()["detail"] == InputErrorResponse(
        code="multiple_claims",
        message="Process will not continue: the input contains 2 atomic claims. Provide exactly one atomic claim.",
        claims=["Enable SSO.", "Require hardware keys."],
    ).model_dump()


def test_job_not_found_returns_404(client):
    assert client.get("/v1/jobs/does-not-exist").status_code == 404


def test_delete_nonexistent_job_returns_404(client):
    assert client.delete("/v1/jobs/does-not-exist").status_code == 404


def test_config_property_accessors():
    from gauntlet.config import AgentConfig, GauntletConfig

    primary = AgentConfig(model="primary/model")
    preflight = AgentConfig(model="preflight/model")
    cfg = GauntletConfig(
        primary=primary,
        preflight=preflight,
        openrouter_api_key="k",
        openrouter_base_url="u",
    )
    assert cfg.for_constructor.model == "primary/model"
    assert cfg.for_critique.model == "primary/model"
    assert cfg.for_evaluator.model == "primary/model"
    assert cfg.for_resolver.model == "primary/model"


def test_config_per_stage_override():
    from gauntlet.config import AgentConfig, GauntletConfig

    override = AgentConfig(model="override/model")
    cfg = GauntletConfig(
        primary=AgentConfig(model="primary/model"),
        preflight=AgentConfig(model="preflight/model"),
        openrouter_api_key="k",
        openrouter_base_url="u",
        resolver_cfg=override,
    )
    assert cfg.for_resolver.model == "override/model"
    assert cfg.for_constructor.model == "primary/model"
