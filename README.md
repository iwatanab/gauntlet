# Gauntlet

Better decisions through rigorous argument.

Gauntlet is a bipolar deliberation harness. It evaluates both a claim and its logical contrary, constructs each position independently, and compares the resulting verdicts in pure Python. The system is built around argumentation theory, but the implementation is intentionally small: one public string input, one preflight phase, and four execution stages per cycle.

## Philosophy

Gauntlet is guided by one principle:

> Separate reasoning modes, not machinery for its own sake.

The load-bearing invariants are:

- Bipolar independence: the claim and its contrary are constructed separately.
- Structural field isolation: each stage sees only the fields it is allowed to see.
- Tool isolation: only Constructor and Evaluator may use tools.
- Deliberation only: the burden bearer is always the action recommender.
- Three-cycle cap: the system stops after at most three attempts per position.

This means Gauntlet preserves epistemic isolation where it matters, while removing the standalone translation layer and other derived machinery that used to exist only to repair upstream outputs.

## Runtime

Public request:

```json
"We should discharge this patient because serial troponins are negative and the ECG is unchanged."
```

Preflight:

1. Validate that the input contains exactly one atomic claim.
2. Extract any explicit Toulmin components already present in the string.
3. Infer the domain standard for the evaluator.
4. Generate the logical contrary.

Per position, per cycle:

```text
Constructor (tools)
-> Critique Bundle (no tools)
   blocked? -> loop using required_gap
-> Evaluator (tools)
   rejected? -> loop using required_gap
-> Resolver (no tools)
```

The cycle cap is fixed at `3`.

## Stages

### Constructor

Basis: Toulmin.

- Builds the strongest defensible argument for the claim.
- Preserves user-provided grounds verbatim.
- Treats user-provided grounds as stipulated true.
- Strengthens the warrant and backing aggressively.
- Uses tools only for evidence retrieval.
- Produces the single canonical warrant used downstream.

### Critique Bundle

Basis: Walton + pragma-dialectics.

- Classifies the argument scheme.
- Attaches critical questions.
- Converts unanswered critical questions into neutral `open_attacks`.
- Audits the exchange for blocking rule violations.
- Produces one canonical `required_gap` when the cycle must continue.

### Evaluator

Basis: Perelman & Olbrechts-Tyteca.

- Sees `domain_standard`; no other stage does.
- Decides whether the universal audience for that standard would act on the argument.
- Produces one canonical `required_gap` when the argument is not yet acceptable.
- May use tools only to establish standards, not case evidence.

### Resolver

Basis: Dung + ASPIC+.

- Consumes the canonical attacks and canonical gap.
- Builds the attack graph.
- Determines whether the claim survives, is defeated, or reaches impasse.

## Why The Translation Layer Is Gone

Older versions used a separate translation layer to rewrite warrants, attacks, and gaps after the producing stage. That design increased latency, retries, and failure surfaces while also acting like a hidden extra judge.

The current design removes that layer entirely:

- Constructor emits the canonical warrant directly.
- Critique emits neutral attacks directly.
- Critique and Evaluator emit canonical `Required:` gaps directly.

Boundary-safe output is now the responsibility of the producing stage.

## Field Isolation

Isolation is enforced by typed stage inputs created from a shared internal `PipelineState`.

Key visibility rules:

- Constructor cannot see `domain_standard`, attacks, rule violations, or verdict.
- Critique cannot see `domain_standard`, rebuttal history, or verdict.
- Evaluator cannot see `open_attacks` or `rebuttal_log`.
- Resolver cannot see `domain_standard`.

Separate execution contexts are still retained where hidden-field or tool boundaries require them.

## API

### `POST /v1/evaluate`

Request body:

```json
"Implement mandatory 2FA for all admin routes."
```

Successful response shape:

```json
{
  "id": "uuid",
  "claim_evaluation": {
    "claim": "Implement mandatory 2FA for all admin routes.",
    "verdict": "survives",
    "final_argument": {
      "grounds": [],
      "warrant": "It is assumed that: ...",
      "backing": null,
      "qualifier": "presumably"
    },
    "issues": {
      "scheme": "argument_from_practical_reasoning",
      "critical_questions": [],
      "open_attacks": [],
      "rule_violations": []
    },
    "required_gap": null,
    "rebuttal_log": [],
    "cycles_run": 1,
    "no_progress": false,
    "trace": {
      "position": "claim",
      "preflight": {},
      "preflight_usage": { "input_tokens": 0, "output_tokens": 0 },
      "cycles": [],
      "halt_reason": "survives",
      "metrics": { "stage_calls": 4, "tool_calls": 1, "cycles_used": 1 }
    },
    "usage": { "input_tokens": 0, "output_tokens": 0 }
  },
  "contrary_evaluation": { "...": "same shape" },
  "comparison": "definite_conclusion",
  "recommended_position": "Implement mandatory 2FA for all admin routes.",
  "inferred_domain_standard": "balance of probabilities",
  "total_usage": { "input_tokens": 0, "output_tokens": 0 }
}
```

### `POST /v1/evaluate/async`

Returns a `job_id` immediately. Poll `GET /v1/jobs/{job_id}` for status and result.

### `GET /v1/health`

Reports the configured `primary_model`, `preflight_model`, and Tavily status.

## Input Rules

The request body must be a single string containing one atomic claim.

If multiple atomic claims are identified, Gauntlet returns `422` immediately with:

- `code: "multiple_claims"`
- a refusal message
- the list of atomic claims it identified

Grounds, warrant, backing, and qualifier may all be embedded in the same input string and are extracted during preflight.

## Configuration

Environment variables:

| Variable | Purpose |
|---|---|
| `OPENROUTER_API_KEY` | OpenRouter API key |
| `OPENROUTER_BASE_URL` | OpenRouter base URL |
| `TAVILY_API_KEY` | Tavily search key for tools |
| `GAUNTLET_PRIMARY_MODEL` | Model for Constructor, Critique, Evaluator, Resolver |
| `GAUNTLET_PREFLIGHT_MODEL` | Model for parsing, domain-standard inference, and contrary generation |

`GAUNTLET_FAST_MODEL` is still accepted as a fallback alias for `GAUNTLET_PREFLIGHT_MODEL`.

## Development

Run the API:

```bash
gauntlet
```

Run tests:

```bash
pytest -q
```

Core source layout:

```text
src/gauntlet/
  api.py
  client.py
  config.py
  models.py
  orchestrator.py
  parsing.py
  trace.py
  tools.py
  agents/
    base.py
    constructor.py
    critique.py
    evaluator.py
    resolver.py
```
