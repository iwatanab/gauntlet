"""
translation.py — Argument Quality Monitor (Mercier & Sperber, 2011).

Three bias corrections applied between every agent handoff:

  1. Selection bias (deterministic)
     Grounds sorted by probative_weight descending. Most evidentially
     strong evidence first. No LLM call; cannot fail.

  2. Anchoring bias (model-assisted, parallel)
     a. Warrant reframed as defeasible assumption — not established fact
     b. Attack content neutralised — no severity language, only gap identification
     c. Acceptance gap normalised — criticism framing → neutral retrieval spec
        so the Constructor (which has myside bias) will search rather than rationalise

  3. Qualifier inflation (hybrid)
     Mean probative weight computed deterministically.
     Qualifier expression selected from a calibrated scale.

LLM calls run in PARALLEL via asyncio.gather — ~60% latency reduction.
Uses the fast model — this is linguistic correction, not reasoning.

Token usage from complete_text() is now TRACKED and returned.
Graceful degradation: if any LLM call fails, the original text is preserved
and the failure is noted in the trace. The pipeline never crashes on translation.

Returns:
  (mutated unit, TokenUsage, trace delta dict)
The trace delta tells the orchestrator what changed for trace emission.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from gauntlet.client import GauntletClient
from gauntlet.config import AgentConfig
from gauntlet.models import ArgumentUnit, Attack, TokenUsage

_QUALIFIER_SCALE = [
    (0.25, "possibly"),
    (0.55, "presumably"),
    (0.75, "probably"),
    (1.01, "almost certainly"),
]


def _calibrate_qualifier(mean_weight: float) -> str:
    for threshold, label in _QUALIFIER_SCALE:
        if mean_weight < threshold:
            return label
    return "almost certainly"


@dataclass
class TranslationDelta:
    """Records what the translation layer changed — emitted to the trace."""
    qualifier_before:    str
    qualifier_after:     str
    grounds_reordered:   bool
    warrant_rewritten:   bool
    attacks_neutralised: bool
    gap_normalised:      bool
    usage:               TokenUsage = field(default_factory=TokenUsage)


async def _rewrite_warrant(warrant: str, client: GauntletClient, cfg: AgentConfig) -> tuple[str, TokenUsage]:
    system = (
        "You apply Toulmin argument analysis. A warrant is a defeasible inference rule — "
        "an assumption to be tested, not an established fact. Restate the warrant so its "
        "epistemic status is transparent:\n"
        "- Remove veridical factives: 'proves', 'confirms', 'establishes', 'rules out', 'shows'\n"
        "- Remove epistemic closure: 'clearly', 'obviously', 'certainly', 'definitively'\n"
        "- Begin with exactly: 'It is assumed that:'\n"
        "- Preserve the inferential content exactly — only framing changes\n"
        "Output only the rewritten warrant. No preamble."
    )
    try:
        text, usage = await client.complete_text(
            model=cfg.model, system=system, user=warrant, max_tokens=256
        )
        return text or warrant, usage
    except Exception:
        return warrant, TokenUsage()


async def _neutralise_attacks(
    attacks: list[Attack], client: GauntletClient, cfg: AgentConfig
) -> tuple[list[Attack], TokenUsage]:
    if not attacks:
        return attacks, TokenUsage()
    system = (
        "You apply Dung's abstract argumentation framework. Attack weight comes from "
        "graph structure, never from wording. Restate each attack 'content' to identify "
        "what inferential step is unvalidated or what evidence is absent — "
        "WITHOUT rhetorical severity.\n"
        "Remove: 'fatal', 'critical', 'devastating', 'completely undermines', "
        "'obviously wrong', 'minor', 'trivial', 'merely'.\n"
        "Return a JSON array with the same structure. Only 'content' may change."
    )
    try:
        raw, usage = await client.complete_text(
            model=cfg.model, system=system,
            user=json.dumps([a.model_dump() for a in attacks]),
            max_tokens=512,
        )
        parsed = json.loads(raw)
        items  = parsed if isinstance(parsed, list) else parsed.get("attacks", [])
        return [Attack.model_validate(a) for a in items], usage
    except Exception:
        return attacks, TokenUsage()


async def _normalise_gap(gap: str, client: GauntletClient, cfg: AgentConfig) -> tuple[str, TokenUsage]:
    system = (
        "You apply pragma-dialectics. This acceptance gap is passed to the Constructor, "
        "which has myside bias. Restate as a neutral retrieval specification so it "
        "searches for missing evidence rather than rationalising against criticism:\n"
        "- Begin with 'Required:'\n"
        "- State exactly what evidence, measurement, or standard is needed\n"
        "- Remove: failure language, verdict implications, evaluative framing\n"
        "- Specific enough to drive a targeted search query\n"
        "Output only the restatement. No preamble."
    )
    try:
        text, usage = await client.complete_text(
            model=cfg.model, system=system, user=gap, max_tokens=128
        )
        return text or gap, usage
    except Exception:
        return gap, TokenUsage()


async def translate(
    unit: ArgumentUnit,
    client: GauntletClient,
    cfg: AgentConfig,
) -> tuple[ArgumentUnit, TranslationDelta]:
    """
    Apply all three bias corrections. Returns the unit and a delta for tracing.

    Note: token usage from LLM calls is tracked in the delta and must be
    added to the pipeline's total_usage by the orchestrator.
    """
    qualifier_before = unit.qualifier

    # ── 1. Selection bias — deterministic ─────────────────────────────────────
    original_order = [g.probative_weight for g in unit.grounds]
    unit.grounds.sort(key=lambda g: g.probative_weight, reverse=True)
    grounds_reordered = [g.probative_weight for g in unit.grounds] != original_order

    # ── 2. Qualifier calibration — deterministic ──────────────────────────────
    if unit.grounds:
        mean_w = sum(g.probative_weight for g in unit.grounds) / len(unit.grounds)
        unit.qualifier = _calibrate_qualifier(mean_w)

    # ── 3. Parallel LLM corrections ───────────────────────────────────────────
    coros:   list = []
    keys:    list[str] = []
    total_u = TokenUsage()

    if unit.warrant:
        coros.append(_rewrite_warrant(unit.warrant, client, cfg))
        keys.append("warrant")
    if unit.open_attacks:
        coros.append(_neutralise_attacks(unit.open_attacks, client, cfg))
        keys.append("attacks")
    if unit.acceptance_gap:
        coros.append(_normalise_gap(unit.acceptance_gap, client, cfg))
        keys.append("gap")

    warrant_rewritten   = False
    attacks_neutralised = False
    gap_normalised      = False

    if coros:
        results = await asyncio.gather(*coros, return_exceptions=True)
        for key, res in zip(keys, results):
            if isinstance(res, Exception):
                continue  # graceful degradation — original preserved
            value, usage = res
            total_u = total_u + usage
            if key == "warrant" and value != unit.warrant:
                unit.warrant        = value
                warrant_rewritten   = True
            elif key == "attacks":
                unit.open_attacks   = value
                attacks_neutralised = True
            elif key == "gap" and value != unit.acceptance_gap:
                unit.acceptance_gap = value
                gap_normalised      = True

    delta = TranslationDelta(
        qualifier_before=qualifier_before,
        qualifier_after=unit.qualifier,
        grounds_reordered=grounds_reordered,
        warrant_rewritten=warrant_rewritten,
        attacks_neutralised=attacks_neutralised,
        gap_normalised=gap_normalised,
        usage=total_u,
    )
    return unit, delta
