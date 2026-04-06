"""agents/evaluator.py - Acceptance evaluator (Perelman & Olbrechts-Tyteca, 1958)."""
from __future__ import annotations

from gauntlet.agents.base import run_agent
from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig, Mode
from gauntlet.models import EvaluatorInput, EvaluatorOutput, StageSummary, TokenUsage
from gauntlet.tools import retrieval_tools
from gauntlet.trace import PipelineTrace

_SYSTEM = """\
You are the Acceptance Evaluator in the Gauntlet argumentation harness.
Basis: Perelman & Olbrechts-Tyteca, The New Rhetoric (1958).

You apply the universal audience standard.
You are the only stage that sees domain_standard.
Procedural correctness does not guarantee acceptance.

INPUT: claim, grounds[], warrant, backing, qualifier,
       domain_standard, stage_audit, rule_violations[]
NOT VISIBLE: open_attacks, rebuttal_log, verdict.

PROCESS:
1. Construct the relevant universal audience from domain_standard.
2. Decide whether that audience would act on this argument as currently constructed.
3. If yes, return acceptance:true and required_gap:null.
4. If no, required_gap must:
   - begin with exactly "Required:"
   - state the exact evidence, measurement, comparison, or standard needed
   - remain neutral and actionable

TOOLS:
- web_search and fetch_document only for current standards or protocols
- do not use tools for case-specific evidence

CALIBRATION:
BAD required_gap: "The argument lacks sufficient evidence"
GOOD required_gap: "Required: troponin result at T+0 under the relevant chest pain rule-out protocol."

OUTPUT - JSON only:
{
  "acceptance": true,
  "required_gap": null
}
"""

_MODE_NOTE = {
    "clinical": '\nMODE:\n- Clinical mode is active. You may use pubmed_search if it helps establish current medical standards.\n',
    "financial": '\nMODE:\n- Financial mode is active. You may use finance_search if it helps establish current financial standards or benchmarks.\n',
}


async def run_evaluator(
    inp: EvaluatorInput,
    cfg: AgentConfig,
    client: GauntletClient,
    trace: PipelineTrace,
    cycle: int,
    mode: Mode,
) -> tuple[EvaluatorOutput, TokenUsage]:
    out, usage = await run_agent(
        name="Evaluator",
        system=_SYSTEM + _MODE_NOTE.get(mode, ""),
        input_model=inp,
        output_type=EvaluatorOutput,
        config=cfg,
        client=client,
        trace=trace,
        cycle=cycle,
        allowed_tools=retrieval_tools(mode),
    )
    trace.agent_complete(
        "Evaluator",
        cycle,
        usage,
        StageSummary(
            accepted=out.acceptance,
            required_gap=(out.required_gap or "")[:120] or None,
        ),
    )
    return out, usage
