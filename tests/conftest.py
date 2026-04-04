"""Shared test fixtures."""
from __future__ import annotations
import pytest
from gauntlet.models import (
    ArgumentUnit, DialogueType, EvaluateRequest, Ground, Attack, AttackType,
)


@pytest.fixture
def base_request() -> EvaluateRequest:
    return EvaluateRequest(
        claim="deprioritise this patient",
        dialogue_type=DialogueType.deliberation,
        domain_standard=(
            "experienced emergency clinician, "
            "NICE NSTEMI troponin rule-out protocol NG185"
        ),
        termination_limit=3,
    )


@pytest.fixture
def unit_with_grounds() -> ArgumentUnit:
    return ArgumentUnit(
        dialogue_type=DialogueType.deliberation,
        domain_standard="senior engineer, distributed systems",
        claim="decompose the monolith",
        grounds=[
            Ground(content="High deploy frequency needed", source="ops", probative_weight=0.8),
            Ground(content="Teams blocked on releases",   source="eng", probative_weight=0.6),
            Ground(content="DB schemas tightly coupled",  source="arch", probative_weight=0.3),
        ],
        warrant="It is assumed that: tight coupling prevents independent deployment",
        qualifier="presumably",
    )


@pytest.fixture
def sample_attack() -> Attack:
    return Attack(
        type=AttackType.undercutting,
        content="Troponin measurement absent — cardiac risk inference unvalidated",
        source_agent="classifier",
    )
