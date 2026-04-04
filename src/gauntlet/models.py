"""
models.py — Core data models, per-agent views, and API types.

BIPOLAR ARCHITECTURE:
Every evaluation runs both the claim and its logical contrary through the
full pipeline. A claim that survives without its contrary being defeated
produces only a plausible conclusion. A definite conclusion requires that
the contrary also fails independently.

  claim survives, contrary defeated  → definite_conclusion
  contrary survives, claim defeated  → wrong_starting_position
  both survive                       → equipoise
  neither survives                   → insufficient_evidence

FIELD ISOLATION:
Each agent receives a Pydantic model containing only its designated fields.
The orchestrator constructs these views — agents never touch ArgumentUnit.
Isolation is structural, not instructional.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────────────

class DialogueType(str, Enum):
    deliberation = "deliberation"   # deciding what to do
    inquiry      = "inquiry"        # establishing what is true
    persuasion   = "persuasion"     # resolving a conflict of opinion


class Verdict(str, Enum):
    survives = "survives"
    defeated = "defeated"
    impasse  = "impasse"


class AttackType(str, Enum):
    rebuttal     = "rebuttal"      # attacks the claim directly
    undercutting = "undercutting"  # attacks the warrant (inference rule)
    undermining  = "undermining"   # attacks the grounds (evidential basis)


class Severity(str, Enum):
    blocking = "blocking"
    advisory = "advisory"


class RebuttalStatus(str, Enum):
    surviving = "surviving"
    defeated  = "defeated"


class BipolarComparison(str, Enum):
    """
    The four possible outcomes of bipolar argumentation evaluation.
    Only definite_conclusion produces a verdict the system can stand behind.
    """
    definite_conclusion     = "definite_conclusion"
    wrong_starting_position = "wrong_starting_position"
    equipoise               = "equipoise"
    insufficient_evidence   = "insufficient_evidence"


# ── Evidence and attack sub-models ────────────────────────────────────────────

class Ground(BaseModel):
    content:          str
    source:           str
    probative_weight: float = Field(ge=0.0, le=1.0)


class CriticalQuestion(BaseModel):
    question: str
    answered: bool
    answer:   Optional[str] = None


class Attack(BaseModel):
    type:         AttackType
    content:      str
    source_agent: str


class RuleViolation(BaseModel):
    rule:        str
    stage:       str
    severity:    Severity
    description: str


class StageAudit(BaseModel):
    confrontation: str
    opening:       str
    argumentation: str
    blocked:       bool


class AttackNode(BaseModel):
    id:          str
    type:        Optional[AttackType] = None
    description: str


class AttackEdge(BaseModel):
    from_node:   str = Field(alias="from")
    to_node:     str = Field(alias="to")
    attack_type: AttackType
    model_config = {"populate_by_name": True}


class AttackGraph(BaseModel):
    nodes: list[AttackNode]
    edges: list[AttackEdge]


class RebuttalEntry(BaseModel):
    timestamp:   str
    agent:       str
    attack_type: AttackType
    content:     str
    status:      RebuttalStatus


class TokenUsage(BaseModel):
    input_tokens:  int = 0
    output_tokens: int = 0

    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


# ── Full ArgumentUnit ─────────────────────────────────────────────────────────

class ArgumentUnit(BaseModel):
    """
    The single shared state object. Owned exclusively by the orchestrator.
    No agent ever reads this directly — each receives a typed projection.
    """

    # Identity — set at creation, immutable
    id:                str          = Field(default_factory=lambda: str(uuid.uuid4()))
    cycle:             int          = 1
    dialogue_type:     DialogueType
    domain_standard:   str
    termination_limit: int          = 3

    # Toulmin structure — Agent 0 (Constructor)
    claim:     str
    grounds:   list[Ground]        = Field(default_factory=list)
    warrant:   Optional[str]       = None
    backing:   Optional[str]       = None
    qualifier: str                 = "presumably"

    # Scheme and attacks — Agent 1 (Classifier)
    scheme:             Optional[str]          = None
    critical_questions: list[CriticalQuestion] = Field(default_factory=list)
    open_attacks:       list[Attack]           = Field(default_factory=list)
    burden_bearer:      Optional[str]          = None

    # Exchange audit — Agent 2 (Auditor)
    stage_audit:     Optional[StageAudit] = None
    rule_violations: list[RuleViolation]  = Field(default_factory=list)

    # Acceptance — Agent 3 (Evaluator)
    acceptance:     Optional[bool] = None
    acceptance_gap: Optional[str]  = None

    # Resolution — Agent 4 (Resolver)
    attack_graph: Optional[AttackGraph] = None
    extension:    Optional[str]         = None
    verdict:      Optional[Verdict]     = None

    # Discourse record — append-only across all cycles
    rebuttal_log: list[RebuttalEntry] = Field(default_factory=list)

    # Accumulated cost for this unit
    usage: TokenUsage = Field(default_factory=TokenUsage)


# ── Per-agent scoped INPUT models ─────────────────────────────────────────────
# These are the ONLY thing each agent sees. The orchestrator builds these
# from ArgumentUnit via the view functions below.

class ConstructorInput(BaseModel):
    claim:          str
    dialogue_type:  DialogueType
    grounds:        Optional[list[Ground]] = None   # None → retrieve from scratch
    warrant:        Optional[str]          = None
    backing:        Optional[str]          = None
    qualifier:      Optional[str]          = None
    acceptance_gap: Optional[str]          = None   # populated on cycle 2+
    rebuttal_log:   list[RebuttalEntry]    = Field(default_factory=list)


class ClassifierInput(BaseModel):
    claim:         str
    grounds:       list[Ground]
    warrant:       Optional[str]
    backing:       Optional[str]
    qualifier:     str
    dialogue_type: DialogueType


class AuditorInput(BaseModel):
    claim:         str
    grounds:       list[Ground]
    warrant:       Optional[str]
    backing:       Optional[str]
    qualifier:     str
    dialogue_type: DialogueType
    burden_bearer: Optional[str]
    open_attacks:  list[Attack]


class EvaluatorInput(BaseModel):
    claim:           str
    grounds:         list[Ground]
    warrant:         Optional[str]
    backing:         Optional[str]
    qualifier:       str
    domain_standard: str           # ONLY this agent sees the normative criterion
    stage_audit:     Optional[StageAudit]
    rule_violations: list[RuleViolation]


class ResolverInput(BaseModel):
    claim:             str
    grounds:           list[Ground]
    warrant:           Optional[str]
    qualifier:         str
    open_attacks:      list[Attack]
    rule_violations:   list[RuleViolation]
    acceptance_gap:    Optional[str]
    rebuttal_log:      list[RebuttalEntry]
    cycle:             int
    termination_limit: int


# ── Per-agent scoped OUTPUT models ────────────────────────────────────────────

class ConstructorOutput(BaseModel):
    grounds:   list[Ground]
    warrant:   Optional[str]
    backing:   Optional[str]
    qualifier: str


class ClassifierOutput(BaseModel):
    scheme:             str
    critical_questions: list[CriticalQuestion]
    open_attacks:       list[Attack]
    burden_bearer:      str


class AuditorOutput(BaseModel):
    stage_audit:     StageAudit
    rule_violations: list[RuleViolation]
    acceptance_gap:  Optional[str]


class EvaluatorOutput(BaseModel):
    acceptance:     bool
    acceptance_gap: Optional[str]


class ResolverOutput(BaseModel):
    attack_graph: AttackGraph
    extension:    str
    verdict:      Verdict
    rebuttal_log: list[RebuttalEntry]


# ── View functions — structural field isolation ────────────────────────────────

def constructor_view(unit: ArgumentUnit) -> ConstructorInput:
    return ConstructorInput(
        claim=unit.claim,
        dialogue_type=unit.dialogue_type,
        grounds=unit.grounds if unit.grounds else None,
        warrant=unit.warrant,
        backing=unit.backing,
        qualifier=unit.qualifier if unit.qualifier != "presumably" else None,
        acceptance_gap=unit.acceptance_gap,
        rebuttal_log=unit.rebuttal_log,
    )


def classifier_view(unit: ArgumentUnit) -> ClassifierInput:
    return ClassifierInput(
        claim=unit.claim,
        grounds=unit.grounds,
        warrant=unit.warrant,
        backing=unit.backing,
        qualifier=unit.qualifier,
        dialogue_type=unit.dialogue_type,
    )


def auditor_view(unit: ArgumentUnit) -> AuditorInput:
    return AuditorInput(
        claim=unit.claim,
        grounds=unit.grounds,
        warrant=unit.warrant,
        backing=unit.backing,
        qualifier=unit.qualifier,
        dialogue_type=unit.dialogue_type,
        burden_bearer=unit.burden_bearer,
        open_attacks=unit.open_attacks,
    )


def evaluator_view(unit: ArgumentUnit) -> EvaluatorInput:
    return EvaluatorInput(
        claim=unit.claim,
        grounds=unit.grounds,
        warrant=unit.warrant,
        backing=unit.backing,
        qualifier=unit.qualifier,
        domain_standard=unit.domain_standard,
        stage_audit=unit.stage_audit,
        rule_violations=unit.rule_violations,
    )


def resolver_view(unit: ArgumentUnit) -> ResolverInput:
    return ResolverInput(
        claim=unit.claim,
        grounds=unit.grounds,
        warrant=unit.warrant,
        qualifier=unit.qualifier,
        open_attacks=unit.open_attacks,
        rule_violations=unit.rule_violations,
        acceptance_gap=unit.acceptance_gap,
        rebuttal_log=unit.rebuttal_log,
        cycle=unit.cycle,
        termination_limit=unit.termination_limit,
    )


# ── API request / response types ──────────────────────────────────────────────

class EvaluateRequest(BaseModel):
    claim:             str
    dialogue_type:     DialogueType
    domain_standard:   str
    termination_limit: int                    = Field(default=3, ge=1, le=10)
    grounds:           Optional[list[Ground]] = None
    warrant:           Optional[str]          = None
    backing:           Optional[str]          = None
    qualifier:         Optional[str]          = None


class ClaimEvaluation(BaseModel):
    """
    Result of evaluating one position (the original claim OR its contrary)
    through the full five-agent pipeline. GauntletResult always contains two.
    """
    claim:          str
    verdict:        Verdict
    qualifier:      str
    acceptance_gap: Optional[str]
    rebuttal_log:   list[RebuttalEntry]
    cycles_run:     int
    no_progress:    bool
    usage:          TokenUsage
    argument_unit:  ArgumentUnit


class GauntletResult(BaseModel):
    """
    Bipolar argumentation result. Always contains both positions.
    The comparison field is the definitive interpretation.
    """
    id:                   str
    claim_evaluation:     ClaimEvaluation
    contrary_evaluation:  ClaimEvaluation
    comparison:           BipolarComparison
    recommended_position: Optional[str]   # the surviving claim, or null
    total_usage:          TokenUsage


class JobStatus(str, Enum):
    pending  = "pending"
    running  = "running"
    complete = "complete"
    failed   = "failed"


class EvaluationJob(BaseModel):
    job_id: str
    status: JobStatus
    result: Optional[GauntletResult] = None
    error:  Optional[str]            = None
