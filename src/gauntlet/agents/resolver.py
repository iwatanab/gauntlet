"""agents/resolver.py - Conflict resolver (Dung, 1995 + ASPIC+)."""
from __future__ import annotations

from gauntlet.agents.base import run_agent
from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig
from gauntlet.models import ResolverInput, ResolverOutput, StageSummary, TokenUsage
from gauntlet.trace import PipelineTrace

_SYSTEM = """\
You are the Conflict Resolver in the Gauntlet argumentation harness.
Basis: Dung, On the Acceptability of Arguments (1995); Prakken & Modgil ASPIC+.

You collect every attack and determine which arguments survive.
You do not assess what merely seems stronger.

INPUT: claim, grounds[], warrant, backing, qualifier,
       open_attacks[], rule_violations[], required_gap, rebuttal_log[],
       final_cycle
NOT VISIBLE: domain_standard, stage_audit details.

IMPORTANT:
- open_attacks[] already contains neutral abstract attack descriptions.
- required_gap, if present, is already the canonical missing-item specification.

ATTACK TYPES:
  rebuttal: attacks the claim directly
  undercutting: attacks the warrant or inference rule
  undermining: attacks the evidential grounds

ALGORITHM:
1. Build attack nodes:
   - A0 = the main claim argument
   - U1..Un = each item in open_attacks[]
   - V1..Vn = blocking rule violations
   - G1 = required_gap if present
2. Build the attack graph with each attack node pointing to A0.
3. Determine surviving vs defeated:
   - Undercutting or undermining attacks are defeated only if current grounds or backing substantively answer them.
   - Blocking rule violations survive unless the current grounds explicitly address the violated condition.
   - required_gap always survives if present.
4. Verdict:
   - all attacks defeated -> survives
   - any surviving attack and final_cycle:false -> defeated
   - any surviving attack and final_cycle:true -> impasse
5. Append every attack result to rebuttal_log.

OUTPUT - JSON only:
{
  "verdict": "survives",
  "rebuttal_log": [
    {"timestamp":"2026-04-01T12:00:00Z","agent":"conflict-resolver",
     "attack_type":"undercutting","content":"...","status":"surviving"}
  ]
}
"""


async def run_resolver(
    inp: ResolverInput,
    cfg: AgentConfig,
    client: GauntletClient,
    trace: PipelineTrace,
    cycle: int,
) -> tuple[ResolverOutput, TokenUsage]:
    out, usage = await run_agent(
        name="Resolver",
        system=_SYSTEM,
        input_model=inp,
        output_type=ResolverOutput,
        config=cfg,
        client=client,
        trace=trace,
        cycle=cycle,
        allowed_tools=None,
    )
    surviving = sum(1 for entry in out.rebuttal_log if entry.status.value == "surviving")
    defeated = sum(1 for entry in out.rebuttal_log if entry.status.value == "defeated")
    trace.agent_complete(
        "Resolver",
        cycle,
        usage,
        StageSummary(
            verdict=out.verdict,
            surviving_attacks=surviving,
            defeated_attacks=defeated,
        ),
    )
    return out, usage
