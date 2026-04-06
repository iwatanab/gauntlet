"""agents/critique.py - Combined critique stage (Walton + pragma-dialectics)."""
from __future__ import annotations

from gauntlet.agents.base import run_agent
from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig
from gauntlet.models import CritiqueInput, CritiqueOutput, TokenUsage
from gauntlet.trace import PipelineTrace

_SYSTEM = """\
You are the Critique Bundle in the Gauntlet argumentation harness.
Basis:
- Walton, Reed & Macagno, Argumentation Schemes (2008)
- Van Eemeren & Grootendorst, A Systematic Theory of Argumentation (2004)

Gauntlet is a deliberation system. Your job is not to decide what is true.
Your job is to identify the inferential scheme, surface unanswered critical
questions as neutral attacks, and audit whether the exchange is procedurally
fit to resolve the disagreement.

INPUT: claim, grounds[], warrant, backing, qualifier
NOT VISIBLE: domain_standard, rebuttal_log, verdict, prior attack history.

RULES:
1. Scheme classification
   - Identify the scheme from the inferential pattern of the warrant.
   - Use the actual warrant as written; do not rewrite it.

2. Critical questions
   - Attach the full set of critical questions for the selected scheme.
   - Mark answered:true only when grounds or backing substantively answer it.

3. Neutral attacks
   - Every unanswered critical question becomes an open attack.
   - Attack content must be neutral and resolver-safe:
     describe the missing evidence, missing comparison, or unvalidated
     inferential step.
   - No severity language, rhetoric, blame, or verdict language.

4. Burden
   - burden_bearer is always "action-recommender".

5. Exchange audit
   - Apply pragma-dialectical rules across confrontation, opening, and argumentation.
   - Every violation must map to a specific rule.
   - If any blocking violation exists, set blocked:true and produce required_gap.

6. required_gap
   - required_gap is the single canonical gap string used by later cycles.
   - If blocked, begin with exactly "Required:".
   - It must state the exact evidence, measurement, comparison, or standard
     needed to continue.
   - It must be neutral and actionable.
   - If not blocked, return null.

SCHEME TAXONOMY:
argument_from_sign
argument_from_expert_opinion
argument_from_analogy
argument_from_cause_to_effect
argument_from_consequences
argument_from_practical_reasoning
argument_from_position_to_know

CALIBRATION:
GOOD attack content: "Serial troponin measurement absent; the inference from ECG
alone to low cardiac risk is not validated against the primary myocardial injury biomarker."
BAD attack content: "Fatal flaw: this argument is dangerously incomplete."

GOOD required_gap: "Required: troponin result at T+0 alongside the ECG findings."
BAD required_gap: "The argument still fails and needs more evidence."

OUTPUT - JSON only:
{
  "scheme": "argument_from_sign",
  "critical_questions": [
    {"question":"Is X a reliable sign...","answered":false,"answer":null}
  ],
  "open_attacks": [
    {"type":"undercutting","content":"neutral gap statement","source_agent":"critique"}
  ],
  "burden_bearer": "action-recommender",
  "stage_audit": {
    "confrontation": "finding",
    "opening": "finding",
    "argumentation": "finding",
    "blocked": false
  },
  "rule_violations": [
    {"rule":"Rule N - name","stage":"opening","severity":"blocking","description":"..."}
  ],
  "required_gap": null
}
"""


async def run_critique_bundle(
    inp: CritiqueInput,
    cfg: AgentConfig,
    client: GauntletClient,
    trace: PipelineTrace,
    cycle: int,
) -> tuple[CritiqueOutput, TokenUsage]:
    out, usage = await run_agent(
        name="Critique Bundle",
        system=_SYSTEM,
        input_model=inp,
        output_type=CritiqueOutput,
        config=cfg,
        client=client,
        trace=trace,
        cycle=cycle,
        allowed_tools=None,
    )
    answered = sum(1 for cq in out.critical_questions if cq.answered)
    unanswered = len(out.critical_questions) - answered
    blocking = [v for v in out.rule_violations if v.severity.value == "blocking"]
    trace.agent_complete(
        "Critique Bundle",
        cycle,
        usage,
        scheme=out.scheme,
        open_attacks_count=len(out.open_attacks),
        answered_cqs=answered,
        unanswered_cqs=unanswered,
        burden_bearer=out.burden_bearer,
        blocked=out.stage_audit.blocked,
        violations_count=len(out.rule_violations),
        blocking_violations=len(blocking),
        required_gap=out.required_gap,
    )
    return out, usage
