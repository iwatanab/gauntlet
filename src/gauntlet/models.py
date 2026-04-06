"""
models.py - Core data models, stage boundaries, and public API types.

BIPOLAR ARCHITECTURE:
Every evaluation runs both the claim and its logical contrary through the
same deliberative pipeline. The claim and contrary remain independent until
pure-Python comparison at the end.

FIELD ISOLATION:
Each stage receives a Pydantic model containing only its designated fields.
The orchestrator owns the internal position state and constructs the stage views.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, RootModel


class Verdict(str, Enum):
    survives = "survives"
    defeated = "defeated"
    impasse = "impasse"


class AttackType(str, Enum):
    rebuttal = "rebuttal"
    undercutting = "undercutting"
    undermining = "undermining"


class Severity(str, Enum):
    blocking = "blocking"
    advisory = "advisory"


class RebuttalStatus(str, Enum):
    surviving = "surviving"
    defeated = "defeated"


class BipolarComparison(str, Enum):
    definite_conclusion = "definite_conclusion"
    wrong_starting_position = "wrong_starting_position"
    equipoise = "equipoise"
    insufficient_evidence = "insufficient_evidence"


class Ground(BaseModel):
    content: str
    source: str
    user_provided: bool = False


class CriticalQuestion(BaseModel):
    question: str
    answered: bool
    answer: Optional[str] = None


class Attack(BaseModel):
    type: AttackType
    content: str
    source_agent: str


class RuleViolation(BaseModel):
    rule: str
    stage: str
    severity: Severity
    description: str


class StageAudit(BaseModel):
    confrontation: str
    opening: str
    argumentation: str
    blocked: bool


class RebuttalEntry(BaseModel):
    timestamp: str
    agent: str
    attack_type: AttackType
    content: str
    status: RebuttalStatus


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass
class PositionState:
    claim: str
    domain_standard: str
    grounds: list[Ground] = field(default_factory=list)
    warrant: str | None = None
    backing: str | None = None
    qualifier: str = "presumably"
    cycle: int = 1
    final_cycle: bool = False
    scheme: str | None = None
    critical_questions: list[CriticalQuestion] = field(default_factory=list)
    open_attacks: list[Attack] = field(default_factory=list)
    stage_audit: StageAudit | None = None
    rule_violations: list[RuleViolation] = field(default_factory=list)
    required_gap: str | None = None
    rebuttal_log: list[RebuttalEntry] = field(default_factory=list)
    verdict: Verdict | None = None

    def reset_cycle(self) -> None:
        self.scheme = None
        self.critical_questions = []
        self.open_attacks = []
        self.stage_audit = None
        self.rule_violations = []
        self.required_gap = None
        self.verdict = None


class ConstructorInput(BaseModel):
    claim: str
    grounds: Optional[list[Ground]] = None
    warrant: Optional[str] = None
    backing: Optional[str] = None
    qualifier: Optional[str] = None
    required_gap: Optional[str] = None


class CritiqueInput(BaseModel):
    claim: str
    grounds: list[Ground]
    warrant: Optional[str]
    backing: Optional[str]
    qualifier: str


class EvaluatorInput(BaseModel):
    claim: str
    grounds: list[Ground]
    warrant: Optional[str]
    backing: Optional[str]
    qualifier: str
    domain_standard: str
    stage_audit: Optional[StageAudit]
    rule_violations: list[RuleViolation]


class ResolverInput(BaseModel):
    claim: str
    grounds: list[Ground]
    warrant: Optional[str]
    backing: Optional[str]
    qualifier: str
    open_attacks: list[Attack]
    rule_violations: list[RuleViolation]
    required_gap: Optional[str]
    rebuttal_log: list[RebuttalEntry]
    final_cycle: bool


class ConstructorOutput(BaseModel):
    grounds: list[Ground]
    warrant: Optional[str]
    backing: Optional[str]
    qualifier: str


class CritiqueOutput(BaseModel):
    scheme: str
    critical_questions: list[CriticalQuestion]
    open_attacks: list[Attack]
    stage_audit: StageAudit
    rule_violations: list[RuleViolation]
    required_gap: Optional[str]


class EvaluatorOutput(BaseModel):
    acceptance: bool
    required_gap: Optional[str]


class ResolverOutput(BaseModel):
    verdict: Verdict
    rebuttal_log: list[RebuttalEntry]


def constructor_view(state: PositionState) -> ConstructorInput:
    return ConstructorInput(
        claim=state.claim,
        grounds=state.grounds or None,
        warrant=state.warrant,
        backing=state.backing,
        qualifier=state.qualifier if state.qualifier != "presumably" else None,
        required_gap=state.required_gap,
    )


def critique_view(state: PositionState) -> CritiqueInput:
    return CritiqueInput(
        claim=state.claim,
        grounds=state.grounds,
        warrant=state.warrant,
        backing=state.backing,
        qualifier=state.qualifier,
    )


def evaluator_view(state: PositionState) -> EvaluatorInput:
    return EvaluatorInput(
        claim=state.claim,
        grounds=state.grounds,
        warrant=state.warrant,
        backing=state.backing,
        qualifier=state.qualifier,
        domain_standard=state.domain_standard,
        stage_audit=state.stage_audit,
        rule_violations=state.rule_violations,
    )


def resolver_view(state: PositionState) -> ResolverInput:
    return ResolverInput(
        claim=state.claim,
        grounds=state.grounds,
        warrant=state.warrant,
        backing=state.backing,
        qualifier=state.qualifier,
        open_attacks=state.open_attacks,
        rule_violations=state.rule_violations,
        required_gap=state.required_gap,
        rebuttal_log=state.rebuttal_log,
        final_cycle=state.final_cycle,
    )


class FinalArgument(BaseModel):
    grounds: list[Ground]
    warrant: Optional[str]
    backing: Optional[str]
    qualifier: str


class EvaluationIssues(BaseModel):
    scheme: Optional[str] = None
    critical_questions: list[CriticalQuestion] = Field(default_factory=list)
    open_attacks: list[Attack] = Field(default_factory=list)
    rule_violations: list[RuleViolation] = Field(default_factory=list)


class ToolCallTrace(BaseModel):
    tool: str
    query: str
    result_chars: int
    result_preview: str


class PreflightSummary(BaseModel):
    claim: str
    domain_standard: str
    termination_limit: int
    grounds_count: int | None = None
    has_warrant: bool | None = None
    has_backing: bool | None = None
    generated_from: str | None = None


class StageSummary(BaseModel):
    grounds_count: int | None = None
    qualifier: str | None = None
    warrant_preview: str | None = None
    has_backing: bool | None = None
    scheme: str | None = None
    open_attacks_count: int | None = None
    answered_cqs: int | None = None
    unanswered_cqs: int | None = None
    blocked: bool | None = None
    violations_count: int | None = None
    blocking_violations: int | None = None
    accepted: bool | None = None
    verdict: Verdict | None = None
    surviving_attacks: int | None = None
    defeated_attacks: int | None = None
    required_gap: str | None = None
    blocking_rule: str | None = None
    blocking_stage: str | None = None
    repeated_gap: str | None = None


class StageTrace(BaseModel):
    status: Literal["completed", "blocked", "rejected"]
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    summary: StageSummary
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)


class CycleTrace(BaseModel):
    cycle: int
    constructor: Optional[StageTrace] = None
    critique: Optional[StageTrace] = None
    evaluator: Optional[StageTrace] = None
    resolver: Optional[StageTrace] = None
    decision: Optional[str] = None


class PositionMetrics(BaseModel):
    stage_calls: int = 0
    tool_calls: int = 0
    cycles_used: int = 0


class PositionTrace(BaseModel):
    position: str
    preflight: Optional[PreflightSummary] = None
    preflight_usage: TokenUsage = Field(default_factory=TokenUsage)
    cycles: list[CycleTrace] = Field(default_factory=list)
    halt_reason: Optional[str] = None
    metrics: PositionMetrics = Field(default_factory=PositionMetrics)


class EvaluateRequest(RootModel[str]):
    """Public API request body: a single JSON string."""

    @property
    def input(self) -> str:
        return self.root


class InputErrorResponse(BaseModel):
    code: str
    message: str
    claims: Optional[list[str]] = None


class ClaimEvaluation(BaseModel):
    claim: str
    verdict: Verdict
    final_argument: FinalArgument
    issues: EvaluationIssues
    required_gap: Optional[str]
    rebuttal_log: list[RebuttalEntry]
    trace: PositionTrace
    usage: TokenUsage


class GauntletResult(BaseModel):
    id: str
    claim_evaluation: ClaimEvaluation
    contrary_evaluation: ClaimEvaluation
    comparison: BipolarComparison
    recommended_position: Optional[str]
    inferred_domain_standard: Optional[str] = None
    total_usage: TokenUsage


class JobStatus(str, Enum):
    pending = "pending"
    running = "running"
    complete = "complete"
    failed = "failed"


class EvaluationJob(BaseModel):
    job_id: str
    status: JobStatus
    result: Optional[GauntletResult] = None
    error: Optional[str] = None
