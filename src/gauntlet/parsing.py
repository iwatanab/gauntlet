"""
parsing.py - Preflight atomic-claim validation and Toulmin decomposition.

A single preflight-model call simultaneously validates atomicity and extracts
the Toulmin components already present in the user's string input.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig
from gauntlet.models import Ground, TokenUsage


class ParsedInput(BaseModel):
    valid:          bool
    invalid_reason: Optional[str] = None
    atomic:         bool
    claims:         list[str]
    claim:          Optional[str] = None
    grounds:        Optional[list[str]] = None
    warrant:        Optional[str] = None
    backing:        Optional[str] = None
    qualifier:      Optional[str] = None


class InputError(Exception):
    def __init__(self, code: str, message: str, claims: list[str] | None = None):
        self.code = code
        self.message = message
        self.claims = claims
        super().__init__(message)


_SYSTEM = """\
You process input for a Toulmin-style argumentation evaluation system. Analyse the text and return JSON.

Definitions:
- A claim is the standpoint or conclusion being advanced for evaluation: the proposition the argument is trying to justify.
- A claim is atomic only if it asserts one decision or one state of affairs. If the text advances multiple decisions,
  multiple conclusions, a conjunction, a disjunction, or a conditional chain that should be evaluated separately,
  then it contains multiple atomic claims.
- Grounds are user-provided evidence and may contain private facts that are not publicly verifiable. Extract them verbatim.
- Warrant is the inferential bridge from grounds to claim.
- Backing is the authority, rule, protocol, or source that licenses the warrant.

Fields:
- valid (bool): does the text contain a testable argumentative claim? Questions, pure facts, and descriptions are not claims.
- invalid_reason (string|null): if not valid, one sentence explaining why; else null
- atomic (bool): does the text contain exactly one atomic claim?
- claims (array): all identified atomic claims (one element if atomic; multiple if not; empty if not valid)
- claim (string|null): the single claim if valid + atomic, else null
- grounds (array|null): evidence strings such as measurements, observations, records, or established facts. Extract verbatim.
- warrant (string|null): the inferential rule linking grounds to claim, if explicitly stated
- backing (string|null): authoritative support for the warrant, if explicitly stated
- qualifier (string|null): epistemic hedging word if present (possibly/presumably/probably/almost certainly)

Atomic-claim examples:
- Atomic: "We should discharge this patient."
- Not atomic: "We should discharge this patient and stop serial troponins."
- Not atomic: "If we cannot discharge this patient, we should admit them and cancel tomorrow's surgery."

Output JSON only. No preamble."""


async def check_and_parse(
    text: str,
    config: AgentConfig,
    client: GauntletClient,
) -> tuple[ParsedInput, TokenUsage]:
    result, _messages, usage = await client.complete_structured(
        model=config.model,
        system=_SYSTEM,
        messages=[{"role": "user", "content": text}],
        output_type=ParsedInput,
        max_tokens=config.max_tokens,
        retries=config.retries,
        tools=None,
    )

    if result is None:
        raise InputError(
            code="no_claim",
            message="Could not parse the input. Please provide a single deliberative claim.",
        )

    if not result.valid:
        reason = result.invalid_reason or "Input does not contain a testable argumentative claim."
        raise InputError(code="no_claim", message=reason, claims=result.claims or [])

    if not result.atomic:
        count = len(result.claims)
        raise InputError(
            code="multiple_claims",
            message=(
                f"Process will not continue: the input contains {count} atomic claims. "
                "Provide exactly one atomic claim."
            ),
            claims=result.claims,
        )

    return result, usage


def grounds_from_parsed(raw_grounds: list[str] | None) -> list[Ground]:
    """Convert verbatim user grounds into trusted Ground objects."""
    if not raw_grounds:
        return []
    return [
        Ground(
            content=g,
            source="user-provided",
            user_provided=True,
        )
        for g in raw_grounds
        if g.strip()
    ]
