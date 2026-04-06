"""Shared test fixtures."""
from __future__ import annotations

import pytest

from gauntlet.models import Attack, AttackType, EvaluateRequest, Ground, PipelineState


@pytest.fixture
def base_request() -> EvaluateRequest:
    return EvaluateRequest.model_validate(
        "We should deprioritise this patient because serial troponins are negative."
    )


@pytest.fixture
def state_with_grounds() -> PipelineState:
    return PipelineState(
        domain_standard="senior engineer, distributed systems",
        claim="decompose the monolith",
        grounds=[
            Ground(content="High deploy frequency needed", source="ops"),
            Ground(content="Teams blocked on releases", source="eng"),
            Ground(content="DB schemas tightly coupled", source="arch"),
        ],
        warrant="It is assumed that: tight coupling prevents independent deployment",
        qualifier="presumably",
    )


@pytest.fixture
def sample_attack() -> Attack:
    return Attack(
        type=AttackType.undercutting,
        content="Troponin measurement absent - cardiac risk inference unvalidated",
        source_agent="critique",
    )
