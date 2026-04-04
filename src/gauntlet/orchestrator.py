"""
orchestrator.py — Bipolar argumentation pipeline.

WHAT THIS FILE IS:
  The entire "framework". No LangChain. No LangGraph. No NAT. No MTHDS.
  Two public functions: run_claim_pipeline() and run_pipeline().
  The rest is private helpers.

BIPOLAR DESIGN:
  Every evaluation runs the CLAIM and its CONTRARY independently.
  A claim that survives without its contrary failing produces only a plausible
  conclusion. A definite conclusion requires both.

  claim survives, contrary defeated  → definite_conclusion
  contrary survives, claim defeated  → wrong_starting_position
  both survive                       → equipoise
  neither survives                   → insufficient_evidence

BUGS FIXED VS PREVIOUS VERSION:
  1. Translation now runs after auditor blocks (gap is normalised before cycling)
  2. complete_text() usage is tracked and accumulated in total_usage
  3. No string-based 'label' conditional — two explicit call sites
  4. rebuttal_log gets entries from auditor violations when pipeline terminates
  5. TranslationDelta replaces silent mutation — trace records what changed
  6. BipolarComparison (typo fixed)
  7. GauntletConfig uses @property accessors (no __post_init__ hack)

TRACEABILITY:
  PipelineTrace receives events at every meaningful step. The full trace
  is included in ClaimEvaluation and returned to the caller via the API.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from gauntlet.agents.auditor     import run_auditor
from gauntlet.agents.classifier  import run_classifier
from gauntlet.agents.constructor import run_constructor
from gauntlet.agents.evaluator   import run_evaluator
from gauntlet.agents.resolver    import run_resolver
from gauntlet.client     import GauntletClient
from gauntlet.config     import GauntletConfig
from gauntlet.models     import (
    ArgumentUnit, AttackType, BipolarComparison,
    ClaimEvaluation, EvaluateRequest, GauntletResult,
    RebuttalEntry, RebuttalStatus, TokenUsage, Verdict,
    auditor_view, classifier_view, constructor_view,
    evaluator_view, resolver_view,
)
from gauntlet.trace      import EventKind, PipelineTrace
from gauntlet.translation import translate


# ── Contrary generation ───────────────────────────────────────────────────────

async def _generate_contrary(
    claim: str,
    config: GauntletConfig,
    client: GauntletClient,
) -> tuple[str, TokenUsage]:
    """
    Generate the logical contrary of a claim.

    The contrary is the most reasonable opposing position — not a strawman,
    but what a rational person might genuinely hold given the same situation.
    Uses the fast model: this is a linguistic task.
    """
    system = (
        "You generate the logical contrary of an argumentative claim. "
        "The contrary is the most reasonable opposing standpoint a rational person "
        "might hold given the same situation — not an exaggeration or strawman. "
        "Keep the same level of specificity as the original. "
        "Output only the contrary claim as a single sentence. No preamble."
    )
    try:
        text, usage = await client.complete_text(
            model=config.fast.model,
            system=system,
            user=f"Generate the logical contrary of: {claim}",
            max_tokens=120,
        )
        return text.strip() or f"do not {claim}", usage
    except Exception:
        return f"do not {claim}", TokenUsage()


# ── Bipolar comparison ────────────────────────────────────────────────────────

def _compare(
    claim_v: Verdict | None,
    contrary_v: Verdict | None,
) -> BipolarComparison:
    cs = claim_v    == Verdict.survives
    xs = contrary_v == Verdict.survives
    if cs and not xs: return BipolarComparison.definite_conclusion
    if xs and not cs: return BipolarComparison.wrong_starting_position
    if cs and xs:     return BipolarComparison.equipoise
    return BipolarComparison.insufficient_evidence


def _recommended(comp: BipolarComparison, claim: str, contrary: str) -> str | None:
    if comp == BipolarComparison.definite_conclusion:     return claim
    if comp == BipolarComparison.wrong_starting_position: return contrary
    return None


# ── No-progress detection ─────────────────────────────────────────────────────

def _no_progress(current: str | None, previous: str | None, cycle: int) -> bool:
    return cycle > 1 and current is not None and current == previous


# ── Timestamp helper ──────────────────────────────────────────────────────────

def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Single-claim pipeline ─────────────────────────────────────────────────────

async def run_claim_pipeline(
    claim: str,
    request: EvaluateRequest,
    config: GauntletConfig,
    client: GauntletClient,
    position: str,
    initial_grounds: list | None = None,
    initial_warrant: str | None = None,
    initial_backing: str | None = None,
) -> ClaimEvaluation:
    """
    Run the full five-agent pipeline for one position (claim or contrary).

    position:        "claim" or "contrary" — for trace labelling only
    initial_grounds: pre-provided grounds (claim position only, if given in request)
    initial_warrant: pre-provided warrant (claim position only)
    initial_backing: pre-provided backing (claim position only)

    The contrary pipeline always starts from scratch (no inherited grounds/warrant)
    to ensure independent evidential construction.
    """
    trace = PipelineTrace(position)
    trace.pipeline_start(claim, request.domain_standard, request.termination_limit)

    unit = ArgumentUnit(
        dialogue_type=request.dialogue_type,
        domain_standard=request.domain_standard,
        termination_limit=request.termination_limit,
        claim=claim,
        grounds=list(initial_grounds) if initial_grounds else [],
        warrant=initial_warrant,
        backing=initial_backing,
        qualifier=request.qualifier or "presumably",
    )

    total_usage = TokenUsage()
    no_progress = False
    prev_gap:   str | None = None

    print(f"\n  ── {position.upper()} pipeline ──", file=sys.stderr)

    for cycle in range(1, unit.termination_limit + 1):
        unit.cycle = cycle
        trace.cycle_start(cycle, unit.termination_limit)
        print(f"    cycle {cycle}/{unit.termination_limit}", file=sys.stderr)

        # ── Agent 0: Constructor ──────────────────────────────────────────────
        c_out, u = await run_constructor(
            constructor_view(unit), config.for_constructor, client, trace, cycle
        )
        unit.grounds   = c_out.grounds
        unit.warrant   = c_out.warrant
        unit.backing   = c_out.backing
        unit.qualifier = c_out.qualifier
        total_usage    = total_usage + u

        # Translation after Constructor
        unit, delta = await translate(unit, client, config.fast)
        total_usage  = total_usage + delta.usage
        trace.translation_applied(
            cycle=cycle,
            qualifier_before=delta.qualifier_before,
            qualifier_after=delta.qualifier_after,
            grounds_reordered=delta.grounds_reordered,
            warrant_rewritten=delta.warrant_rewritten,
            attacks_neutralised=delta.attacks_neutralised,
            gap_normalised=delta.gap_normalised,
            tokens=delta.usage,
        )

        # ── Agent 1: Classifier ───────────────────────────────────────────────
        cl_out, u = await run_classifier(
            classifier_view(unit), config.for_classifier, client, trace, cycle
        )
        unit.scheme             = cl_out.scheme
        unit.critical_questions = cl_out.critical_questions
        unit.open_attacks       = cl_out.open_attacks
        unit.burden_bearer      = cl_out.burden_bearer
        total_usage             = total_usage + u

        # Translation after Classifier
        unit, delta = await translate(unit, client, config.fast)
        total_usage  = total_usage + delta.usage
        trace.translation_applied(
            cycle=cycle,
            qualifier_before=delta.qualifier_before,
            qualifier_after=delta.qualifier_after,
            grounds_reordered=delta.grounds_reordered,
            warrant_rewritten=delta.warrant_rewritten,
            attacks_neutralised=delta.attacks_neutralised,
            gap_normalised=delta.gap_normalised,
            tokens=delta.usage,
        )

        # ── Agent 2: Exchange Auditor ─────────────────────────────────────────
        a_out, u = await run_auditor(
            auditor_view(unit), config.for_auditor, client, trace, cycle
        )
        unit.stage_audit     = a_out.stage_audit
        unit.rule_violations = a_out.rule_violations
        total_usage          = total_usage + u

        if a_out.stage_audit.blocked:
            unit.acceptance_gap = a_out.acceptance_gap
            unit.acceptance     = False

            # ── FIX: translate the gap BEFORE cycling back ────────────────────
            # Without this, the Constructor receives a criticism-framed gap
            # and its myside bias rationalises rather than retrieves.
            unit, delta = await translate(unit, client, config.fast)
            total_usage  = total_usage + delta.usage
            trace.translation_applied(
                cycle=cycle,
                qualifier_before=delta.qualifier_before,
                qualifier_after=delta.qualifier_after,
                grounds_reordered=delta.grounds_reordered,
                warrant_rewritten=delta.warrant_rewritten,
                attacks_neutralised=delta.attacks_neutralised,
                gap_normalised=delta.gap_normalised,
                tokens=delta.usage,
            )

            trace.auditor_blocked(
                cycle=cycle,
                rule=a_out.rule_violations[0].rule if a_out.rule_violations else "unknown",
                stage=a_out.rule_violations[0].stage if a_out.rule_violations else "unknown",
                gap=unit.acceptance_gap or "",
            )

            if _no_progress(unit.acceptance_gap, prev_gap, cycle):
                no_progress  = True
                unit.verdict = Verdict.impasse
                trace.no_progress_halt(cycle, unit.acceptance_gap or "")
                # Record auditor violations in rebuttal_log before terminating
                unit.rebuttal_log = unit.rebuttal_log + [
                    RebuttalEntry(
                        timestamp=_ts(),
                        agent="auditor",
                        attack_type=AttackType.rebuttal,
                        content=v.description,
                        status=RebuttalStatus.surviving,
                    )
                    for v in a_out.rule_violations if v.severity.value == "blocking"
                ]
                break

            prev_gap = unit.acceptance_gap
            if cycle == unit.termination_limit:
                unit.verdict = Verdict.impasse
                unit.rebuttal_log = unit.rebuttal_log + [
                    RebuttalEntry(
                        timestamp=_ts(),
                        agent="auditor",
                        attack_type=AttackType.rebuttal,
                        content=v.description,
                        status=RebuttalStatus.surviving,
                    )
                    for v in a_out.rule_violations if v.severity.value == "blocking"
                ]
            continue

        # Translation after Auditor (only if not blocked)
        unit, delta = await translate(unit, client, config.fast)
        total_usage  = total_usage + delta.usage
        trace.translation_applied(
            cycle=cycle,
            qualifier_before=delta.qualifier_before,
            qualifier_after=delta.qualifier_after,
            grounds_reordered=delta.grounds_reordered,
            warrant_rewritten=delta.warrant_rewritten,
            attacks_neutralised=delta.attacks_neutralised,
            gap_normalised=delta.gap_normalised,
            tokens=delta.usage,
        )

        # ── Agent 3: Acceptance Evaluator ─────────────────────────────────────
        e_out, u = await run_evaluator(
            evaluator_view(unit), config.for_evaluator, client, trace, cycle
        )
        unit.acceptance     = e_out.acceptance
        unit.acceptance_gap = e_out.acceptance_gap
        total_usage         = total_usage + u

        if not e_out.acceptance:
            trace.evaluator_rejected(cycle, e_out.acceptance_gap or "")

            # Translate gap before cycling back
            unit, delta = await translate(unit, client, config.fast)
            total_usage  = total_usage + delta.usage
            trace.translation_applied(
                cycle=cycle,
                qualifier_before=delta.qualifier_before,
                qualifier_after=delta.qualifier_after,
                grounds_reordered=delta.grounds_reordered,
                warrant_rewritten=delta.warrant_rewritten,
                attacks_neutralised=delta.attacks_neutralised,
                gap_normalised=delta.gap_normalised,
                tokens=delta.usage,
            )

            if _no_progress(unit.acceptance_gap, prev_gap, cycle):
                no_progress  = True
                unit.verdict = Verdict.impasse
                trace.no_progress_halt(cycle, unit.acceptance_gap or "")
                break

            prev_gap = unit.acceptance_gap
            if cycle == unit.termination_limit:
                unit.verdict = Verdict.impasse
            continue

        # Translation after Evaluator (only if accepted)
        unit, delta = await translate(unit, client, config.fast)
        total_usage  = total_usage + delta.usage
        trace.translation_applied(
            cycle=cycle,
            qualifier_before=delta.qualifier_before,
            qualifier_after=delta.qualifier_after,
            grounds_reordered=delta.grounds_reordered,
            warrant_rewritten=delta.warrant_rewritten,
            attacks_neutralised=delta.attacks_neutralised,
            gap_normalised=delta.gap_normalised,
            tokens=delta.usage,
        )

        # ── Agent 4: Conflict Resolver ─────────────────────────────────────────
        r_out, u = await run_resolver(
            resolver_view(unit), config.for_resolver, client, trace, cycle
        )
        unit.attack_graph = r_out.attack_graph
        unit.extension    = r_out.extension
        unit.verdict      = r_out.verdict
        unit.rebuttal_log = unit.rebuttal_log + r_out.rebuttal_log
        total_usage       = total_usage + u

        if unit.verdict in (Verdict.survives, Verdict.impasse):
            break
        # defeated → next cycle

    unit.usage = total_usage
    final_verdict = unit.verdict or Verdict.impasse

    print(
        f"    [{position}] verdict={final_verdict} "
        f"cycles={unit.cycle} tokens={total_usage.total()}",
        file=sys.stderr,
    )

    return ClaimEvaluation(
        claim=unit.claim,
        verdict=final_verdict,
        qualifier=unit.qualifier,
        acceptance_gap=unit.acceptance_gap,
        rebuttal_log=unit.rebuttal_log,
        cycles_run=unit.cycle,
        no_progress=no_progress,
        usage=total_usage,
        argument_unit=unit,
    )


# ── Public: bipolar pipeline ──────────────────────────────────────────────────

async def run_pipeline(
    request: EvaluateRequest,
    config: GauntletConfig,
    client: GauntletClient,
) -> GauntletResult:
    """
    Run the full bipolar argumentation pipeline.

    Step 1: Generate the logical contrary of the claim.
    Step 2: Run the claim through the full five-agent sequence.
    Step 3: Run the contrary through the identical sequence (independent grounds).
    Step 4: Compare both verdicts to produce a BipolarComparison.

    The two pipelines are intentionally sequential (not parallel) to keep
    token costs and server load predictable and debuggable.
    """
    print(f"\n══ GAUNTLET ══", file=sys.stderr)
    print(f"  claim: {request.claim[:80]}", file=sys.stderr)

    # Step 1: Generate contrary
    contrary_claim, contrary_gen_usage = await _generate_contrary(request.claim, config, client)
    print(f"  contrary: {contrary_claim[:80]}", file=sys.stderr)

    # Step 2: Claim pipeline
    claim_eval = await run_claim_pipeline(
        claim=request.claim,
        request=request,
        config=config,
        client=client,
        position="claim",
        initial_grounds=request.grounds,
        initial_warrant=request.warrant,
        initial_backing=request.backing,
    )

    # Step 3: Contrary pipeline (no inherited grounds/warrant — independent construction)
    contrary_eval = await run_claim_pipeline(
        claim=contrary_claim,
        request=request,   # same dialogue_type, domain_standard, termination_limit
        config=config,
        client=client,
        position="contrary",
        initial_grounds=None,
        initial_warrant=None,
        initial_backing=None,
    )

    # Step 4: Compare
    comparison   = _compare(claim_eval.verdict, contrary_eval.verdict)
    recommended  = _recommended(comparison, request.claim, contrary_claim)

    print(f"\n══ RESULT ══", file=sys.stderr)
    print(f"  claim     {claim_eval.verdict}  /  contrary {contrary_eval.verdict}", file=sys.stderr)
    print(f"  → {comparison}", file=sys.stderr)
    if recommended:
        print(f"  recommended: {recommended[:80]}", file=sys.stderr)

    total = claim_eval.usage + contrary_eval.usage + contrary_gen_usage

    return GauntletResult(
        id=claim_eval.argument_unit.id,
        claim_evaluation=claim_eval,
        contrary_evaluation=contrary_eval,
        comparison=comparison,
        recommended_position=recommended,
        total_usage=total,
    )
