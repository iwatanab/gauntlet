# Gauntlet

**Better decisions through rigorous argument.**

Gauntlet is a multi-agent argumentation harness exposed as a REST API. Submit a claim — a recommendation, a decision, a proposed action — and Gauntlet subjects it to a structured sequence of theoretical challenges before returning either a justified verdict or an honest record of why justification could not be reached.

Most AI systems optimise for an answer. Gauntlet optimises for a *justified* answer and treats the two as distinct.

```
POST /v1/evaluate
{ "claim": "deprioritise this patient", "dialogue_type": "deliberation", ... }

→ { "verdict": "defeated", "qualifier": "presumably",
    "acceptance_gap": "Required: troponin result at T+0 per NICE NG185",
    "rebuttal_log": [...], "cycles_run": 1 }
```

---

## Table of Contents

- [Quick Start](#quick-start)
- [How It Works](#how-it-works)
  - [The Argument Unit](#the-argument-unit)
  - [The Agent Sequence](#the-agent-sequence)
  - [The Translation Layer](#the-translation-layer)
  - [Cycle Logic](#cycle-logic)
  - [Field Isolation](#field-isolation)
- [API Reference](#api-reference)
  - [POST /v1/evaluate](#post-v1evaluate)
  - [POST /v1/evaluate/async](#post-v1evaluateasync)
  - [GET /v1/jobs/{job\_id}](#get-v1jobsjob_id)
  - [GET /v1/health](#get-v1health)
- [Request Schema](#request-schema)
- [Response Schema](#response-schema)
- [Configuration](#configuration)
- [Changing Models](#changing-models)
- [Adding Tools](#adding-tools)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Design Principles](#design-principles)
- [Theoretical Foundations](#theoretical-foundations)

---

## Quick Start

**Requirements:** Python 3.11+, an [OpenRouter](https://openrouter.ai) API key.

```bash
# 1. Clone and install
git clone https://github.com/your-org/gauntlet.git
cd gauntlet
pip install -e .

# 2. Configure
cp .env.example .env
# Edit .env — set OPENROUTER_API_KEY

# 3. Start the server
python -m gauntlet
# → Running on http://0.0.0.0:8000
# → Docs at  http://localhost:8000/docs

# 4. Submit a claim
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "decompose the monolith into microservices",
    "dialogue_type": "deliberation",
    "domain_standard": "senior software architect familiar with CAP theorem and microservices trade-offs",
    "termination_limit": 2
  }'
```

The interactive API docs at `/docs` let you try every endpoint in the browser.

---

## How It Works

A claim enters the system and passes through five specialist agents in sequence. Between every agent handoff, an independent translation layer normalises the language to ensure the next agent evaluates evidence rather than presentation. The cycle repeats until the claim survives, is defeated, or reaches the termination limit.

```
Claim ──► Constructor ──[translate]──► Classifier ──[translate]──► Auditor
                                                                       │
          ◄──── cycle if blocked ────────────────────────────────────┘
                                                                       │
                                                          [translate]  │
                                                                       ▼
                                                               Evaluator
                                                                   │
          ◄──── cycle if rejected ─────────────────────────────────┘
                                                                   │
                                                          [translate]  │
                                                                   ▼
                                                            Resolver
                                                                │
                              ┌─────────────────────┬──────────┴─────────┐
                              ▼                     ▼                    ▼
                           survives             defeated              impasse
                         (verdict +           (cycle again        (rebuttal log
                       rebuttal log)          if < limit)          as output)
```

### The Argument Unit

Every agent operates on a single shared JSON object: the **ArgumentUnit**. The orchestrator owns this object. No agent reads it directly — each receives only a typed projection containing the fields it is permitted to see. This is the architectural mechanism behind field isolation.

| Field group | Fields | Set by |
|---|---|---|
| Identity | `id`, `cycle`, `dialogue_type`, `domain_standard`, `termination_limit` | Initialisation — fixed |
| Toulmin structure | `claim`, `grounds[]`, `warrant`, `backing`, `qualifier` | Constructor |
| Classifier output | `scheme`, `critical_questions[]`, `open_attacks[]`, `burden_bearer` | Classifier |
| Auditor output | `stage_audit`, `rule_violations[]` | Exchange Auditor |
| Evaluator output | `acceptance`, `acceptance_gap` | Acceptance Evaluator |
| Resolver output | `attack_graph`, `extension`, `verdict` | Conflict Resolver |
| Discourse record | `rebuttal_log[]` | Appended throughout — never cleared |

### The Agent Sequence

**Agent 0 — Constructor** *(Toulmin, 1958)*

Receives the claim and builds its evidential basis. If grounds are not provided, retrieves them via web search. Surfaces the implicit warrant — what must be true for these grounds to support this claim. Has web search access. Is the most biased agent in the system: it holds the claim and searches for supporting evidence. Does not populate the rebuttal log.

**Agent 1 — Classifier** *(Walton, 1989–2020)*

Identifies which of Walton's argumentation schemes the warrant instantiates. Attaches the full set of critical questions for that scheme. Evaluates which CQs are answered by the existing grounds and backing. Writes unanswered CQs as undercutting attack vectors. No web search access.

**Agent 2 — Exchange Auditor** *(Van Eemeren & Grootendorst, 2004)*

Checks whether the exchange is structured fairly enough to resolve the disagreement. Applies the ten pragma-dialectics rules across four stages. A blocking violation returns an `acceptance_gap` to the orchestrator, which sends the argument back to the Constructor. No web search access.

**Agent 3 — Acceptance Evaluator** *(Perelman & Olbrechts-Tyteca, 1958)*

The only agent that sees `domain_standard`. Applies the universal audience standard: would a reasonable, well-informed expert in this domain act on this argument as currently constructed? Procedural correctness is not the same as rational compellingness — an argument can pass the auditor and fail the evaluator. Has web search access for criterion establishment (retrieving current protocols and standards) — not for case evidence. A rejection returns a specific `acceptance_gap` identifying the missing evidence.

**Agent 4 — Conflict Resolver** *(Dung, 1995 + ASPIC+)*

Collects every attack generated through the exchange. Classifies each as rebuttal (attacks the claim), undercutting (attacks the warrant), or undermining (attacks the grounds). Builds the attack graph, computes the preferred extension, applies reinstatement. Produces one of three verdicts: `survives`, `defeated`, or `impasse`. Appends surviving and defeated attacks to the rebuttal log.

### The Translation Layer

Between every agent handoff, the translation layer applies three corrections derived from Mercier & Sperber's (2011) work on argument quality:

**Selection bias** — Grounds are sorted by `probative_weight` descending. Most evidentially strong evidence first; most vivid or available last. This is deterministic.

**Anchoring bias** — The warrant is restated as an explicit assumption to be evaluated rather than an established fact. Open attacks are restated as neutral evidential gaps — not damning indictments and not minor footnotes. The acceptance gap is restated as a neutral retrieval specification (so the Constructor searches for missing evidence rather than defending against a criticism).

**Qualifier inflation** — The qualifier is calibrated against the mean probative weight of the grounds. If the grounds do not support the expressed confidence, the qualifier is downgraded.

The three LLM calls in the translation layer run in parallel via `asyncio.gather`, cutting translation latency by approximately 60% compared to sequential execution. A fast, cheap model handles translation — the reasoning-heavy agents use the primary model.

### Cycle Logic

After each Resolver call:

- **`survives`** — return the full ArgumentUnit with the complete rebuttal log.
- **`defeated`** and `cycle < termination_limit` — increment cycle, return to Constructor with `acceptance_gap` as retrieval constraint.
- **`defeated`** and `cycle == termination_limit` — return the rebuttal log as an impasse record. Do not produce a verdict.
- **No-progress detection** — if `acceptance_gap` is identical across two consecutive cycles, the Constructor cannot retrieve the missing evidence. Terminate early with `impasse` rather than repeating uselessly.

A documented impasse is an honest output. It tells the caller exactly what the argument could not survive and what evidence would change the outcome.

### Field Isolation

Field isolation is structural, not instructional. Each agent receives a Pydantic model containing *only* its designated fields — it cannot read fields outside its scope regardless of what its system prompt says.

| Agent | Cannot see |
|---|---|
| Constructor | `domain_standard`, `scheme`, `stage_audit`, `acceptance`, `verdict` |
| Classifier | `domain_standard`, `rebuttal_log`, `acceptance`, `verdict` |
| Auditor | `domain_standard`, `acceptance`, `verdict`, `rebuttal_log` |
| Evaluator | `dialogue_type`, `open_attacks[]`, `rebuttal_log`, `verdict` |
| Resolver | `domain_standard`, `dialogue_type`, `scheme`, `stage_audit` |

The Evaluator is the only agent that sees `domain_standard`. This isolation is what ensures the evaluator applies the normative standard independently, without being contaminated by the classifier's framing or the auditor's procedural findings.

---

## API Reference

### POST /v1/evaluate

Synchronous evaluation. Blocks until the pipeline completes. Suitable for direct integration and testing. For production use with long-running cycles, prefer the async endpoint.

**Request**

```bash
curl -X POST http://localhost:8000/v1/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "deprioritise this patient",
    "dialogue_type": "deliberation",
    "domain_standard": "experienced emergency clinician, NICE NSTEMI troponin rule-out protocol NG185",
    "termination_limit": 3
  }'
```

**Response — survives**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "verdict": "survives",
  "qualifier": "presumably",
  "claim": "deprioritise this patient",
  "acceptance_gap": null,
  "rebuttal_log": [
    {
      "timestamp": "2026-04-01T12:00:00Z",
      "agent": "conflict-resolver",
      "attack_type": "undercutting",
      "content": "Troponin T+0 absent in cycle 1 — inference from ECG to cardiac risk unvalidated",
      "status": "defeated"
    }
  ],
  "cycles_run": 2,
  "no_progress": false,
  "usage": { "input_tokens": 18400, "output_tokens": 3100 },
  "argument_unit": { ... }
}
```

**Response — impasse**

```json
{
  "verdict": "impasse",
  "qualifier": "presumably",
  "acceptance_gap": "Required: troponin result at T+0 per NICE NG185 NSTEMI rule-out protocol",
  "rebuttal_log": [
    {
      "attack_type": "undercutting",
      "content": "Troponin measurement absent — primary biomarker for myocardial injury not evaluated",
      "status": "surviving"
    }
  ],
  "cycles_run": 3,
  "no_progress": false,
  ...
}
```

---

### POST /v1/evaluate/async

Returns immediately with a job ID. The pipeline runs in the background.

```bash
curl -X POST http://localhost:8000/v1/evaluate/async \
  -H "Content-Type: application/json" \
  -d '{
    "claim": "implement mandatory 2FA for all admin routes",
    "dialogue_type": "deliberation",
    "domain_standard": "senior security engineer, NIST SP 800-63B authentication guidelines"
  }'
```

```json
{ "job_id": "7f4e2c1a-9b3d-4f8e-a2c6-1d5e8f9a0b7c" }
```

---

### GET /v1/jobs/{job\_id}

Poll for the result of an async evaluation.

```bash
curl http://localhost:8000/v1/jobs/7f4e2c1a-9b3d-4f8e-a2c6-1d5e8f9a0b7c
```

```json
{
  "job_id": "7f4e2c1a-9b3d-4f8e-a2c6-1d5e8f9a0b7c",
  "status": "complete",
  "result": { ... },
  "error": null
}
```

`status` values: `pending` → `running` → `complete` | `failed`

---

### GET /v1/health

```bash
curl http://localhost:8000/v1/health
```

```json
{
  "status": "ok",
  "version": "0.1.0",
  "primary_model": "anthropic/claude-opus-4-6",
  "fast_model": "anthropic/claude-haiku-4-5"
}
```

---

## Request Schema

All fields for `POST /v1/evaluate` and `POST /v1/evaluate/async`:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `claim` | string | Yes | — | The position to be evaluated. Max 2000 characters. |
| `dialogue_type` | enum | Yes | — | `deliberation` \| `inquiry` \| `persuasion` |
| `domain_standard` | string | Yes | — | Defines the universal audience for the evaluator. Be specific about domain, seniority, and relevant standards. |
| `termination_limit` | integer | No | `3` | Maximum cycles before impasse. Range: 1–10. |
| `grounds` | array | No | `null` | Pre-constructed evidence. If omitted, the Constructor retrieves grounds via web search. |
| `warrant` | string | No | `null` | Explicit inferential link. If omitted, the Constructor surfaces it. |
| `backing` | string | No | `null` | Authoritative source licensing the warrant. |
| `qualifier` | string | No | `"presumably"` | Expressed confidence. Calibrated by the translation layer. |

**Dialogue types**

- `deliberation` — deciding what to do. The burden of proof falls on whoever recommends action.
- `inquiry` — establishing what is true. The burden falls on whoever advances the claim.
- `persuasion` — resolving a conflict of opinion. The burden falls on the protagonist.

**Domain standard examples**

```
# Too vague — evaluator will approximate, not apply
"a doctor"

# Good — specific expertise and relevant standard named
"experienced emergency clinician familiar with NICE NSTEMI troponin rule-out protocol NG185"

# Good — cross-domain
"senior software architect familiar with CAP theorem, microservices decomposition trade-offs, and current Netflix/Uber decomposition patterns"

# Good — regulatory domain
"experienced GDPR compliance officer familiar with ICO enforcement guidance and Article 6 lawful basis requirements"
```

---

## Response Schema

| Field | Type | Description |
|---|---|---|
| `id` | string | UUID for this evaluation run. |
| `verdict` | enum | `survives` \| `defeated` \| `impasse` |
| `qualifier` | string | Calibrated confidence: `possibly` \| `presumably` \| `probably` \| `almost certainly` |
| `claim` | string | The original claim as submitted. |
| `acceptance_gap` | string \| null | What evidence is missing. Null if verdict is `survives`. Present for `defeated` and `impasse`. |
| `rebuttal_log` | array | Complete record of every attack — surviving and defeated — with timestamps and attribution. |
| `cycles_run` | integer | How many full agent cycles completed. |
| `no_progress` | boolean | True if the pipeline terminated early because the acceptance gap was unchanged across cycles. |
| `usage` | object | `input_tokens` and `output_tokens` for the full run. |
| `argument_unit` | object | The complete ArgumentUnit for inspection and audit. Contains all intermediate agent outputs. |

**Rebuttal log entry**

```json
{
  "timestamp": "2026-04-01T12:00:00Z",
  "agent": "conflict-resolver",
  "attack_type": "undercutting | rebuttal | undermining",
  "content": "Description of the attack",
  "status": "surviving | defeated"
}
```

---

## Configuration

All configuration via environment variables. Copy `.env.example` to `.env` and edit.

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | **Required.** Your OpenRouter API key. Get one at openrouter.ai. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter endpoint. Change to use a different OpenAI-compatible provider. |
| `GAUNTLET_PRIMARY_MODEL` | `anthropic/claude-opus-4-6` | Model for all five reasoning agents. |
| `GAUNTLET_FAST_MODEL` | `anthropic/claude-haiku-4-5` | Model for the translation layer. Should be cheap and fast. |
| `GAUNTLET_HOST` | `0.0.0.0` | Server bind address. |
| `GAUNTLET_PORT` | `8000` | Server port. |
| `GAUNTLET_RELOAD` | `false` | Enable auto-reload for development (`true` or `false`). |

---

## Changing Models

Any model available on OpenRouter can be used. Set the model strings in `.env`:

```bash
# Use different models per role
GAUNTLET_PRIMARY_MODEL=google/gemini-2.5-pro
GAUNTLET_FAST_MODEL=google/gemini-2.0-flash

# Or use open models
GAUNTLET_PRIMARY_MODEL=meta-llama/llama-3.3-70b-instruct
GAUNTLET_FAST_MODEL=meta-llama/llama-3.1-8b-instruct

# Mix providers
GAUNTLET_PRIMARY_MODEL=anthropic/claude-opus-4-6
GAUNTLET_FAST_MODEL=openai/gpt-4o-mini
```

Per-agent model overrides are available in `src/gauntlet/config.py` if you need finer control (e.g., a cheaper model for the Classifier but a more capable one for the Resolver).

**Note on model compatibility:** Some models do not support `response_format: json_object`. If you use such a model, add its prefix to `_NO_JSON_MODE` in `src/gauntlet/client.py`. The client falls back to prompt-only JSON instruction.

---

## Adding Tools

Tools are the mechanism by which agents retrieve external information. Only the Constructor and Evaluator have tool access — this is enforced structurally, not by instruction.

Adding a new tool requires changes to exactly one file: `src/gauntlet/tools.py`.

**Step 1 — Implement the Tool protocol**

```python
# src/gauntlet/tools.py

class MyCustomTool:
    name = "my_tool"
    description = "What this tool does and when to use it."

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query."
                        }
                    },
                    "required": ["query"],
                },
            },
        }

    async def execute(self, arguments: dict) -> str:
        query = arguments.get("query", "")
        # Your implementation here
        return f"Result for: {query}"
```

**Step 2 — Register and assign**

```python
# Still in tools.py — at the bottom, after the class definition

my_tool = registry.register(MyCustomTool())

# Give to Constructor (case evidence retrieval)
CONSTRUCTOR_TOOLS.append("my_tool")

# Or give to Evaluator (criterion establishment)
# EVALUATOR_TOOLS.append("my_tool")
```

That is the complete change. No other files need modification. The tool is immediately available on the next server start.

**Tool security model:** The `allowed_tools` list passed to `run_agent()` is the only thing that determines which tools an agent can call. An agent that is not given a tool cannot call it — the tool's schema is never included in its API request.

---

## Project Structure

```
gauntlet/
├── src/gauntlet/
│   ├── __init__.py          # Package version
│   ├── __main__.py          # Entry point: python -m gauntlet
│   ├── config.py            # GauntletConfig — model assignments, env loading
│   ├── models.py            # ArgumentUnit + all scoped view models + API types
│   ├── client.py            # Async OpenRouter client (complete_text, complete_json)
│   ├── tools.py             # Tool protocol, registry, WebSearch, DocumentFetch
│   ├── validation.py        # Input guard, injection detection
│   ├── translation.py       # Quality monitor — parallel async LLM corrections
│   ├── orchestrator.py      # Pipeline: agent sequence, cycle logic, no-progress detection
│   ├── api.py               # FastAPI routes (sync evaluate, async evaluate, jobs, health)
│   └── agents/
│       ├── base.py          # run_agent(): tool loop, retry, permission enforcement
│       ├── constructor.py   # Agent 0 — Toulmin (has web search)
│       ├── classifier.py    # Agent 1 — Walton (no tools)
│       ├── auditor.py       # Agent 2 — Van Eemeren (no tools)
│       ├── evaluator.py     # Agent 3 — Perelman (has web search)
│       └── resolver.py      # Agent 4 — Dung + ASPIC+ (no tools)
├── tests/
│   ├── conftest.py          # Shared fixtures
│   ├── test_models.py       # View isolation tests (the critical invariant)
│   ├── test_validation.py   # Input guard tests
│   ├── test_translation.py  # Deterministic translation tests
│   ├── test_tools.py        # Registry, protocol compliance, extensibility
│   └── test_api.py          # Endpoint tests with mocked pipeline
├── pyproject.toml
└── .env.example
```

**17 source files. 1,939 lines. No framework dependencies beyond FastAPI and the OpenAI client.**

The framework is `orchestrator.py`. It is 168 lines. Every architectural decision is explicit and readable there.

---

## Running Tests

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_models.py -v

# Run tests matching a pattern
pytest tests/ -k "isolation" -v
```

The tests cover:

- **Field isolation** — the critical invariant that each agent sees only its designated fields
- **Input validation** — claim length, injection patterns, ground weight ranges
- **Translation layer** — deterministic qualifier calibration and grounds sorting
- **Tool registry** — protocol compliance, permission assignment, extensibility pattern
- **API endpoints** — routing, validation, error handling, response structure

Tests do not make real LLM calls. The pipeline is mocked in API tests. Deterministic translation logic is tested directly.

---

## Design Principles

**Instructions are not implementations.** An agent told not to read a field will, under sufficient adversarial pressure, read it anyway. Gauntlet enforces isolation through Pydantic model projections: an agent that receives a `ClassifierInput` model cannot access `domain_standard` because that field does not exist in `ClassifierInput`. No instruction required.

**The translation layer is a function, not an agent.** The quality monitor has no opinion on the claim. It applies three deterministic bias corrections and three targeted LLM calls for linguistic reframing. It fires between every agent handoff via explicit Python calls — not through a hook mechanism that could be bypassed.

**No framework, no lock-in.** The orchestrator is 168 lines of plain Python. There is no LangChain, no LangGraph, no LlamaIndex, no MTHDS. Each agent is one file, one function, one system prompt. The tool loop in `agents/base.py` borrows its pattern from the Claude Code Rust reimplementation's `run_turn()` — a while loop that breaks when the model returns no tool calls.

**Parallel where correct, sequential where required.** The three translation layer LLM calls are independent of each other and run in parallel. The five agents are sequentially dependent — Walton's classifier must run before Van Eemeren's auditor, because the auditor receives `burden_bearer` and `open_attacks` as inputs. Parallelism is applied where the dependencies permit it, not everywhere.

**Honest output under genuine uncertainty.** A three-cycle impasse record is more useful than a forced verdict. The `acceptance_gap` field specifies exactly what evidence would change the outcome, making the impasse actionable rather than merely negative.

---

## Theoretical Foundations

Gauntlet implements six traditions in argumentation theory. Each addresses a distinct dimension of the problem of reasoning under uncertainty.

| Theorist | Year | Contribution | Role in Gauntlet |
|---|---|---|---|
| Toulmin | 1958 | The argument unit | Breaks every argument into claim, grounds, warrant, backing, qualifier — making the implicit explicit |
| Walton | 1989–2020 | Argumentation schemes | Names the inference pattern and attaches the specific challenges it must survive |
| Van Eemeren & Grootendorst | 2004 | Pragma-dialectics | Checks whether the exchange is structured fairly enough to resolve the disagreement |
| Perelman & Olbrechts-Tyteca | 1958 | The New Rhetoric | Tests whether a reasonable, well-informed expert would act on the argument |
| Dung | 1995 | Abstract argumentation | Computes which arguments survive when arguments conflict |
| Mercier & Sperber | 2011 | Argumentative theory of reasoning | Ensures argument acceptance tracks evidential strength, not presentation |

The framework is described in detail in the accompanying blog series:
- [Part 1 — The Perspectives That Shaped the Field](https://medium.com/@isawatanabe/)
- [Part 2 — Building AI That Argues Well](https://medium.com/@isawatanabe/argumentation-for-ai-part-2-building-ai-that-argues-well-d9ca04c201e6)

---

## License

MIT
