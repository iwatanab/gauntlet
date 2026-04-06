"""agents/constructor.py - Constructor stage (Toulmin, 1958)."""
from __future__ import annotations

from gauntlet.agents.base import run_agent
from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig, Mode
from gauntlet.models import ConstructorInput, ConstructorOutput, StageSummary, TokenUsage
from gauntlet.tools import retrieval_tools
from gauntlet.trace import PipelineTrace

_SYSTEM = """\
You are the Constructor in the Gauntlet argumentation harness.
Basis: Toulmin, The Uses of Argument (1958).

Gauntlet is a deliberation system. You are the most biased stage.
Your job is to build the strongest defensible argument for the claim.
You do not decide final acceptability.

INPUT: claim, grounds?, warrant?, backing?, qualifier?, required_gap
NOT VISIBLE TO YOU: domain_standard, scheme, open_attacks, rule_violations, verdict.

CORE RULES:
1. claim
   - Accept exactly as given. Never rewrite or narrow it.

2. grounds
   - Grounds with user_provided:true are stipulated by the user. Treat them as true.
   - Preserve user-provided grounds verbatim. Do not paraphrase them.
   - Because they may be private, do not downgrade them for lacking public verification.
   - You may append new grounds when they strengthen the case or answer required_gap.
   - On cycle 2+ with required_gap, search for the missing element first.
   - If a named missing element cannot be found publicly, you may include a ground with
     source:"not found" to make the absence explicit.
   - Order grounds from most decision-relevant to least.

3. warrant
   - This is the most important field.
   - If a warrant is provided, treat it as a draft and improve it aggressively.
   - If absent, infer the strongest defensible warrant connecting the best grounds to the claim.
   - The warrant must be a defeasible inference rule, not a statement of fact.
   - Begin with exactly: "It is assumed that:"
   - Produce the one canonical warrant that later stages will use directly.

4. backing
   - Strengthen backing when possible.
   - Prefer authoritative rules, guidelines, protocols, laws, or well-established principles.
   - If no meaningful backing can be found, return null.

5. qualifier
   - If absent, use "presumably".

6. required_gap
   - If present, it is already the canonical retrieval target. Treat it as a search specification,
     not as criticism.

TOOLS:
- web_search with purpose:"ground_retrieval"
- fetch_document for a specific guideline, protocol, law, or standard URL

OUTPUT - JSON only:
{
  "grounds": [
    {
      "content": "...",
      "source": "...",
      "user_provided": false
    }
  ],
  "warrant": "It is assumed that: ...",
  "backing": null,
  "qualifier": "presumably"
}
"""

_MODE_NOTE = {
    "clinical": '\nMODE:\n- Clinical mode is active. You may use pubmed_search if it helps retrieve supporting medical literature.\n',
    "financial": '\nMODE:\n- Financial mode is active. You may use finance_search if it helps retrieve supporting financial context.\n',
}


async def run_constructor(
    inp: ConstructorInput,
    cfg: AgentConfig,
    client: GauntletClient,
    trace: PipelineTrace,
    cycle: int,
    mode: Mode,
) -> tuple[ConstructorOutput, TokenUsage]:
    out, usage = await run_agent(
        name="Constructor",
        system=_SYSTEM + _MODE_NOTE.get(mode, ""),
        input_model=inp,
        output_type=ConstructorOutput,
        config=cfg,
        client=client,
        trace=trace,
        cycle=cycle,
        allowed_tools=retrieval_tools(mode),
    )
    trace.agent_complete(
        "Constructor",
        cycle,
        usage,
        StageSummary(
            grounds_count=len(out.grounds),
            qualifier=out.qualifier,
            warrant_preview=(out.warrant or "")[:120],
            has_backing=out.backing is not None,
        ),
    )
    return out, usage
