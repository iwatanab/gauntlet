"""
orchestrator.py - Bipolar deliberative pipeline.

Gauntlet's runtime now keeps only the execution boundaries required by
field isolation and tool isolation:
  Constructor -> Critique Bundle -> Evaluator -> Resolver
"""

from __future__ import annotations

import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from gauntlet.agents.constructor import run_constructor
from gauntlet.agents.critique import run_critique_bundle
from gauntlet.agents.evaluator import run_evaluator
from gauntlet.agents.resolver import run_resolver
from gauntlet.client import GauntletClient
from gauntlet.config import GauntletConfig
from gauntlet.models import (
    AttackType,
    BipolarComparison,
    ClaimEvaluation,
    EvaluateRequest,
    EvaluationIssues,
    FinalArgument,
    GauntletResult,
    Ground,
    PositionState,
    PreflightSummary,
    RebuttalEntry,
    RebuttalStatus,
    TokenUsage,
    Verdict,
    constructor_view,
    critique_view,
    evaluator_view,
    resolver_view,
)
from gauntlet.parsing import check_and_parse, grounds_from_parsed
from gauntlet.trace import PipelineTrace

TERMINATION_LIMIT = 3


@dataclass
class PreparedEvaluationInput:
    claim: str
    grounds: list[Ground]
    warrant: str | None
    backing: str | None
    qualifier: str
    domain_standard: str
    usage: TokenUsage


def _contrary_is_valid(text: str) -> bool:
    candidate = text.strip()
    if len(candidate) < 8:
        return False
    if candidate[-1] in "-,;:(":
        return False
    return True


async def _generate_contrary(
    claim: str,
    config: GauntletConfig,
    client: GauntletClient,
) -> tuple[str, TokenUsage]:
    system = (
        "You generate the logical contrary of an argumentative claim. "
        "The contrary is the most reasonable opposing standpoint a rational person "
        "might hold given the same situation, not a strawman. "
        "Keep the same level of specificity as the original. "
        "Output only the contrary claim as a single sentence."
    )
    fallback = f"do not {claim}"
    try:
        text, usage = await client.complete_text(
            model=config.preflight.model,
            system=system,
            user=f"Generate the logical contrary of: {claim}",
            max_tokens=120,
        )
        contrary = text.strip()
        if not _contrary_is_valid(contrary):
            return fallback, usage
        return contrary, usage
    except Exception:
        return fallback, TokenUsage()


async def _infer_domain_standard(
    claim: str,
    config: GauntletConfig,
    client: GauntletClient,
) -> tuple[str, TokenUsage]:
    system = (
        "You infer the domain standard for evaluating a deliberative claim. "
        "The domain standard is the evidential criterion or normative threshold "
        "the evaluator should apply. Output only the standard as a concise phrase."
    )
    try:
        text, usage = await client.complete_text(
            model=config.preflight.model,
            system=system,
            user=f"Claim: {claim}",
            max_tokens=80,
        )
        return text.strip() or "balance of probabilities", usage
    except Exception:
        return "balance of probabilities", TokenUsage()


async def prepare_evaluation_input(
    text: str,
    config: GauntletConfig,
    client: GauntletClient,
) -> PreparedEvaluationInput:
    parsed, parse_usage = await check_and_parse(text, config.preflight, client)
    claim = parsed.claim or ""
    grounds = grounds_from_parsed(parsed.grounds)
    warrant = parsed.warrant
    backing = parsed.backing
    qualifier = parsed.qualifier or "presumably"
    domain_standard, infer_usage = await _infer_domain_standard(claim, config, client)
    return PreparedEvaluationInput(
        claim=claim,
        grounds=grounds,
        warrant=warrant,
        backing=backing,
        qualifier=qualifier,
        domain_standard=domain_standard,
        usage=parse_usage + infer_usage,
    )


def _compare(claim_v: Verdict | None, contrary_v: Verdict | None) -> BipolarComparison:
    claim_survives = claim_v == Verdict.survives
    contrary_survives = contrary_v == Verdict.survives
    if claim_survives and not contrary_survives:
        return BipolarComparison.definite_conclusion
    if contrary_survives and not claim_survives:
        return BipolarComparison.wrong_starting_position
    if claim_survives and contrary_survives:
        return BipolarComparison.equipoise
    return BipolarComparison.insufficient_evidence


def _recommended(comp: BipolarComparison, claim: str, contrary: str) -> str | None:
    if comp == BipolarComparison.definite_conclusion:
        return claim
    if comp == BipolarComparison.wrong_starting_position:
        return contrary
    return None


def _gap_key(gap: str) -> str:
    normalized = re.sub(r"(?i)^required:\s*", "", gap.strip())
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.lower()


def _no_progress(current: str | None, previous: str | None, cycle: int) -> bool:
    if cycle <= 1 or current is None or previous is None:
        return False
    return _gap_key(current) == _gap_key(previous)


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _blocking_entries(agent: str, descriptions: list[str]) -> list[RebuttalEntry]:
    return [
        RebuttalEntry(
            timestamp=_ts(),
            agent=agent,
            attack_type=AttackType.rebuttal,
            content=description,
            status=RebuttalStatus.surviving,
        )
        for description in descriptions
    ]


def _blocking_descriptions(state: PositionState) -> list[str]:
    return [
        violation.description
        for violation in state.rule_violations
        if violation.severity.value == "blocking"
    ]


def _gap_outcome(current: str | None, previous: str | None, cycle: int, limit: int) -> str | None:
    if _no_progress(current, previous, cycle):
        return "no_progress"
    if cycle == limit:
        return "limit"
    return None


def _preflight_summary(
    *,
    claim: str,
    domain_standard: str,
    grounds: list[Ground] | None = None,
    warrant: str | None = None,
    backing: str | None = None,
    generated_from: str | None = None,
) -> PreflightSummary:
    if generated_from is not None:
        return PreflightSummary(
            claim=claim,
            domain_standard=domain_standard,
            termination_limit=TERMINATION_LIMIT,
            generated_from=generated_from,
        )
    return PreflightSummary(
        claim=claim,
        domain_standard=domain_standard,
        termination_limit=TERMINATION_LIMIT,
        grounds_count=len(grounds or []),
        has_warrant=warrant is not None,
        has_backing=backing is not None,
    )


def _final_argument(state: PositionState) -> FinalArgument:
    return FinalArgument(
        grounds=state.grounds,
        warrant=state.warrant,
        backing=state.backing,
        qualifier=state.qualifier,
    )


def _issues(state: PositionState) -> EvaluationIssues:
    return EvaluationIssues(
        scheme=state.scheme,
        critical_questions=state.critical_questions,
        open_attacks=state.open_attacks,
        rule_violations=state.rule_violations,
    )


async def run_claim_pipeline(
    claim: str,
    domain_standard: str,
    qualifier: str,
    config: GauntletConfig,
    client: GauntletClient,
    position: str,
    preflight_summary: PreflightSummary,
    preflight_usage: TokenUsage,
    initial_grounds: list[Ground] | None = None,
    initial_warrant: str | None = None,
    initial_backing: str | None = None,
) -> ClaimEvaluation:
    trace = PipelineTrace(position)
    trace.set_preflight(preflight_summary, preflight_usage)

    state = PositionState(
        claim=claim,
        grounds=list(initial_grounds) if initial_grounds else [],
        warrant=initial_warrant,
        backing=initial_backing,
        qualifier=qualifier,
        domain_standard=domain_standard,
    )

    total_usage = preflight_usage
    no_progress = False
    prev_gap: str | None = None

    print(f"\n  -- {position.upper()} pipeline --", file=sys.stderr)

    for cycle in range(1, TERMINATION_LIMIT + 1):
        state.cycle = cycle
        state.final_cycle = cycle == TERMINATION_LIMIT
        trace.cycle_start(cycle, TERMINATION_LIMIT)
        print(f"    cycle {cycle}/{TERMINATION_LIMIT}", file=sys.stderr)

        constructor_out, usage = await run_constructor(
            constructor_view(state), config.for_constructor, client, trace, cycle
        )
        state.grounds = constructor_out.grounds
        state.warrant = constructor_out.warrant
        state.backing = constructor_out.backing
        state.qualifier = constructor_out.qualifier
        total_usage = total_usage + usage

        state.reset_cycle()

        critique_out, usage = await run_critique_bundle(
            critique_view(state), config.for_critique, client, trace, cycle
        )
        state.scheme = critique_out.scheme
        state.critical_questions = critique_out.critical_questions
        state.open_attacks = critique_out.open_attacks
        state.stage_audit = critique_out.stage_audit
        state.rule_violations = critique_out.rule_violations
        total_usage = total_usage + usage

        if critique_out.stage_audit.blocked:
            state.required_gap = critique_out.required_gap
            trace.critique_blocked(
                cycle=cycle,
                rule=critique_out.rule_violations[0].rule if critique_out.rule_violations else "unknown",
                stage=critique_out.rule_violations[0].stage if critique_out.rule_violations else "unknown",
                required_gap=critique_out.required_gap or "",
            )
            outcome = _gap_outcome(state.required_gap, prev_gap, cycle, TERMINATION_LIMIT)
            if outcome:
                state.verdict = Verdict.impasse
                state.rebuttal_log = state.rebuttal_log + _blocking_entries(
                    "critique",
                    _blocking_descriptions(state),
                )
                if outcome == "no_progress":
                    no_progress = True
                    trace.no_progress_halt(cycle, state.required_gap or "")
                break
            prev_gap = state.required_gap
            continue

        evaluator_out, usage = await run_evaluator(
            evaluator_view(state), config.for_evaluator, client, trace, cycle
        )
        state.required_gap = evaluator_out.required_gap
        total_usage = total_usage + usage

        if not evaluator_out.acceptance:
            trace.evaluator_rejected(cycle, evaluator_out.required_gap or "")
            outcome = _gap_outcome(state.required_gap, prev_gap, cycle, TERMINATION_LIMIT)
            if outcome:
                state.verdict = Verdict.impasse
                if outcome == "no_progress":
                    no_progress = True
                    trace.no_progress_halt(cycle, state.required_gap or "")
                break
            prev_gap = state.required_gap
            continue

        resolver_out, usage = await run_resolver(
            resolver_view(state), config.for_resolver, client, trace, cycle
        )
        state.verdict = resolver_out.verdict
        state.rebuttal_log = state.rebuttal_log + resolver_out.rebuttal_log
        total_usage = total_usage + usage

        if state.verdict in (Verdict.survives, Verdict.impasse):
            break

    final_verdict = state.verdict or Verdict.impasse
    if not no_progress:
        trace.verdict_reached(state.cycle, final_verdict.value)

    print(
        f"    [{position}] verdict={final_verdict} "
        f"cycles={state.cycle} tokens={total_usage.total()}",
        file=sys.stderr,
    )

    return ClaimEvaluation(
        claim=state.claim,
        verdict=final_verdict,
        final_argument=_final_argument(state),
        issues=_issues(state),
        required_gap=state.required_gap,
        rebuttal_log=state.rebuttal_log,
        trace=trace.snapshot(),
        usage=total_usage,
    )


async def run_pipeline(
    request: EvaluateRequest,
    config: GauntletConfig,
    client: GauntletClient,
    prepared: PreparedEvaluationInput | None = None,
) -> GauntletResult:
    print("\n== GAUNTLET ==", file=sys.stderr)

    prepared_input = prepared or await prepare_evaluation_input(request.input, config, client)
    claim = prepared_input.claim
    grounds = prepared_input.grounds
    warrant = prepared_input.warrant
    backing = prepared_input.backing
    qualifier = prepared_input.qualifier
    domain_standard = prepared_input.domain_standard

    print(f"  claim: {claim[:80]}", file=sys.stderr)
    print(f"  domain: {domain_standard}", file=sys.stderr)

    contrary_claim, contrary_usage = await _generate_contrary(claim, config, client)
    print(f"  contrary: {contrary_claim[:80]}", file=sys.stderr)

    claim_eval = await run_claim_pipeline(
        claim=claim,
        domain_standard=domain_standard,
        qualifier=qualifier,
        config=config,
        client=client,
        position="claim",
        preflight_summary=_preflight_summary(
            claim=claim,
            grounds=grounds,
            warrant=warrant,
            backing=backing,
            domain_standard=domain_standard,
        ),
        preflight_usage=prepared_input.usage,
        initial_grounds=grounds,
        initial_warrant=warrant,
        initial_backing=backing,
    )

    contrary_eval = await run_claim_pipeline(
        claim=contrary_claim,
        domain_standard=domain_standard,
        qualifier="presumably",
        config=config,
        client=client,
        position="contrary",
        preflight_summary=_preflight_summary(
            claim=contrary_claim,
            domain_standard=domain_standard,
            generated_from=claim,
        ),
        preflight_usage=contrary_usage,
        initial_grounds=None,
        initial_warrant=None,
        initial_backing=None,
    )

    comparison = _compare(claim_eval.verdict, contrary_eval.verdict)
    recommended = _recommended(comparison, claim, contrary_claim)
    total_usage = claim_eval.usage + contrary_eval.usage

    print("\n== RESULT ==", file=sys.stderr)
    print(f"  claim     {claim_eval.verdict} / contrary {contrary_eval.verdict}", file=sys.stderr)
    print(f"  -> {comparison}", file=sys.stderr)
    if recommended:
        print(f"  recommended: {recommended[:80]}", file=sys.stderr)

    return GauntletResult(
        id=str(uuid.uuid4()),
        claim_evaluation=claim_eval,
        contrary_evaluation=contrary_eval,
        comparison=comparison,
        recommended_position=recommended,
        inferred_domain_standard=domain_standard,
        total_usage=total_usage,
    )
