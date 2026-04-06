# Gauntlet

Better decisions through rigorous argument.

Gauntlet is an argumentation-theory-based deliberation harness. It takes one deliberative claim, builds the strongest case for it and for its logical contrary, runs both through the same isolated reasoning pipeline, and compares the outcomes.

> [!IMPORTANT]
> Gauntlet is experimental research software, not a production decision system.
> Expect breaking changes to prompts, schemas, runtime behavior, and tool integrations while the architecture is still evolving.
> The core pipeline is live, but `clinical` and `financial` mode currently expose placeholder domain tools, and nothing in this repository should be used for unattended or high-stakes clinical or financial decision-making without independent validation.

## Why This Exists

Gauntlet starts from a simple claim:

Formal deductive reasoning is necessary for some tasks, but it is not sufficient for most real-world decisions.

In formal logic, if the premises are guaranteed to be sufficient for the conclusion, validity can do most of the work. Real decisions usually do not look like that. They involve incomplete evidence, defeasible inferences, contested standards, audience-relative acceptability, and live counterarguments.

That is the problem Gauntlet is built for.

It is not a theorem prover. It is a deliberation system for open-textured, revisable decisions where:

- the claim may already contain evidence, warrants, and backing
- the right standard must be inferred and applied
- the strongest contrary position must be considered, not ignored
- unresolved attacks should block overconfident conclusions

## Theoretical Foundations

Gauntlet is not "inspired by argumentation" in a vague way. Each stage is tied to a distinct tradition and a distinct job.

| Thinker / tradition | Contribution to Gauntlet | Where it shows up in code |
|---|---|---|
| Stephen Toulmin | Real arguments are not exhausted by formal validity; claims are supported by grounds, warrants, backing, and qualifiers. | Preflight extraction and the Constructor stage |
| Douglas Walton, Chris Reed, Fabrizio Macagno | Argument schemes and their critical questions provide a way to test defeasible reasoning patterns. | Critique Bundle scheme classification and critical questions |
| Frans van Eemeren, Rob Grootendorst | Pragma-dialectics treats argument as a regulated critical discussion with rule-governed failure modes. | Critique Bundle stage audit and blocking rule violations |
| Chaim Perelman, Lucie Olbrechts-Tyteca | Acceptability depends on what a relevant audience would accept, not on formal validity alone. | Evaluator stage and inferred `domain_standard` |
| Phan Minh Dung | Arguments stand or fall in light of attacks and defense, not in isolation. | Resolver stage verdict logic |
| Henry Prakken, Sanjay Modgil, ASPIC+ | Defeasible reasoning needs distinctions like rebuttal, undercutting, and undermining. | Attack types and Resolver semantics |
| Hugo Mercier, Dan Sperber | Human reasoning is biased and adversarial; good systems should structure disagreement rather than assume neutral introspection. | Bipolar evaluation and stage isolation |
| Donald Schon | Real practice requires problem-setting, not just technical rule application after the problem is already fixed. | Preflight framing: atomic-claim extraction and domain-standard inference |

## What Gauntlet Does

Gauntlet accepts a single JSON string:

```json
"Implement mandatory 2FA for all admin routes."
```

It then:

1. validates that the input contains exactly one atomic claim
2. extracts any explicit Toulmin components already present in the string
3. infers the domain standard for evaluation
4. generates the logical contrary
5. runs both claim and contrary through the same four-stage pipeline
6. compares the two outcomes in pure Python

The current pipeline is:

```text
Preflight
  -> parse one atomic claim
  -> extract grounds / warrant / backing / qualifier
  -> infer domain_standard
  -> generate contrary

Per position (claim, contrary), per cycle:
  Constructor (tools)
  -> Critique Bundle (no tools)
     blocked? -> loop using required_gap
  -> Evaluator (tools)
     rejected? -> loop using required_gap
  -> Resolver (no tools)

Final:
  compare claim vs contrary
  -> recommend a position or report that the evidence is insufficient
```

## Design Invariants

These are the load-bearing architectural constraints in the current codebase:

- Bipolar independence: the claim and its contrary are constructed independently.
- Structural field isolation: each stage sees only the fields it is allowed to see.
- Tool isolation: only Constructor and Evaluator may use tools.
- Deliberation only: the system evaluates action-guiding claims, not arbitrary dialogue modes.
- Three-cycle cap: each position gets at most three attempts.
- No translation layer: stages must emit canonical outputs directly instead of relying on downstream rewrite passes.

## Stage Map

### Preflight

Preflight is a separate model role used for parsing and setup.

It performs four jobs:

- reject no-claim or multi-claim inputs
- extract grounds verbatim from the user's text
- extract explicit warrant, backing, and qualifier when present
- infer `domain_standard` and generate the contrary claim

Important detail: user-provided grounds are preserved verbatim and treated as stipulated true by the Constructor, because they may come from private records that are not publicly verifiable.

### Constructor

Basis: Toulmin.

The Constructor builds the strongest defensible case for the claim. It is allowed to retrieve additional grounds, strengthen a weak warrant, and add backing. It does not see `domain_standard`, attacks, rule violations, or verdicts.

### Critique Bundle

Basis: Walton + pragma-dialectics.

The Critique Bundle classifies the warrant's argument scheme, attaches critical questions, converts unanswered questions into neutral `open_attacks`, and checks whether the exchange is procedurally fit to continue. If not, it emits one canonical `Required:` gap string.

### Evaluator

Basis: Perelman & Olbrechts-Tyteca.

The Evaluator is the only stage that sees `domain_standard`. It asks whether the relevant universal audience would act on the argument as it currently stands. If not, it emits one canonical `Required:` gap string.

### Resolver

Basis: Dung + ASPIC+.

The Resolver treats attacks, blocking violations, and unresolved gaps as live attacks on the claim. It returns one of three verdicts:

- `survives`
- `defeated`
- `impasse`

## Modes

Gauntlet has one global runtime mode, configured with `GAUNTLET_MODE`.

Valid values:

- `base`
- `clinical`
- `financial`

If `GAUNTLET_MODE` is unset, Gauntlet defaults to `base`. If it is set to anything else, startup fails fast.

Mode affects only the two tool-using stages and a small runtime prompt cue. It does not change the public API shape.

| Mode | Extra tools | Notes |
|---|---|---|
| `base` | none | Default mode |
| `clinical` | `pubmed_search` | Placeholder for PubMed-style clinical retrieval |
| `financial` | `finance_search` | Placeholder for finance-specific retrieval |

Current tool surface:

- `web_search`: Tavily-backed web search
- `fetch_document`: fetch a known URL
- `pubmed_search`: placeholder only in this version
- `finance_search`: placeholder only in this version

Only Constructor and Evaluator can use tools. Critique Bundle and Resolver are always tool-free.

## Quickstart

### Requirements

- Python 3.11+
- an OpenRouter-compatible API key
- optionally, a Tavily API key if you want `web_search` to work

### Install

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate

pip install -e .
# or, for tests:
pip install -e .[dev]
```

### Configure

Create a `.env` from `.env.example` or export environment variables directly.

Minimal configuration:

```env
OPENROUTER_API_KEY=your-openrouter-api-key
GAUNTLET_PRIMARY_MODEL=anthropic/claude-opus-4-6
GAUNTLET_PREFLIGHT_MODEL=anthropic/claude-haiku-4-5
GAUNTLET_MODE=base
```

Optional:

```env
TAVILY_API_KEY=your-tavily-api-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
GAUNTLET_HOST=0.0.0.0
GAUNTLET_PORT=8000
GAUNTLET_RELOAD=false
```

Legacy compatibility: `GAUNTLET_FAST_MODEL` is still accepted as a fallback alias for `GAUNTLET_PREFLIGHT_MODEL`.

### Run

```bash
gauntlet
```

or:

```bash
python -m gauntlet
```

The API binds to `0.0.0.0:8000` by default and is typically reached at `http://127.0.0.1:8000`.

Health check:

```text
GET /v1/health
```

The health response reports:

- `status`
- `version`
- `mode`
- `primary_model`
- `preflight_model`
- `tavily`

### Test

```bash
pytest -q
```

## API

### `POST /v1/evaluate`

Synchronous evaluation.

Request body: a single JSON string, not an object.

```json
"Implement mandatory 2FA for all admin routes."
```

If the input is invalid, the API returns `422`.

Important failure cases:

- empty input
- prompt-injection-like input
- no testable argumentative claim
- multiple atomic claims

If multiple atomic claims are detected, Gauntlet stops immediately and returns the list it identified.

### `POST /v1/evaluate/async`

Starts the same evaluation asynchronously and returns a `job_id`.

### `GET /v1/jobs/{job_id}`

Returns async job status and result.

### `DELETE /v1/jobs/{job_id}`

Deletes an async job record.

## Response Shape

The top-level response includes:

- `claim_evaluation`
- `contrary_evaluation`
- `comparison`
- `recommended_position`
- `inferred_domain_standard`
- `total_usage`

Each `ClaimEvaluation` includes:

- `claim`
- `verdict`
- `final_argument`
- `issues`
- `required_gap`
- `rebuttal_log`
- `trace`
- `usage`

Comparison outcomes:

- `definite_conclusion`
- `wrong_starting_position`
- `equipoise`
- `insufficient_evidence`

## Repository Layout

```text
src/gauntlet/
  api.py            FastAPI app
  config.py         env-driven runtime config
  client.py         OpenRouter client and structured output handling
  orchestrator.py   preflight + bipolar pipeline orchestration
  parsing.py        atomic-claim parsing and Toulmin extraction
  validation.py     request guardrails
  tools.py          tool registry and mode-gated tool lists
  trace.py          hierarchical trace accumulation
  agents/
    constructor.py
    critique.py
    evaluator.py
    resolver.py
```

## Current Limitations

- `clinical` and `financial` mode currently add placeholder tools, not live MCP integrations.
- The request contract is intentionally narrow: one string, one atomic claim.
- The service is optimized for deliberation, not formal proof generation.
- The system may conclude `impasse` or `insufficient_evidence`; it is allowed to fail closed.

## References

- [Isa Watanabe, "Argumentation for AI [Part 1]: The Limits of Formal Reasoning"](https://medium.com/@isaiahwatanabe/argumentation-for-ai-part-1-the-limits-of-formal-reasoning-aa4edab90231)
- [Stephen Toulmin, *The Uses of Argument*](https://en.wikipedia.org/wiki/The_Uses_of_Argument)
- [Chaim Perelman and Lucie Olbrechts-Tyteca, *The New Rhetoric*](https://www.britannica.com/biography/Chaim-Perelman)
- [Douglas Walton, Chris Reed, and Fabrizio Macagno, *Argumentation Schemes*](https://en.wikipedia.org/wiki/Argumentation_scheme)
- [Frans H. van Eemeren and Rob Grootendorst, pragma-dialectics](https://iep.utm.edu/argumentation-theory/)
- [Phan Minh Dung, "On the Acceptability of Arguments and Its Fundamental Role in Nonmonotonic Reasoning, Logic Programming and n-Person Games"](https://doi.org/10.1016/0004-3702(94)00041-X)
- [Henry Prakken and Sanjay Modgil, ASPIC+ structured argumentation](https://link.springer.com/article/10.1007/s10472-011-9285-0)
- [Hugo Mercier and Dan Sperber, "Why do humans reason? Arguments for an argumentative theory"](https://pubmed.ncbi.nlm.nih.gov/27450708/)
- [Donald Schon, *The Reflective Practitioner*](https://www.taylorfrancis.com/books/mono/10.4324/9781315237473/reflective-practitioner-donald-schon)
