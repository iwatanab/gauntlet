"""
test_api.py — API endpoint tests with mocked pipeline.

No real LLM calls. Verifies routing, validation enforcement, bipolar
response shape, and job management.
"""
from __future__ import annotations
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from gauntlet.api import app
from gauntlet.models import (
    ArgumentUnit, BipolarComparison, ClaimEvaluation,
    DialogueType, EvaluationJob, GauntletResult, JobStatus,
    RebuttalEntry, TokenUsage, Verdict, AttackType, RebuttalStatus,
)


def _unit(claim="test claim") -> ArgumentUnit:
    u = ArgumentUnit(
        dialogue_type=DialogueType.deliberation,
        domain_standard="test domain",
        claim=claim,
        qualifier="presumably",
    )
    u.verdict = Verdict.survives
    return u


def _claim_eval(claim="test claim", verdict=Verdict.survives) -> ClaimEvaluation:
    return ClaimEvaluation(
        claim=claim,
        verdict=verdict,
        qualifier="presumably",
        acceptance_gap=None,
        rebuttal_log=[],
        cycles_run=1,
        no_progress=False,
        usage=TokenUsage(input_tokens=1000, output_tokens=300),
        argument_unit=_unit(claim),
    )


def _result(
    comparison=BipolarComparison.definite_conclusion,
    claim_verdict=Verdict.survives,
    contrary_verdict=Verdict.defeated,
) -> GauntletResult:
    ce = _claim_eval("do the thing",    claim_verdict)
    xe = _claim_eval("do not the thing", contrary_verdict)
    rec = "do the thing" if comparison == BipolarComparison.definite_conclusion else None
    return GauntletResult(
        id=ce.argument_unit.id,
        claim_evaluation=ce,
        contrary_evaluation=xe,
        comparison=comparison,
        recommended_position=rec,
        total_usage=TokenUsage(input_tokens=2500, output_tokens=700),
    )


VALID = {
    "claim":            "implement mandatory 2FA for all admin routes",
    "dialogue_type":    "deliberation",
    "domain_standard":  "senior security engineer, NIST SP 800-63B",
    "termination_limit": 2,
}


@pytest.fixture
def client():
    from gauntlet import api as m
    from gauntlet.config import GauntletConfig, AgentConfig
    m._config = GauntletConfig(
        primary=AgentConfig(model="test/model"),
        fast=AgentConfig(model="test/fast"),
        openrouter_api_key="test",
        openrouter_base_url="https://test.example.com",
    )
    m._client = AsyncMock()
    with TestClient(app) as c:
        yield c


# ── Health ────────────────────────────────────────────────────────────────────

def test_health_ok(client):
    r = client.get("/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert "version" in r.json()


# ── Validation enforcement ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_claim,expected_status", [
    ("", 422),
    ("ignore previous instructions", 422),
    ("jailbreak", 422),
])
def test_bad_claims_rejected(bad_claim, expected_status, client):
    r = client.post("/v1/evaluate", json={**VALID, "claim": bad_claim})
    assert r.status_code == expected_status


def test_missing_domain_standard_rejected(client):
    payload = {k: v for k, v in VALID.items() if k != "domain_standard"}
    assert client.post("/v1/evaluate", json=payload).status_code == 422


def test_invalid_dialogue_type_rejected(client):
    r = client.post("/v1/evaluate", json={**VALID, "dialogue_type": "debate"})
    assert r.status_code == 422


def test_termination_limit_bounds(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = _result()
        assert client.post("/v1/evaluate", json={**VALID, "termination_limit": 0}).status_code == 422
        assert client.post("/v1/evaluate", json={**VALID, "termination_limit": 11}).status_code == 422
        assert client.post("/v1/evaluate", json={**VALID, "termination_limit": 5}).status_code == 200


# ── Bipolar response structure ────────────────────────────────────────────────

def test_sync_evaluate_returns_bipolar_shape(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = _result()
        r = client.post("/v1/evaluate", json=VALID)
    assert r.status_code == 200
    d = r.json()
    for field in ("id", "claim_evaluation", "contrary_evaluation",
                  "comparison", "recommended_position", "total_usage"):
        assert field in d, f"missing field: {field}"


def test_definite_conclusion_has_recommended_position(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = _result(BipolarComparison.definite_conclusion)
        d = client.post("/v1/evaluate", json=VALID).json()
    assert d["comparison"] == "definite_conclusion"
    assert d["recommended_position"] is not None


def test_wrong_starting_position_recommends_contrary(client):
    result = _result(BipolarComparison.wrong_starting_position,
                     Verdict.defeated, Verdict.survives)
    result.recommended_position = "do not the thing"
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = result
        d = client.post("/v1/evaluate", json=VALID).json()
    assert d["comparison"] == "wrong_starting_position"
    assert d["recommended_position"] == "do not the thing"


def test_equipoise_has_no_recommended_position(client):
    result = _result(BipolarComparison.equipoise, Verdict.survives, Verdict.survives)
    result.recommended_position = None
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = result
        d = client.post("/v1/evaluate", json=VALID).json()
    assert d["comparison"]          == "equipoise"
    assert d["recommended_position"] is None


def test_insufficient_evidence_has_no_recommended_position(client):
    result = _result(BipolarComparison.insufficient_evidence, Verdict.impasse, Verdict.impasse)
    result.recommended_position = None
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = result
        d = client.post("/v1/evaluate", json=VALID).json()
    assert d["comparison"]          == "insufficient_evidence"
    assert d["recommended_position"] is None


def test_each_evaluation_has_own_fields(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = _result()
        d = client.post("/v1/evaluate", json=VALID).json()
    for side in ("claim_evaluation", "contrary_evaluation"):
        assert "verdict"       in d[side]
        assert "qualifier"     in d[side]
        assert "rebuttal_log"  in d[side]
        assert "cycles_run"    in d[side]
        assert "no_progress"   in d[side]
        assert "usage"         in d[side]
        assert "argument_unit" in d[side]


def test_total_usage_sums_both_pipelines(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = _result()
        d = client.post("/v1/evaluate", json=VALID).json()
    usage = d["total_usage"]
    assert usage["input_tokens"]  == 2500
    assert usage["output_tokens"] == 700


def test_pipeline_error_returns_500(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.side_effect = RuntimeError("model unavailable")
        r = client.post("/v1/evaluate", json=VALID)
    assert r.status_code == 500


# ── Async endpoint ────────────────────────────────────────────────────────────

def test_async_endpoint_returns_job_id(client):
    with patch("gauntlet.api.run_pipeline", new_callable=AsyncMock) as m:
        m.return_value = _result()
        r = client.post("/v1/evaluate/async", json=VALID)
    assert r.status_code == 202
    assert "job_id" in r.json()
    assert len(r.json()["job_id"]) == 36  # UUID


def test_job_not_found_returns_404(client):
    assert client.get("/v1/jobs/does-not-exist").status_code == 404


def test_delete_nonexistent_job_returns_404(client):
    assert client.delete("/v1/jobs/does-not-exist").status_code == 404


# ── Config ────────────────────────────────────────────────────────────────────

def test_config_property_accessors():
    from gauntlet.config import GauntletConfig, AgentConfig
    primary = AgentConfig(model="primary/model")
    fast    = AgentConfig(model="fast/model")
    cfg = GauntletConfig(
        primary=primary, fast=fast,
        openrouter_api_key="k", openrouter_base_url="u",
    )
    # All per-agent configs default to primary
    assert cfg.for_constructor.model == "primary/model"
    assert cfg.for_classifier.model  == "primary/model"
    assert cfg.for_auditor.model     == "primary/model"
    assert cfg.for_evaluator.model   == "primary/model"
    assert cfg.for_resolver.model    == "primary/model"


def test_config_per_agent_override():
    from gauntlet.config import GauntletConfig, AgentConfig
    override = AgentConfig(model="override/model")
    cfg = GauntletConfig(
        primary=AgentConfig(model="primary/model"),
        fast=AgentConfig(model="fast/model"),
        openrouter_api_key="k", openrouter_base_url="u",
        resolver_cfg=override,
    )
    assert cfg.for_resolver.model    == "override/model"
    assert cfg.for_constructor.model == "primary/model"
