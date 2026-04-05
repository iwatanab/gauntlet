# Gauntlet

**Better decisions through rigorous argument.**

Gauntlet is a multi-agent argumentation harness exposed as a REST API. Submit a claim — a clinical recommendation, an architectural decision, a proposed action — and Gauntlet subjects it to a structured sequence of theoretical challenges, runs the logical contrary through the same gauntlet independently, and returns a justified comparative verdict with a full step-by-step trace of everything that happened.

A claim that survives without its contrary also failing produces only a *plausible* conclusion. Gauntlet produces *definite* conclusions — or tells you honestly why it cannot.

```
POST /v1/evaluate
{ "claim": "deprioritise this patient",
  "dialogue_type": "deliberation",
  "domain_standard": "experienced emergency clinician, NICE NG185" }

→ {
    "comparison": "wrong_starting_position",
    "recommended_position": "do not deprioritise this patient",
    "claim_evaluation":   { "verdict": "defeated", "acceptance_gap": "Required: troponin at T+0", ... },
    "contrary_evaluation": { "verdict": "survives", ... },
    "claim_evaluation": { "trace": [ ... 24 timestamped events ... ] }
  }
```

---

## Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
  - [Bipolar Evaluation](#bipolar-evaluation)
  - [The Five Agents](#the-five-agents)
  - [The Translation Layer](#the-translation-layer)
  - [Field Isolation](#field-isolation)
  - [Cycle Logic and No-Progress Detection](#cycle-logic-and-no-progress-detection)
  - [The Pipeline Trace](#the-pipeline-trace)
- [API Reference](#api-reference)
- [Request and Response Schema](#request-and-response-schema)
- [The Trace](#the-trace)
- [Configuration](#configuration)
- [Changing Models](#changing-models)
- [Adding Tools](#adding-tools)
- [Running Tests](#running-tests)
- [Project Structure](#project-structure)
- [Design Decisions](#design-decisions)
- [Theoretical Foundations](#theoretical-foundations)

---

## Quick Start

**Requirements:** Python 3.11+, an [OpenRouter](https://openrouter.ai) API key, a [Tavily](https://tavily.com) API key.

```bash
# 1. Install
git clone https://github.com/your-org/gauntlet.git
cd gauntlet
uv sync

# 2. Configure
cp .env.example .env
# Set OPENROUTER_API_KEY and TAVILY_API_KEY in .env

# 3. Start
uv run python -m gauntlet
# → http://localhost:8000
# → http://localhost:8000/docs  (interactive API explorer)

# 4. Evaluate a claim
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "deprioritise this patient",
    "dialogue_type": "deliberation",
    "domain_standard": "experienced emergency clinician familiar with NICE NSTEMI NG185 troponin rule-out protocol",
    "termination_limit": 2
  }' | python -m json.tool
```

The `/docs` endpoint renders the full OpenAPI spec with a browser interface for testing every route.

---

## How It Works

### Bipolar Evaluation

Every evaluation runs **two independent pipelines**. The first evaluates the original claim. The second evaluates its logical contrary, generated automatically from the claim text. Both pipelines run against the same `domain_standard` and `termination_limit`. The contrary pipeline constructs its own evidential basis from scratch — it does not inherit any grounds or warrant from the claim pipeline.

```
claim: "deprioritise this patient"
contrary (auto-generated): "do not deprioritise this patient"

Claim pipeline  →  defeated  (troponin not measured)
Contrary pipeline →  survives  (same standard applied independently)

Comparison: wrong_starting_position
Recommended: "do not deprioritise this patient"
```

The four possible outcomes:

| Comparison | Meaning |
|---|---|
| `definite_conclusion` | Claim survives; contrary defeated. Evidence genuinely favours the claim. |
| `wrong_starting_position` | Contrary survives; claim defeated. You started from the wrong position. |
| `equipoise` | Both survive. Genuine evidential balance — the decision cannot be justified from available evidence alone. |
| `insufficient_evidence` | Neither survives. More data is needed before any position can be justified. |

Only `definite_conclusion` produces a verdict the system can stand behind. The others are honest records of why justification failed.

---

### The Five Agents

Five specialist LLM agents run in sequence. Each receives only the fields it is permitted to see — structural field isolation, not instructional. The orchestrator builds typed Pydantic projections from the shared `ArgumentUnit`; agents never touch the full object.

**Agent 0 — Constructor** *(Toulmin, 1958)*

The most biased agent. Holds the claim and builds its evidential basis. Retrieves grounds via web search if none are provided. Surfaces the implicit warrant — the inferential link from grounds to claim, stated as a defeasible assumption rather than an established fact. On subsequent cycles, receives the `acceptance_gap` from the previous cycle as a neutral retrieval specification and searches specifically for the missing element.

*Has web search. Does not evaluate.*

**Agent 1 — Classifier** *(Walton, 1989–2020)*

Names the inferential scheme the warrant instantiates from Walton's taxonomy (argument from sign, from expert opinion, from analogy, from cause to effect, from consequences, from practical reasoning, from position to know). Attaches the complete set of critical questions for that scheme. Marks each CQ as answered or unanswered based on the existing grounds and backing. Unanswered CQs become undercutting attack vectors.

*No tools. Evaluates structure, not truth.*

**Agent 2 — Exchange Auditor** *(Van Eemeren & Grootendorst, 2004)*

Checks whether the exchange is structured fairly enough to resolve the disagreement under pragma-dialectics. Applies the ten rules across four stages: confrontation, opening, argumentation, concluding. A blocking violation returns an `acceptance_gap` and the pipeline cycles back to the Constructor. Notable: Rule 2 requires that the cost of the recommended action be placed on the table alongside the cited risk — one-sided risk framing without cost framing is a blocking violation.

*No tools. Evaluates process, not content.*

**Agent 3 — Acceptance Evaluator** *(Perelman & Olbrechts-Tyteca, 1958)*

The only agent that sees `domain_standard`. Applies the universal audience standard: would a reasonable, well-informed expert in this domain act on this argument as currently constructed? Uses web search to verify what the current authoritative standard actually requires — not to find case evidence, only to establish the evidential threshold. If the argument fails, returns a specific, actionable `acceptance_gap` identifying exactly what is missing.

*Has web search. The only agent that sees domain_standard.*

**Agent 4 — Conflict Resolver** *(Dung, 1995 + ASPIC+)*

Collects every attack produced through the exchange. Classifies each as rebuttal (attacks the claim), undercutting (attacks the warrant), or undermining (attacks the grounds). Builds the attack graph, computes the preferred extension, applies reinstatement. An attack that was surviving in cycle 1 but is addressed by new grounds in cycle 2 is marked defeated — the claim is reinstated with respect to that attack.

*No tools. Computes, does not assess.*

---

### The Translation Layer

Between every agent handoff, three bias corrections are applied. These run before the next agent receives the ArgumentUnit.

**Selection bias correction** (deterministic): grounds are sorted by `probative_weight` descending. The most evidentially strong evidence appears first. No LLM call, no failure mode.

**Anchoring bias correction** (model-assisted, parallel): the warrant is reframed as a defeasible assumption if it contains veridical language ("proves", "confirms", "establishes"). Open attacks are restated as neutral evidential gaps — their weight in Dung's framework comes from graph structure, not from how forcefully they are worded. The acceptance gap is reframed from criticism-language to a neutral retrieval specification, so the Constructor searches for missing evidence rather than rationalising against a perceived attack.

**Qualifier inflation correction** (hybrid): the mean probative weight of the grounds is computed deterministically. The qualifier is then calibrated to match:

| Mean weight | Qualifier |
|---|---|
| < 0.25 | possibly |
| 0.25 – 0.55 | presumably |
| 0.55 – 0.75 | probably |
| > 0.75 | almost certainly |

The three LLM calls (warrant rewrite, attacks neutralise, gap normalise) run in parallel via `asyncio.gather`. If any fails, the original text is preserved — graceful degradation, never a crash. Token usage from translation is tracked and included in `total_usage`.

---

### Field Isolation

Each agent receives a typed Pydantic model containing only its designated fields. The orchestrator constructs these views; agents never touch the full `ArgumentUnit`. This is structural isolation — the field does not exist in the model the agent receives.

| Agent | Cannot see |
|---|---|
| Constructor | `domain_standard`, `scheme`, `stage_audit`, `acceptance`, `verdict` |
| Classifier | `domain_standard`, `rebuttal_log`, `acceptance`, `verdict` |
| Auditor | `domain_standard`, `acceptance`, `verdict`, `rebuttal_log` |
| Evaluator | `dialogue_type`, `open_attacks`, `rebuttal_log`, `verdict` |
| Resolver | `domain_standard`, `dialogue_type`, `scheme`, `stage_audit` |

The Evaluator is the only agent that sees `domain_standard`. It cannot be told the standard by the claim or the prior agents — it receives it exclusively from the initialisation input. This independence is what makes its verdict meaningful.

---

### Cycle Logic and No-Progress Detection

```
for cycle in 1..termination_limit:

    Constructor → translate
    Classifier  → translate
    Auditor
      if blocked:
        translate (gap normalisation)  ← critical: runs even on blocking path
        if no_progress: verdict = impasse, stop
        else: continue to next cycle

    translate
    Evaluator
      if rejected:
        translate (gap normalisation)
        if no_progress: verdict = impasse, stop
        else: continue to next cycle

    translate
    Resolver
      survives → stop
      impasse  → stop
      defeated → next cycle (if available)
```

**No-progress detection**: if the `acceptance_gap` is identical across two consecutive cycles, the Constructor cannot retrieve the missing evidence — it is unavailable. The pipeline terminates with `verdict: impasse` rather than repeating uselessly. The repeated gap is recorded in the trace.

**Translation on blocking path**: the acceptance gap from a blocked auditor is translated through the gap normaliser before cycling back. Without this, the Constructor (which has myside bias) receives a criticism-framed gap and rationalises rather than retrieves. This was a bug in the previous version.

**Rebuttal log completeness**: when the auditor blocks and the pipeline terminates (last cycle or no-progress), the blocking rule violations are appended to `rebuttal_log` as surviving attacks. Previously they disappeared without trace.

---

### The Pipeline Trace

Every meaningful step emits a `TraceEvent`. The full trace is returned in the API response as part of each `ClaimEvaluation`. Users can reconstruct exactly why the verdict was reached.

```json
{
  "claim_evaluation": {
    "verdict": "defeated",
    "trace": [
      {
        "ts": "2026-04-01T14:23:01.412Z",
        "kind": "pipeline_start",
        "position": "claim",
        "cycle": 0,
        "detail": { "claim": "deprioritise this patient", "termination_limit": 3 }
      },
      {
        "ts": "2026-04-01T14:23:02.811Z",
        "kind": "agent_complete",
        "position": "claim",
        "cycle": 1,
        "tokens": { "input_tokens": 1840, "output_tokens": 612 },
        "detail": {
          "agent": "Constructor",
          "grounds_count": 3,
          "qualifier": "presumably",
          "warrant_preview": "It is assumed that: negative ECG and age profile indicate..."
        }
      },
      {
        "ts": "2026-04-01T14:23:04.119Z",
        "kind": "tool_called",
        "position": "claim",
        "cycle": 1,
        "detail": {
          "agent": "Constructor",
          "tool": "web_search",
          "query": "NICE NG185 troponin rule-out protocol",
          "result_chars": 892,
          "result_preview": "NICE guideline NG185 recommends..."
        }
      },
      {
        "ts": "2026-04-01T14:23:06.204Z",
        "kind": "agent_complete",
        "position": "claim",
        "cycle": 1,
        "detail": {
          "agent": "Classifier",
          "scheme": "argument_from_sign",
          "open_attacks_count": 2,
          "answered_cqs": 1,
          "unanswered_cqs": 2,
          "burden_bearer": "action-recommender"
        }
      },
      {
        "ts": "2026-04-01T14:23:08.509Z",
        "kind": "translation_applied",
        "position": "claim",
        "cycle": 1,
        "tokens": { "input_tokens": 240, "output_tokens": 88 },
        "detail": {
          "qualifier_before": "certainly",
          "qualifier_after": "presumably",
          "warrant_rewritten": true,
          "attacks_neutralised": true,
          "gap_normalised": false,
          "grounds_reordered": true
        }
      },
      {
        "ts": "2026-04-01T14:23:10.881Z",
        "kind": "evaluator_rejected",
        "position": "claim",
        "cycle": 1,
        "detail": { "gap": "Required: troponin result at T+0 per NICE NG185" }
      },
      {
        "ts": "2026-04-01T14:23:19.302Z",
        "kind": "verdict_reached",
        "position": "claim",
        "cycle": 2,
        "detail": { "verdict": "defeated", "cycles_used": 2 }
      }
    ]
  }
}
```

**Event kinds and their detail fields:**

| Kind | Detail fields |
|---|---|
| `pipeline_start` | `claim`, `domain_standard`, `termination_limit` |
| `cycle_start` | `cycle_number`, `total_cycles` |
| `agent_start` | `agent` |
| `agent_complete` | `agent` + agent-specific fields (see below) |
| `tool_called` | `agent`, `tool`, `query`, `result_chars`, `result_preview` |
| `translation_applied` | `qualifier_before`, `qualifier_after`, `grounds_reordered`, `warrant_rewritten`, `attacks_neutralised`, `gap_normalised` |
| `auditor_blocked` | `rule`, `stage`, `gap` |
| `evaluator_rejected` | `gap` |
| `no_progress_halt` | `repeated_gap`, `cycle` |
| `verdict_reached` | `verdict`, `cycles_used` |

**Agent-complete detail by agent:**

| Agent | Detail fields |
|---|---|
| Constructor | `grounds_count`, `qualifier`, `warrant_preview`, `has_backing` |
| Classifier | `scheme`, `open_attacks_count`, `answered_cqs`, `unanswered_cqs`, `burden_bearer` |
| Auditor | `blocked`, `violations_count`, `blocking_violations`, `blocking_rule`, `gap_preview` |
| Evaluator | `accepted`, `gap_preview` |
| Resolver | `verdict`, `surviving_attacks`, `defeated_attacks` |

---

## API Reference

### `POST /v1/evaluate`

Synchronous bipolar evaluation. Blocks until both pipelines complete. Suitable for integration, debugging, and testing. For long-running evaluations in production, prefer the async endpoint.

#### Required fields only

The three required fields are all you need. The Constructor will retrieve evidence from scratch via web search, surface the implicit warrant, and the translation layer will calibrate the qualifier from the evidence it finds.

**Healthcare — emergency triage decision**

```bash
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "deprioritise this patient",
    "dialogue_type": "deliberation",
    "domain_standard": "experienced emergency clinician familiar with NICE NSTEMI NG185 troponin rule-out protocol"
  }'
```

The Evaluator will establish what NICE NG185 actually requires (troponin at T+0 and T+3h, serial ECG) and test whether the grounds meet that standard. If troponin was not measured, the claim is defeated and the contrary (`do not deprioritise this patient`) survives — producing `wrong_starting_position`.

**Finance — stock purchase decision**

```bash
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "I should purchase NVIDIA stock today",
    "dialogue_type": "deliberation",
    "domain_standard": "chartered financial analyst familiar with momentum investing, valuation multiples, and semiconductor sector dynamics"
  }'
```

The Constructor retrieves current price/PE/growth data. The Evaluator checks whether the evidence meets the threshold a CFA would require before acting. The contrary (`I should not purchase NVIDIA stock today`) runs independently — if both survive, the result is `equipoise`, indicating the evidence is genuinely balanced and the decision cannot be justified from data alone.

**Architecture — decomposition decision**

```bash
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "we should decompose the monolith into microservices",
    "dialogue_type": "deliberation",
    "domain_standard": "senior software architect familiar with CAP theorem, DDD, and microservices trade-offs at scale"
  }'
```

---

#### With optional fields

Optional fields let you supply evidence and structure that would otherwise be retrieved or inferred. Omitting them is not a degraded mode — it is the default: the Constructor builds the evidential basis from scratch. Supplying them seeds the pipeline with your specific context and skips the cold-start search.

**`termination_limit`** — how many cycles each pipeline may run before terminating. Default `3`. Each cycle costs one full pass through all five agents. Use `1` for a fast single-pass opinion, `3–5` for high-stakes decisions where the Constructor should have multiple attempts to retrieve missing evidence identified by the Evaluator. Range 1–10.

```bash
# Fast single-pass — no retry if evidence is initially insufficient
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "discharge this patient",
    "dialogue_type": "deliberation",
    "domain_standard": "experienced emergency clinician familiar with NICE chest pain pathway NG185",
    "termination_limit": 1
  }'
```

**`grounds`** — pre-supply the evidential basis for the claim pipeline. If omitted, the Constructor uses web search to retrieve evidence from scratch. If provided, cycle 1 starts with your evidence already in place; the Constructor only searches on subsequent cycles if the Evaluator identifies a gap. The contrary pipeline always constructs its own grounds independently — `grounds` is only for the claim position.

Each ground requires `content` (the evidence text), `source` (where it came from), and `probative_weight` (0.0–1.0, your assessment of evidential strength). The translation layer will reorder by weight and recalibrate the qualifier from the mean.

```bash
# Healthcare with pre-supplied clinical measurements
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "deprioritise this patient",
    "dialogue_type": "deliberation",
    "domain_standard": "experienced emergency clinician familiar with NICE NSTEMI NG185 troponin rule-out protocol",
    "termination_limit": 3,
    "grounds": [
      {
        "content": "12-lead ECG shows normal sinus rhythm, no ST changes, no new LBBB",
        "source": "ED ECG recorded 14:32",
        "probative_weight": 0.7
      },
      {
        "content": "High-sensitivity troponin T at T+0: 8 ng/L (below 99th percentile threshold of 14 ng/L)",
        "source": "ED pathology, collected 14:35",
        "probative_weight": 0.85
      },
      {
        "content": "Patient age 28, no cardiac history, symptom onset during exercise, resolved spontaneously",
        "source": "Clerk-in notes",
        "probative_weight": 0.5
      }
    ]
  }'
```

**`warrant`** — the explicit inferential link from grounds to claim, stated as a defeasible assumption. If omitted, the Constructor surfaces the implicit warrant from the evidence it retrieves. Provide it when you have a specific causal theory you want the pipeline to test — the Classifier will then assign a scheme to your stated warrant and attach its critical questions.

**`backing`** — an authoritative source that licenses the warrant. If omitted, it remains null and the warrant is treated as an unsupported assumption (which is correct — most warrants are). Provide it when you have a guideline or standard that explicitly endorses the inferential step.

**`qualifier`** — initial expressed confidence. If omitted, defaults to `"presumably"`. The translation layer always recalibrates the qualifier from the mean probative weight of the grounds, so the initial value matters only for the very first translation pass.

```bash
# Finance with warrant and backing — testing a specific causal theory
curl -s -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "I should purchase NVIDIA stock today",
    "dialogue_type": "deliberation",
    "domain_standard": "chartered financial analyst familiar with momentum investing, valuation multiples, and semiconductor sector dynamics",
    "termination_limit": 3,
    "grounds": [
      {
        "content": "NVIDIA Q4 FY2025 revenue $39.3B, up 78% YoY, driven by data centre segment",
        "source": "NVIDIA Q4 FY2025 earnings release",
        "probative_weight": 0.75
      },
      {
        "content": "Forward PE ratio 35x vs 5-year average of 42x, suggesting relative discount to historical valuation",
        "source": "Bloomberg consensus estimates, April 2025",
        "probative_weight": 0.6
      }
    ],
    "warrant": "It is assumed that: sustained data centre revenue growth combined with a below-average forward multiple indicates the market has not fully priced in continued AI infrastructure demand",
    "backing": "Damodaran (2024) on growth-adjusted valuation for semiconductor companies with platform moats",
    "qualifier": "presumably"
  }'
```

---

### `POST /v1/evaluate/async`

Async evaluation. Returns `job_id` immediately. Pipeline runs in background.

```bash
curl -X POST http://localhost:8000/v1/evaluate/async \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "I should purchase NVIDIA stock today",
    "dialogue_type": "deliberation",
    "domain_standard": "chartered financial analyst familiar with momentum investing, valuation multiples, and semiconductor sector dynamics"
  }'

# → { "job_id": "550e8400-e29b-41d4-a716-446655440000" }
```

### `GET /v1/jobs/{job_id}`

Poll for result of an async evaluation.

```bash
curl http://localhost:8000/v1/jobs/550e8400-e29b-41d4-a716-446655440000
# → { "job_id": "...", "status": "complete", "result": { ... } }
```

`status` values: `pending` → `running` → `complete` | `failed`

### `DELETE /v1/jobs/{job_id}`

Remove a completed job from the in-memory store.

### `GET /v1/health`

```bash
curl http://localhost:8000/v1/health
# → { "status": "ok", "version": "0.2.0", "primary_model": "...", "fast_model": "..." }
```

---

## Request and Response Schema

### Request

| Field | Type | Required | Default | If omitted |
|---|---|---|---|---|
| `claim` | string | **Yes** | — | Request rejected. |
| `dialogue_type` | enum | **Yes** | — | Request rejected. |
| `domain_standard` | string | **Yes** | — | Request rejected. |
| `termination_limit` | int | No | `3` | Both pipelines run up to 3 cycles. Range 1–10. |
| `grounds` | array | No | null | Constructor retrieves evidence via web search from scratch. |
| `warrant` | string | No | null | Constructor surfaces the implicit inferential link from the retrieved evidence. |
| `backing` | string | No | null | Warrant is treated as an unsupported defeasible assumption — correct in most cases. |
| `qualifier` | string | No | `"presumably"` | Translation layer recalibrates from mean probative weight of grounds regardless. |

**What "omitting optional fields" means in practice:**

Omitting optional fields is not a degraded mode — it is the intended default. The three required fields are sufficient for a full bipolar evaluation. Gauntlet is designed to operate without pre-supplied evidence: the Constructor retrieves grounds from scratch, surfaces the implicit warrant, and the translation layer calibrates confidence from what is actually found. Optional fields let you seed the pipeline with your specific context when you already have it.

- **`grounds` omitted** → Constructor calls `web_search` on the first iteration of cycle 1, retrieving evidence for the claim. On cycle 2+ it searches specifically for the element identified in `acceptance_gap` from the previous cycle. The contrary pipeline always constructs its own grounds independently regardless of whether you supply grounds for the claim.

- **`warrant` omitted** → Constructor writes the warrant from the evidence it retrieves. It is always framed as a defeasible assumption beginning with "It is assumed that:" — the translation layer enforces this framing before the Classifier sees it.

- **`backing` omitted** → Warrant has no authoritative licence. This is the correct representation for most warrants, which are inferential assumptions rather than established rules. The Classifier will mark backing-dependent critical questions as unanswered.

- **`qualifier` omitted** → Starts as `"presumably"`. The translation layer immediately recalibrates it from the mean probative weight of the grounds and may change it. The initial value matters only for the very first translation pass.

- **`termination_limit` omitted** → Both pipelines run up to 3 cycles. The no-progress detector may terminate earlier if the Constructor cannot retrieve the evidence identified in the acceptance gap.

**Dialogue types and burden of proof:**

- `deliberation` — deciding what to do; burden falls on whoever recommends action
- `inquiry` — establishing what is true; burden falls on whoever advances the claim
- `persuasion` — resolving a conflict of opinion; burden falls on the protagonist

**Domain standard — be specific:**

The `domain_standard` is the only field the Evaluator sees that defines what counts as sufficient evidence. It is the universal audience against which the argument is tested. Vague standards produce vague verdicts.

```
# Too vague — no evidential threshold, verdict will be arbitrary
"a doctor"
"an investor"
"an engineer"

# Good — names the specific protocol and expertise level
"experienced emergency clinician familiar with NICE NSTEMI NG185 troponin rule-out protocol"

# Good — names the analytical frameworks the evaluator should apply
"chartered financial analyst familiar with momentum investing, DCF valuation, and semiconductor sector dynamics"

# Good — names the regulatory standard directly
"senior software architect familiar with CAP theorem, DDD, and current Netflix/Uber decomposition patterns"

# Good
"GDPR-qualified data protection officer familiar with ICO enforcement guidance and Article 6 lawful basis requirements"
```

### Response — `GauntletResult`

```json
{
  "id": "uuid",
  "comparison": "definite_conclusion | wrong_starting_position | equipoise | insufficient_evidence",
  "recommended_position": "string or null",
  "total_usage": { "input_tokens": 0, "output_tokens": 0 },
  "claim_evaluation": {
    "claim": "original claim",
    "verdict": "survives | defeated | impasse",
    "qualifier": "presumably",
    "acceptance_gap": "string or null",
    "rebuttal_log": [ ... ],
    "cycles_run": 2,
    "no_progress": false,
    "usage": { "input_tokens": 0, "output_tokens": 0 },
    "argument_unit": { ... },
    "trace": [ ... ]
  },
  "contrary_evaluation": {
    "claim": "auto-generated contrary",
    ...same shape as claim_evaluation...
  }
}
```

`recommended_position` is set to the surviving claim when `comparison` is `definite_conclusion` or `wrong_starting_position`. It is `null` for `equipoise` and `insufficient_evidence`.

---

## Configuration

All configuration via environment variables. Copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **Required.** Get from [openrouter.ai](https://openrouter.ai). |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Override to use any OpenAI-compatible endpoint. |
| `GAUNTLET_PRIMARY_MODEL` | `anthropic/claude-opus-4-6` | Model for all five reasoning agents. |
| `GAUNTLET_FAST_MODEL` | `anthropic/claude-haiku-4-5` | Model for translation layer and contrary generation. |
| `GAUNTLET_HOST` | `0.0.0.0` | Bind address. |
| `GAUNTLET_PORT` | `8000` | Port. |
| `GAUNTLET_RELOAD` | `false` | Hot reload for development. |

---

## Changing Models

Any OpenRouter model string works for either role. Models are resolved at startup — no code changes required.

```bash
# In .env

# High-capability primary + cheap fast
GAUNTLET_PRIMARY_MODEL=anthropic/claude-opus-4-6
GAUNTLET_FAST_MODEL=anthropic/claude-haiku-4-5

# Google models
GAUNTLET_PRIMARY_MODEL=google/gemini-2.5-pro
GAUNTLET_FAST_MODEL=google/gemini-2.0-flash

# Open models
GAUNTLET_PRIMARY_MODEL=meta-llama/llama-3.3-70b-instruct
GAUNTLET_FAST_MODEL=meta-llama/llama-3.1-8b-instruct

# Cross-provider mix
GAUNTLET_PRIMARY_MODEL=anthropic/claude-opus-4-6
GAUNTLET_FAST_MODEL=openai/gpt-4o-mini
```

Per-agent model overrides are available in `config.py` via the `constructor_cfg`, `classifier_cfg`, `auditor_cfg`, `evaluator_cfg`, `resolver_cfg` fields on `GauntletConfig`. This lets you assign a cheaper model to less demanding agents (Classifier, Auditor) and reserve the strongest model for the Evaluator and Resolver.

**Model compatibility:** Some models do not support `response_format: json_object`. If you use one, add its model string prefix to `_NO_JSON_MODE` in `client.py`. The client falls back to prompt-only JSON instruction automatically.

---

## Adding Tools

Tools are how agents retrieve external information. Only the Constructor and Evaluator have tool access — enforced structurally by which tool names are passed to `run_agent()`.

Adding a new tool requires changes to **one file only**: `src/gauntlet/tools.py`.

**Step 1 — Implement the Tool protocol**

```python
# In tools.py

class PubMedTool:
    name        = "pubmed_search"
    description = (
        "Search PubMed for peer-reviewed clinical evidence. "
        "Use for Constructor ground retrieval in clinical domains."
    )

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name":        self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type":        "string",
                            "description": "PubMed search query.",
                        },
                        "max_results": {
                            "type":    "integer",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, arguments: dict) -> str:
        query = arguments["query"]
        # Your implementation — any async HTTP call
        return f"PubMed results for: {query}"
```

**Step 2 — Register and assign**

```python
# Still in tools.py — after the class definition

pubmed = registry.register(PubMedTool())

# Give to Constructor (case evidence retrieval)
CONSTRUCTOR_TOOLS.append("pubmed_search")

# Or give to Evaluator (criterion establishment)
# EVALUATOR_TOOLS.append("pubmed_search")
```

That is the complete change. No other files need modification.

**Tool permission model:** The `allowed_tools` list passed to `run_agent()` is the only thing that determines what an agent can call. An agent that is not given a tool structurally cannot call it — the schema is never included in its API request.

---

## Running Tests

```bash
pip install -e ".[dev]"

# All tests
pytest tests/ -v

# By module
pytest tests/test_models.py -v       # field isolation (critical invariant)
pytest tests/test_trace.py -v        # traceability event structure
pytest tests/test_orchestrator.py -v # bipolar logic, no-progress detection
pytest tests/test_translation.py -v  # deterministic corrections
pytest tests/test_validation.py -v   # input guard
pytest tests/test_tools.py -v        # registry and permissions
pytest tests/test_api.py -v          # endpoint routing and response shape
```

The test suite makes **no real LLM calls**. Pipeline functions are mocked in API tests; deterministic logic is tested directly.

---

## Project Structure

```
gauntlet/
├── src/gauntlet/
│   ├── __init__.py          # version
│   ├── __main__.py          # entry point: python -m gauntlet
│   ├── config.py            # GauntletConfig — model roles, env loading
│   ├── models.py            # ArgumentUnit, all views, request/response types
│   ├── trace.py             # PipelineTrace — first-class traceability
│   ├── client.py            # Async OpenRouter client
│   ├── tools.py             # Tool protocol, registry, WebSearch, DocumentFetch
│   ├── validation.py        # Input guard, injection detection
│   ├── translation.py       # Quality monitor — parallel async corrections
│   ├── orchestrator.py      # Bipolar pipeline, cycle logic, no-progress detection
│   ├── api.py               # FastAPI routes
│   └── agents/
│       ├── base.py          # run_agent() — tool loop, retry, tracing
│       ├── constructor.py   # Agent 0 — Toulmin (web search)
│       ├── classifier.py    # Agent 1 — Walton (no tools)
│       ├── auditor.py       # Agent 2 — Van Eemeren (no tools)
│       ├── evaluator.py     # Agent 3 — Perelman (web search, criterion only)
│       └── resolver.py      # Agent 4 — Dung + ASPIC+ (no tools)
├── tests/
│   ├── conftest.py
│   ├── test_models.py       # 18 tests — field isolation
│   ├── test_trace.py        # 15 tests — event structure
│   ├── test_orchestrator.py # 14 tests — bipolar logic
│   ├── test_translation.py  # 8 tests — deterministic corrections
│   ├── test_validation.py   # 13 tests — input guard
│   ├── test_tools.py        # 14 tests — registry and permissions
│   └── test_api.py          # 20 tests — endpoints
├── pyproject.toml
└── .env.example
```

**18 source files. 2,446 lines. No agent framework dependencies.**

---

## Design Decisions

**Instructions are not implementations.** An agent told not to read a field will, under adversarial pressure, read it. Gauntlet enforces isolation through typed Pydantic projections: `ClassifierInput` does not contain `domain_standard` — the field simply does not exist. No instruction required.

**Translation is a function, not an agent.** The quality monitor has no opinion on the claim. It applies three deterministic corrections and three targeted LLM calls for linguistic reframing. It fires at every agent handoff via explicit Python calls. The three LLM calls run in parallel. Token usage is tracked and returned. If any call fails, the original text is preserved.

**Translation runs on the blocking path.** When the Auditor blocks, the acceptance gap must be translated into a neutral retrieval specification before cycling back to the Constructor. Without this, the Constructor (which has myside bias) receives a criticism-framed gap and rationalises against it rather than retrieving the missing evidence. This is the most consequential bug in prior versions.

**Traceability is first-class.** The `PipelineTrace` accumulates structured events at every meaningful step — including every tool call, every translation delta, every agent decision point. The full trace is returned in the API response. A user submitting a clinical or legal claim can see exactly what evidence was retrieved, what scheme was identified, what CQs were unanswered, what rule was triggered, and why the verdict was reached. Debugging and auditing are first-class concerns, not afterthoughts.

**Contrary pipeline is independent.** The contrary pipeline constructs its own grounds and warrant from scratch. It does not inherit anything from the claim pipeline. This independence is required for the bipolar comparison to be meaningful — two pipelines drawing from the same evidence base would not produce an independent verdict.

**No agent SDK, no framework.** The orchestrator is 280 lines of plain Python. The entire "framework" is `run_agent()` in `agents/base.py` — a while loop that breaks when the model returns no tool calls. LangChain, LangGraph, NAT, and MTHDS were all evaluated and rejected. Their abstractions either solve a different problem (dynamic routing, which Gauntlet does not need), introduce incompatibilities (NAT does not support OpenRouter natively), or add complexity without adding capability.

---

## Theoretical Foundations

| Theorist | Work | Role in Gauntlet |
|---|---|---|
| Toulmin | *The Uses of Argument* (1958) | Structures every argument as claim, grounds, warrant, backing, qualifier — making implicit assumptions explicit and testable |
| Walton, Reed & Macagno | *Argumentation Schemes* (2008) | Names the inference pattern and attaches the specific critical questions that scheme must survive |
| Van Eemeren & Grootendorst | *A Systematic Theory of Argumentation* (2004) | Checks whether the exchange is structured fairly enough to resolve the disagreement — ten rules across four stages |
| Perelman & Olbrechts-Tyteca | *The New Rhetoric* (1958) | The universal audience standard: would a reasonable, fully-informed expert in this domain act on this argument? |
| Dung | *On the Acceptability of Arguments* (1995) | Abstract argumentation framework: builds the attack graph, computes which arguments survive in the preferred extension |
| Prakken & Modgil | *ASPIC+* (2010) | Extends Dung with typed attacks (rebuttal, undercutting, undermining) and structured argument construction |
| Cayrol & Lagasquie-Schiex | Bipolar argumentation (2005) | Extends Dung to handle both support and attack relations — the formal basis for the claim/contrary comparison |
| Mercier & Sperber | *The Enigma of Reason* (2011) | Argumentation evolved for persuasion, not truth-seeking — the translation layer corrects for selection bias, anchoring bias, and qualifier inflation |

---

## License

MIT
