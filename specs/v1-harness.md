---
implementation_paths:
  - pyproject.toml
  - LICENSE
  - NOTICE
  - README.md
  - CONTRIBUTING.md
  - CODE_OF_CONDUCT.md
  - SECURITY.md
  - DESIGN.md
  - design/**
  - .github/**
  - .claude-plugin/**
  - skills/**
  - agents/**
  - src/rqharness/**
  - tests/**
  - evals/**
  - examples/**
---

# Spec: risk-quantification-harness v1

> Origin: "prompt" — refactor of an earlier prototype into an open-source, skill-based harness · Designed 2026-11-09 · Review status: **draft** · Critic: 15 findings, all applied (2 mechanical, 13 design edits recorded as D26 and D27), none declined · Review: 2 findings (the skill chain; evals for every skill), applied as D28 and D29
> Visual: specs/v1-harness.plan.html

## Summary

`risk-quantification-harness` is an Apache-2.0 Claude Code plugin plus a Python package (`rqh` command). Given a scenario sentence, it produces one self-contained HTML risk report. A front-door router asks `rqh` which phase comes next and invokes the phase skill that owns it — scope, collect, simulate, report — so each skill hands off to the next through files in the workspace, never through the conversation. Scoping ends with one structured question that confirms the scenario and chooses a route. **YOLO** fills every parameter from benchmarks and runs straight to the report. **Accuracy** routes each parameter to the people, systems and connectors in the user's organisation, tracks the asks across sessions and finalizes whenever the user chooses. The decision the reviewer must not miss is the split of authority: skills converse and propose, but `rqh` alone validates, simulates, computes every number, enforces every status transition and writes the report. Every figure in a report comes from a placeholder resolved by `rqh`; prose that states a figure on its own is rejected.

## Problem

Security and risk analysts who want a defensible annualized loss estimate today drive four hand-gated subagents in an earlier prototype. Each handoff loses context, there is no path from "give me a quick estimate" to "make it defensible", and output is scattered across markdown, PNGs and a wiki. This spec defines the open-source v1: skills instead of phase agents, two data routes, a local memory of real figures, and a single HTML deliverable. Portfolio aggregation across scenarios, non-PERT loss distributions, a converter for runs from the earlier prototype, and any hosted service are out of scope.

## Constraints

| Constraint | Value | Source | Detected by |
|------------|-------|--------|-------------|
| Every reader-facing number is computed | narrative prose reaches the report only through `{{…}}` placeholders resolved from `run_summary.json`; a literal currency amount, percentage or magnitude-suffixed number in prose fails the render | user | `tests/test_narrative.py` |
| The report is self-contained | `report.html` loads nothing over the network. No `src`, `srcset`, `href`, `xlink:href`, `@import` or `url()` holds an `http(s):` or protocol-relative `//` reference, except `https://` citation anchors. The page carries `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'sha256-<digest>'; base-uri 'none'; form-action 'none'">`, where `<digest>` is the base64 SHA-256 of the inlined `report.js`, so that exact script is the only one that runs (styles stay inline because the charts and bars carry style attributes), and the two-variant sample report stays at or under 1 MB | user | `tests/report/test_render.py::test_self_contained` |
| Simulation speed | `n = 50,000` iterations for a baseline plus two variants completes in under 5 s on a GitHub-hosted `ubuntu-latest` runner, at a load of up to 10 expected events per iteration with six primary loss forms and secondary loss on, where the variants override only frequency or vulnerability; slice 3 measures this before the number is committed | inferred | `tests/engine/test_perf.py::test_perf_budget` on that load fixture |
| Reproducibility | identical inputs, `n`, seed, package version and NumPy and SciPy versions on the same platform produce a byte-identical `run_summary.json`; the manifest records all four versions | user | `tests/engine/test_engine.py::test_reproducible` |
| Default run parameters | `rqh run confirm` stores `n = 50,000` and a seed from `secrets.randbits(63)` in `run.yaml` unless given, so the gate shows the values `finalize` uses. `n` is at most 10,000,000 (run schema; `finalize --n` is held to the same bound). Every version of a run reuses that seed unless `finalize --seed` overrides it, and both values are recorded in the manifest. A repeated confirm of a `collecting` run with a different `--n` or `--seed` exits 3 and names `rqh run rescope`, never ignoring the flags | user | `tests/finalize/` |
| One human gate in YOLO | after the scoping interview, exactly one structured question per confirmation pass (scenario, route, `n` and seed). A declined confirmation returns to scoping and starts a new pass. YOLO never runs inline org setup: without a profile, the closing section names owner roles from the connector map | user | live eval suite (`evals/live/yolo`, the question counted on the reply by an `llm` grader, because an eval run offers no structured question tool), required by the release workflow; the guardrail lint in CI |
| Connectors are read-only | skills call only search and read tools of host connectors; messages to people are drafts the user sends | user | live eval suite (`evals/live/accuracy`) asserts no send-type Bash call (an eval run loads no connectors) and that the reply shows the drafts unsent, required by the release workflow; the guardrail lint in CI |
| A found figure is a candidate | figures found in connectors or received in answers enter `inputs.yaml` only through `rqh candidates confirm` | user | `tests/test_requests.py::test_candidate_never_in_inputs` |
| Workspace is private by default | `rqh init` writes `.riskquant/.gitignore` containing `*` | user | `tests/test_workspace.py` |
| Memory holds derived figures only | library entries carry a value, a pointer to the source and a sensitivity flag; the schema has no field for raw exports and caps `note` at 500 characters | user | `tests/test_library.py` |
| No telemetry | the package opens network connections only in `rqharness.search` (optional Tavily) | user | `tests/test_no_network.py` scans imports of `urllib`, `http.client`, `socket`, `requests` |
| Untrusted text is escaped | every scenario, source and narrative string is HTML-escaped in the report (Jinja2 autoescape); `Source.url` must match `^https://` and `theme.logo_data_uri` must match `^data:image/(png\|jpeg\|svg\+xml);base64,` | inferred | `tests/report/test_render.py::test_escapes_markup`; schema patterns in `tests/validate/` and `tests/state_schemas/` |
| Currency and time | `inputs.yaml` declares one ISO 4217 `currency`; every amount estimate's `unit` and every variant `annual_cost` must equal it (no FX conversion in v1), and every amount in `run_summary.json` carries it. Timestamps are UTC ISO 8601 with `Z` | inferred | currency rule in `tests/validate/`; schema patterns |
| Reader-facing wording | templates and skills say "estimate", never "SWAG"; descriptions say "FAIR-aligned" and the package and plugin names do not contain "FAIR" | user | `tests/test_wording.py` |
| Python and dependencies | Python ≥ 3.11; runtime dependencies are `numpy`, `scipy`, `jsonschema`, `PyYAML`, `Jinja2` (≥ 3.1.6) and `MarkupSafe` (imported directly by the report); `matplotlib` is gone | inferred | `pyproject.toml` review; CI install on three operating systems |
| Host support | Claude Code first-class and tested; Cursor and Codex read the same skill files, which fall back to numbered options when no structured question tool exists, and the router reads `skills/<next_skill>/SKILL.md` and follows it when the host cannot invoke a skill | user | `tests/test_skill_guardrails.py::test_question_fallback_present`; `tests/plugin/test_router.py` |
| Skills hand off through the workspace | a phase skill starts from the run's files and `rqh status`, ends by naming the next skill `rqh status` reports, and never invokes another phase skill; only the router chains phases | user | `tests/plugin/test_router.py`; `tests/skill_guardrails/`; the replays in `evals/` |
| Consistency between writers | a skill re-reads `inputs.yaml` after any `rqh` command that writes it, before editing it again; a workspace has one active session, so no other consumer reads concurrently | inferred | `tests/skill_guardrails/` re-read rule |
| Rollout and rollback | the package is versioned semver and the plugin manifest `version` equals the package version; rollback is installing the previous version, since no workspace format migrates in v1 | inferred | `tests/test_plugin_manifest.py::test_versions_match` |

## System design

### Ownership

| Component | Owns (source of truth for) | Reads |
|-----------|----------------------------|-------|
| Skills (`skills/*/SKILL.md`, `agents/benchmark-researcher.md`) | the conversation; the router loop that invokes the next skill; which questions to ask; drafted messages; narrative prose; proposed estimates before the user accepts them | everything `rqh` prints as JSON; connector and web search results |
| `rqh` (`src/rqharness`) | validation rules; run status and its transitions; which skill comes next (`next_skill`); request and candidate status; version numbering; simulation results; statistics, sensitivity and the data-quality grade; the rendered report | workspace files; shipped data |
| `scenario.yaml`, `inputs.yaml` (per run, written by skills, validated by `rqh`) | the scenario narrative; every model parameter and its provenance; variants. `rqh candidates confirm` is the only other writer of `inputs.yaml`, and it changes only the confirmed parameter path and its source row | — |
| `run.yaml` (per run, written only by `rqh`) | route, per-parameter route overrides, run status | version directories |
| `requests.yaml` (per run, written only by `rqh`) | data requests, their status, answers and candidates | — |
| `v<N>/` directories (written only by `rqh`) | the frozen snapshots of inputs, scenario and theme; the manifest, summary and draws; the stored narrative and the report of version N; which versions exist. Rendering reads nothing outside `v<N>/` | — |
| `.riskquant/library/` (written only by `rqh library add`) | the organisation's memory of real figures | — |
| `.riskquant/org-profile.yaml` (written by skills, validated by `rqh`) | teams, owner roles, people, systems of record, report theme | — |
| Shipped data (`src/rqharness/data/`) | seeded benchmark entries; the connector map | — |
| Host connectors and web search | external facts | — |

### Interaction

```flow
caption: The router loop — rqh names the next skill from the run's state, the router invokes it, then asks again
User -> risk-quant router : (1) scenario sentence or run id, answers
risk-quant router -> rqh : (2) status --json returns next_skill; init when no workspace
risk-quant router -> scope-scenario : (3) next_skill
risk-quant router -> collect-data : (3) next_skill
risk-quant router -> simulate : (3) next_skill
risk-quant router -> report : (3) next_skill
risk-quant router -> risk-quant-memory : (4) end-of-run batch, once after report
```

```flow
caption: Every state change goes through rqh — each phase skill calls it, and only rqh writes the workspace and the report
scope-scenario -> rqh : (5)
collect-data -> rqh : (5)
simulate -> rqh : (5)
report -> rqh : (5)
risk-quant-memory -> rqh : (5)
rqh -> Workspace files : (9) atomic writes
rqh -> Tavily API : (10) optional search
rqh -> report.html (new) : (11) render
```

```flow
caption: What collect-data reaches outside rqh — researchers on the YOLO route; connectors and inline org setup on the Accuracy route
collect-data --> benchmark-researcher (new) : (6) YOLO, at most 4
collect-data -> Host connectors : (7) Accuracy, read-only
collect-data -> risk-quant-org-setup : (8) Accuracy, inline
```

| Arrow | Mode | On timeout | On duplicate |
|-------|------|------------|--------------|
| (1) | sync | the conversation waits; nothing is written until the user answers | a repeated answer is idempotent: the skill rewrites the same YAML field |
| (2) | sync | a local read bounded by the speed constraint; exit 5 for a missing workspace makes the router run `rqh init` once, and any other non-zero exit is shown to the user and ends the loop | pure read; `rqh init` is idempotent |
| (3) | sync | a skill that stops for the user returns with the run status and `next_skill` unchanged, and the router ends the loop instead of invoking it again | invoking a phase skill again on an unchanged state is safe: each skill starts from the run's files and `rqh status`, and writes YAML by field |
| (4) | sync | when the session ends before the batch, it is skipped; the user can run `risk-quant-memory` later | `rqh library add` is idempotent by entry id and content hash |
| (5) | sync | the commands each phase skill runs are listed in § Skill chain and hand-offs. Not applicable to local commands bounded by the speed constraint; a non-zero exit is shown to the user and the phase stops | every command is idempotent except `finalize`, which creates a new version each time; a run-level `.lock` file created exclusively makes a second concurrent `finalize`, or any run-state write during one, exit 1 once a short wait (about 2 seconds) for the lock runs out |
| (6) | async | fan-out of at most 4 researchers, YOLO parameters only. A researcher works within a budget of 12 tool calls and returns what it found; a parameter group with no usable cited result falls back to the shipped library, else to `agent_assumption`, and the gap is named in the report. The host offers no wall-clock deadline for subagents, so the budget is the bound | results are merged by parameter path; the later result for the same path is discarded |
| (7) | sync | read-only search, Accuracy parameters only. A connector call that errors or exceeds the host's tool timeout is not retried in that pass: the skill says so in one line, and the parameter keeps its current route | the same finding is de-duplicated by source link before a candidate is created |
| (8) | sync | inline, Accuracy only. Org setup asks only for the teams and owners the run's parameters need; an unanswered question leaves the profile unchanged, and the route names owner roles without people | rewrites the same profile fields |
| (9) | sync | not applicable | writes go to a temporary file and `os.replace`; a version is written to `v<N>.tmp/` and renamed to `v<N>/` |
| (10) | sync | 60 s timeout, exit 1; the skill falls back to host web search | a repeated search is harmless and stores nothing |
| (11) | sync | not applicable | rendering a version again from its stored narrative produces identical bytes, because rendering reads only `v<N>/` |

### Skill chain and hand-offs

The router repeats one step: run `rqh status <run> --json`, invoke the skill named by `next_skill`, and ask again. It stops when `next_skill` is null, when a skill returns with the run status and `next_skill` unchanged (the skill stopped for the user), or when the user ends the session. After `report` returns inside the loop, the router invokes `risk-quant-memory` in batch mode once. A phase skill ends by naming the next skill from `rqh status`. When the router invoked it, that line hands back to the router, which carries on in the same reply; a phase invoked directly by the user stops there, so the chain can also be driven by hand, and a later session restarts it from wherever the run stands.

| Skill | Starts when | Reads | Writes | Leaves the run | Asks the user |
|-------|-------------|-------|--------|----------------|---------------|
| `risk-quant` (router) | the user gives a scenario sentence or a run id | `rqh status` | nothing; runs `rqh init` when the workspace is missing | unchanged | nothing of its own |
| `scope-scenario` | `next_skill` is `scope-scenario` | the scenario sentence; `org-profile.yaml` when present | `scenario.yaml`; then `rqh run confirm --route`, which creates or updates `run.yaml` | `collecting` | the scoping interview, then one structured question: scenario, route, `n` and seed |
| `collect-data` | `next_skill` is `collect-data`, or `risk-quant-resume` enters it for an `awaiting_data` run | `scenario.yaml`, `inputs.yaml`, `rqh status`, `rqh library search`, routes from `rqh` | `inputs.yaml`; requests and candidates through `rqh requests` and `rqh candidates`; per-parameter routes through `rqh run route`; `rqh run pause` or `rqh run resume` | `collecting` with valid inputs and no pending candidate, or `awaiting_data` | YOLO: nothing. Accuracy: the asks to draft, candidate confirmation, and whether to finalize now or wait |
| `simulate` | `next_skill` is `simulate` | `n` and seed from `rqh status` | `rqh finalize` | `finalized`, with a new `v<N>/` | nothing |
| `report` | `next_skill` is `report` | `v<N>/run_summary.json` | `narrative.draft.md`, then `rqh report --narrative` | `finalized`, with `v<N>/report.html` | nothing |
| `risk-quant-memory` | batch: invoked once by the router after `report`; browse, add and prune: invoked by the user | the run's confirmed `internal_data` and `sme_estimate` parameters | `rqh library add` for each approved item | unchanged | one yes or no per item |
| `risk-quant-org-setup` | invoked by the user, or inline by `collect-data` on the Accuracy route with the minimal scope the run needs | read-only connectors | `org-profile.yaml`, validated by `rqh validate` | unchanged | teams, owners and people |
| `risk-quant-resume` | the user names a run to resume | `rqh status` | nothing | unchanged; it enters the router loop, invoking `collect-data` first when the run is `awaiting_data` | nothing of its own |

### Failure unit

A failing `rqh` command stops only the phase that called it; earlier versions and their reports stay intact. A failing connector or researcher affects only the parameters it was asked about. Tavily is optional, and its absence never stops a run. A phase skill that stops leaves the run in a state `rqh status` names, so the chain restarts from that skill in any later session.

## Component contracts

### CLI envelope (`rqh <command> --json`)

```python
class Envelope(TypedDict):
    schema_version: Literal["1"]
    ok: bool
    data: dict | None        # present when ok
    issues: list[Issue]      # present when not ok; Issue = {"path": str, "rule": str, "message": str}
```

| Exit code | Meaning | Failure kind (`rqharness.outcomes`) |
|-----------|---------|------------------------------------|
| 0 | success | — |
| 1 | validation or rejection; `issues` names every dotted field path | `Rejected` |
| 2 | usage error: an argument or environment value unusable as given (`argv.*`, `env.*`) | `Usage` |
| 3 | illegal status transition | `IllegalTransition` |
| 4 | narrative rejected | `NarrativeRejected` |
| 5 | required artifact missing | `NotFound` |

A domain function returns its success value and raises one of the five kinds, each a `DomainError` carrying its `issues`, when it cannot deliver it; success results such as `Added`, `Duplicate` and `Updated` stay returned values. `rqharness.outcomes` is a leaf that knows no exit code: `cli.EXIT_CODES` is the only map from a kind to its exit code and `cli.main` the only handler, so the same kind exits the same way from every command. `ValueError` remains for programmer errors only. An out-of-range `--n` or `--seed` is `Usage` (issue at `argv.<flag>`, rule `range`) from `rqh run confirm` and `rqh finalize` alike, checked before anything is read (D31).

Skills parse the envelope, never human-readable output. A future major version changes `schema_version`, and a v1 skill refuses an envelope whose major version it does not know.

### `rqharness.validate.validate_run`

```python
def validate_run(run: Run) -> ValidationReport: ...
def validate_inputs(data: object, *, entry_lookup: library.EntryLookup) -> list[Issue]: ...
def missing_document(path: Path) -> Issue: ...  # <stem>.document / missing, "<name> is missing from <parent>"
# ValidationReport(ok: bool, issues: list[Issue], contents: RunContents, scenario: dict | None,
#                  inputs: dict | None, readiness: ReadyRun | list[Issue]), plus documents: list[str],
#                  readiness_issues: list[Issue] and ready() -> ReadyRun
# RunContents(scenario: bytes | None, inputs: bytes | None): the run's documents, read once by validate_run
# scenario / inputs: those bytes parsed once, each None unless the document is present and passes its own
#   checks (parse, schema and, for inputs, the cross-reference rules); documents: the stems present in contents
# readiness: the one readiness rule, "the run validates and both documents are present", held in
#   one field: the ReadyRun, or the non-empty list of reasons, which is the issues, then
#   missing_document(<run>/inputs.yaml) when inputs.yaml is absent (an empty list is a ValueError).
#   readiness_issues is that list, or [] for a ready run. chain.next_step says `simulate` only when it is
#   empty, and rqh finalize rejects with it otherwise
# ready(): ReadyRun(scenario_bytes: bytes, inputs_bytes: bytes, inputs: dict) plus inputs_model: ModelInputs,
#   load_model_inputs(inputs) loaded on first use (D30), none of them ever None; raises Rejected(readiness_issues)
#   when the run is not ready. validate_run builds the ReadyRun, where it holds the documents it checked
# A caller that uses a document takes it from the report, never from a second read:
# rqh finalize snapshots and simulates ready(); rqh run confirm records scenario
# The missing-document issue is built only by missing_document: validate_run (scenario and inputs) and
#   requests.confirm_candidate (inputs)
# Run(workspace: Path, dir: Path), from rqharness.workspace: dir is <workspace>/runs/<id>/
# entry_lookup is library.entry_lookup(workspace): validate_run binds run.workspace;
# `rqh validate <inputs file>` binds the workspace resolve_run would use, or None when it does not exist
```

| Aspect | Contract |
|--------|----------|
| Inputs | a `Run`, from `cli.resolve_run`, whose directory holds `scenario.yaml` and, after scoping, `inputs.yaml`; `memory` sources resolve against the run's own workspace library. `resolve_run` refuses a directory outside `<workspace>/runs/` with `Usage`, exit 2 (issue rule `outside_workspace`), so no workspace file is ever read from the folders above a copied run |
| Outcomes | `ok = True`, or every JSON Schema error plus every cross-reference rule: `source_ids` resolve; a `benchmark` tier has a `web` or `benchmark_library` source with a URL; an `internal_data` tier has a `person` or `internal_system` source, or a `memory` source whose library entry has tier `internal_data`; an `sme_estimate` tier has a `person` source, or a `memory` source whose entry has tier `sme_estimate` or better; an `agent_assumption` tier has a rationale; every amount `unit` and every `annual_cost` equals the declared `currency`; each variant override targets an estimate present in the baseline; `min ≤ mode ≤ max`; `engine.expected_events` on the estimates' maxima (the product of the frequency estimates' maxima × `analysis_period_years`, a threat-capability share counted as 1), in the baseline and in each variant that overrides an estimate it reads, and every `slef` max are at most the engine's `MAX_EVENT_MEAN` (63,000), so its 16-bit event ordinals cannot overflow (`expected_events`) |
| Raises | only on I/O faults; malformed YAML becomes an issue at path `document`, and so does a YAML alias: every workspace document is parsed with a loader that refuses aliases, so a shared file cannot expand into billions of nodes, and `rqh` writes none; the issue names the way out for a file an older `rqh` wrote with aliases (re-save it without anchors), and the input files of `requests add`, `requests update` and `candidates add` go through the same loader |
| Idempotency | pure |
| Versioning | each file carries `schema_version: "1"`; an unknown major version is one issue |

### `rqharness.engine.simulate`

```python
def simulate(model: ModelInputs, *, n: int, seed: int) -> SimulationResult: ...
# ModelInputs is constructed only by load_model_inputs() after validate_run passes.
# SimulationResult: per variant id -> annual_loss, lef, event_count arrays; per-parameter iteration statistics for sensitivity.
```

| Aspect | Contract |
|--------|----------|
| Inputs | validated inputs; `n ≥ 1`; `seed` a non-negative 63-bit integer |
| Semantics | ported from an earlier prototype's engine semantics: four frequency models, two vulnerability models, events drawn as Poisson(LEF × years), per-event primary loss, secondary loss Poisson per primary event with a rate drawn once per iteration, and annual loss equal to horizon loss divided by years. Beta-PERT with γ = 4 |
| Stream keys | each stream key is the first four little-endian `uint32` words of `blake2b(name.encode("utf-8"))`, a value that is stable across processes and platforms. Python's salted `hash()` is never used. Named streams are one per estimate path, plus `events` (the per-iteration event count N) and `secondary_events` (the per-event secondary count k) |
| Common random numbers | every draw is the inverse CDF of a uniform that depends only on (stream, iteration, event ordinal): `Philox` keyed by the stream key, with counter `iteration × 2³² + ordinal`. A 53-bit output x maps to `(x + ½) × 2⁻⁵³`, with the top clamped to `engine.LARGEST_UNIFORM`, the largest float below 1, so every uniform lies in [2⁻⁵⁴, 1 − 2⁻⁵³] and no inverse CDF sees 0 or 1. Only x = 2⁵³ − 1 is clamped; it used to round to exactly 1.0, which crashed a count above mean 30 but gave a result in a PERT stream or a smaller count, and those draws may now differ. At about 2⁻⁵³ per draw this was accepted without changing `STREAM_RULE`. N is `poisson.ppf(u_events[i], LEF × years)`; per-event magnitudes and k use the uniform at (i, j). The j-th event of iteration i therefore gets the same uniforms in every variant, and a variant differs from the baseline only through the estimates it overrides |
| Reuse | magnitudes are computed once for the maximum event count across variants in each iteration; a variant that overrides no magnitude estimate reuses the baseline's magnitudes for its first N events |
| Vectorisation | NumPy array operations across iterations and a padded `[n, max_events]` layout. The earlier prototype's pure-Python per-event loop is not ported |
| Raises | `ValueError` for a programmer error (`n < 1`, a seed out of range, a `poisson_inverse` uniform outside the open interval (0, 1)) and for an iteration with 65,536 or more events, or a primary event with that many secondary events. The inputs are not re-checked: the engine trusts validated documents (D30) |
| Idempotency | pure and deterministic for identical arguments |

### `rqharness.finalize.finalize`

```python
def finalize(run: Run, *, n: int | None = None, seed: int | None = None) -> Finalized: ...
# Finalized(version: int, path: Path, n: int, seed: int); raises outcomes.Rejected · outcomes.IllegalTransition
```

| Aspect | Contract |
|--------|----------|
| Behaviour | takes the run's `.lock` (exclusive create), reads `inputs.yaml` and `scenario.yaml` once, validates those bytes, then snapshots the same bytes and the org-profile theme and simulates from them, so a write to the run after validation never reaches the version and `inputs_sha256` hashes the validated bytes. It simulates with the `n` and seed from `run.yaml` unless overridden, writes `run_manifest.json`, `run_summary.json` and `draws.npz` into `v<N>.tmp/`, renames that to `v<N>/`, sets the run status to `finalized` and releases the lock |
| Outcomes | `Finalized`; raises `Rejected` (exit 1) when the run is not ready (`ValidationReport.readiness_issues`: validation fails, or the run has no `inputs.yaml`, issue `inputs.document` / `missing` from `missing_document`; `validate_run` itself stays lenient about inputs, so `rqh validate` passes on a run still collecting them), the org profile is invalid, the lock is held, or the run would need more than `engine.MAX_EVENT_CELLS` event cells (D32), and `IllegalTransition` (exit 3) from `scoping`, with the refusal `runstate.check` gives; none of them writes anything |
| Recovery | the run `.lock` is taken before the status check and held through the status write, and every other writer of `run.yaml`, `requests.yaml` or candidates takes it too (`runstate.locked`), so a status change during a simulation exits 1 (`lock_held`) instead of making finalize exit 3 after it wrote `v<N>/`. Once the lock is taken, any leftover `v<N>.tmp/` is a crash remnant and is deleted; a remnant that is a link is unlinked, and in a run directory that is itself a link a remnant is refused with `Rejected` (`run.dir` / `linked_run`) instead of being deleted through it. The holder touches the lock every minute, so only a lock untouched for 10 minutes is stale; a writer waits up to about 2 seconds for a held lock before it exits 1, so brief contention between parallel `rqh` writers is waited out, and a lock released between its failed create and the stale check is retried; a stale lock is broken only under a second exclusive guard file (`.lock.break`) after a second staleness check, and a holder deletes only the lock or guard that carries its own token. A spent journal that a concurrent reader keeps from being deleted is emptied instead, so it never fails the write it followed. The latest version is the highest complete `v<N>/`, never a value cached in `run.yaml`. The rename and the status write are one `runstate.publish`: a journal (`.pending-status.yaml`) names the trigger before the rename and is removed after the status write, so after a crash between the two the run reads as `finalized` (the router asks for the report of `v<N>`, `rqh finalize` exits 3 and writes no duplicate), and the next locked write records the status; a journal whose trigger no longer fires is discarded, so reopen-then-finalize still creates `v<N+1>` |
| Idempotency | not idempotent by design: each successful call is a new version |

### `rqharness.report.render_report`

```python
def render_report(run_dir: Path, version: int | None = None, *, narrative: Path | None = None,
                  omit_narrative: bool = False) -> Rendered: ...
# Rendered(path, version: int, narrative_omitted: bool); raises outcomes.NarrativeRejected (issue at narrative.line.<n>)
#   · outcomes.Rejected (a run_summary.json whose currency is not ^[A-Z]{3}$) · outcomes.NotFound
```

| Aspect | Contract |
|--------|----------|
| Inputs | a complete `v<N>/` only. A `--narrative` file passed on the command line is validated and stored as `v<N>/narrative.md`; later renders use the stored copy |
| Placeholder grammar | `{{ <variant>.<metric>.<stat> }}`, `{{ delta.<variant>.<metric>.<stat> }}` and `{{ quality.grade }}`. Metrics are `annual_loss`, `lef` and `event_count`; stats are the summary's statistics. An optional `\|money`, `\|pct`, `\|rate` or `\|int` format applies; an unknown placeholder is rejected |
| Literal rule | outside placeholders, prose is rejected when it holds a digit next to a currency symbol or ISO code, `%`, `percent` or `per cent`, a currency word (`dollars`, `euros`, `pounds`), a magnitude suffix (`k`, `m`, `bn`, `million`, `billion`) or a multiplier (`3x`); a ratio or rate pattern (`1 in 20`, `every 5 years`); or a spelled-out number from `two` upward or a magnitude word (`hundred`, `thousand`). Plain digits such as years or "top 3" pass |
| Second failure | the skill rewrites once with placeholders. If the retry is also rejected, it renders with `omit_narrative=True`: the takeaway becomes a fixed sentence built from placeholders, and the report notes that the narrative was omitted. YOLO therefore always ends with a report |
| Outcomes | `Rendered`; raises `NarrativeRejected` (exit 4) for a narrative that breaks the literal rule, whether passed with `--narrative` or stored as `v<N>/narrative.md` (a stored narrative that no longer validates is exit 4 on re-render, never printed), `Rejected` (exit 1) for a `run_summary.json` whose `currency` is not `^[A-Z]{3}$`, since the currency is printed into the page, or `NotFound` (exit 5) for a missing version, version file or narrative file; a rejected render writes no file |
| Idempotency | identical `v<N>/` contents give identical bytes |

```sequence
caption: Report rendering when the narrative contains a literal figure
participant skill
participant rqh
participant v<N>/
skill -> rqh : rqh report run --json
rqh -> v<N>/ : read manifest, summary
alt narrative uses placeholders only
rqh -> v<N>/ : write report.html
rqh --> skill : ok, path
else literal figure in prose
rqh --> skill : exit 4, line and token
skill -> rqh : retry once with placeholders
alt retry rejected
skill -> rqh : rqh report run --omit-narrative
rqh --> skill : ok, narrative omitted
end
end
```

### `rqharness.requests` and candidates

```python
def add_request(run_dir: Path, req: NewRequest) -> Added | Duplicate: ...  # idempotent by (parameter_path, owner_role, person) among open requests
def transition_request(run_dir: Path, request_id: str, to: RequestStatus, *, answer: Answer | None = None) -> Updated: ...
def add_candidate(run_dir: Path, cand: NewCandidate) -> Added | Duplicate: ...       # de-duplicated by (parameter_path, source link)
def confirm_candidate(run: Run, candidate_id: str) -> Confirmed: ...
# each raises outcomes.NotFound (unknown id), outcomes.IllegalTransition (a move the status tables refuse)
# or outcomes.Rejected (a document that would not validate)
```

| Aspect | Contract |
|--------|----------|
| Effects | an `answered` transition records the answer and creates a `pending` candidate. `confirm_candidate` writes the value into `inputs.yaml` at the candidate's parameter path and adds a `sources[]` row. The tier is `internal_data` when the candidate's `evidence_kind` is `measured`, and `sme_estimate` when it is `judgement`. When the last open request of a run in `awaiting_data` reaches a terminal status, `transition_request` moves the run to `collecting` |
| Idempotency | a repeated transition to the current status returns `Updated` with no change (the CLI envelope says `result: unchanged`, where a write says `updated`; rejecting a rejected candidate is the same), and still moves an `awaiting_data` run with no open request to `collecting`, so a retry finishes an interrupted auto-resume; a repeat whose answer differs from the recorded one (its value, note or evidence kind) is `IllegalTransition` (exit 3, rule `answer_recorded`), never silently dropped, and an answer on a repeat to any status but `answered` is `Rejected` (`answer_status`), as on a first move. A closed request (`answered`, `unavailable`, `withdrawn`) is not a duplicate of a new ask. Candidates are idempotent by key |
| Finalized runs | every write is refused with `IllegalTransition` (exit 3, path `run.status`, a message naming `rqh run reopen`) while the run is `finalized`, except withdrawing a request; every write holds the run lock |
| One confirmed value | confirming a candidate for a parameter that already has a confirmed candidate is `IllegalTransition` (exit 3, rule `already_confirmed`); the user rejects the newcomer or edits that estimate in `inputs.yaml` |
| Malformed file | `load` validates `requests.yaml`; malformed YAML or a schema error is `Rejected` (exit 1) with issues at `requests.*`, from `rqh status` too |
| Write order | `confirm_candidate` writes `inputs.yaml` first (value plus a source row whose id is the candidate id), then sets the candidate to `confirmed`. A crash between the two leaves a `pending` candidate whose value is already in place; confirming again rewrites the same value and source id, so the retry is safe |
| CLI | `rqh requests add\|update\|list`, `rqh candidates add\|confirm\|reject`, and `rqh status`, which lists open requests, pending candidates and parameters still on `benchmark` or `agent_assumption` tiers, and returns `next_skill` (see `rqharness.chain.next_step`) |

```sequence
caption: Accuracy resume after a connector times out
participant user
participant risk-quant-resume
participant collect-data
participant connector
participant rqh
user -> risk-quant-resume : resume the run
risk-quant-resume -> rqh : rqh status --json
rqh --> risk-quant-resume : awaiting_data, waiting_on, pending candidates
risk-quant-resume -> collect-data : invoke collect-data
alt connector answers
collect-data -> connector : read-only search
connector -->> collect-data : finding with link
collect-data -> rqh : rqh candidates add
else connector times out
collect-data -> user : connector unavailable, continuing
end
collect-data -> user : confirm candidates? finalize now?
user -> collect-data : finalize
collect-data -> rqh : rqh candidates confirm, rqh run resume
risk-quant-resume -> rqh : rqh status --json
rqh --> risk-quant-resume : next_skill simulate, then report
```

### `rqharness.chain.next_step`

```python
def next_step(run: Run) -> NextStep: ...  # raises outcomes.NotFound when the workspace or run directory is missing
# NextStep(skill: Literal["scope-scenario", "collect-data", "simulate", "report"] | None,
#          status: RunStatus, waiting_on: list[str], latest_version: int | None, reason: str)
```

| Run state | `next_skill` |
|-----------|--------------|
| no `scenario.yaml`, or status `scoping` (a run directory without `run.yaml` is in `scoping`) | `scope-scenario` |
| `collecting`, with `inputs.yaml` missing or invalid, or a `pending` candidate | `collect-data` |
| `collecting`, with valid inputs and no `pending` candidate | `simulate` |
| `awaiting_data` | null; `waiting_on` lists the open request ids, and `risk-quant-resume` enters `collect-data`; with no open request the reason names `rqh run resume` |
| `finalized`, with no version | null; the reason names `rqh run reopen` and finalizing again |
| `finalized`, and the latest complete `v<N>/` has no `report.html` | `report` |
| `finalized`, and the latest version has its report | null; the run is done until `rqh run reopen` |

| Aspect | Contract |
|--------|----------|
| Owner | `rqh` alone decides the order of phases; skills read `next_skill` and never derive it |
| Outcomes | `NextStep`; raises `NotFound` (exit 5) when the workspace or the run directory does not exist; `reason` is one plain sentence the router shows when it stops |
| Idempotency | a pure read: it runs `validate_run` and reads its `readiness_issues`, the readiness rule `finalize` applies (so it says `simulate` exactly when `rqh finalize` would not reject the documents), and the latest-version scan used by `finalize`, and writes nothing |
| Versioning | `rqh status --json` adds `next_skill`, `waiting_on`, `latest_version` and `reason` to `data`; a skill ignores fields it does not know |

### `rqharness.library`

```python
def search(q: LibraryQuery, *, workspace: Path | None) -> list[LibraryHit]: ...   # hit = entry, origin ("memory" | "benchmark"), stale: bool
def add(entry: dict, *, workspace: Path) -> Added | Duplicate: ...    # idempotent by entry_id and content hash; raises outcomes.Rejected
def entry_lookup(workspace: Path | None) -> EntryLookup: ...                      # (entry_id, issue path) -> (entry, []) or (None, issues); memory first, then shipped
```

Memory hits sort before benchmark hits, then by segment match and recency. An entry is `stale` when the end of its covered period is older than its `stale_after_months` (default 18). `add` writes only under `.riskquant/library/` and never into shipped data. `search` and `entry_lookup` read both trees, subfolders included, and trust the same entries: schema-valid, in PERT order, known by the `entry_id` inside the file. One function in `library` decides that trust, and `rqh library validate` reports the issues it finds, so the two cannot drift. `add`, `remove` and `validate_all` enumerate memory the same way: a memory file answers to the `entry_id` inside it, or to its file name when it holds none, so `rqh library remove <id>` deletes the file `search` shows under that id in any subfolder, and `rqh library validate` reports every file, its issues under `library.<name>`, where `<name>` is the file's path below the library folder without `.yaml` (`library.team-a/x.value`). `add` writes a new entry as `.riskquant/library/<entry_id>.yaml` but treats an id held in a subfolder as present. One id answered by two memory files is a `duplicate_entry_id` issue at `library.<entry_id>.entry_id` naming both files, and a file that holds no `entry_id` is marked `(no entry_id; matched by file name)` in it; `remove` and `add` raise `Rejected` with that issue and change nothing, rather than pick one. `entry_lookup` refuses the same way: it returns the entry and no issues, or `None` and the issue at the reference's path (`inputs.sources.<i>.library_entry_id`) — `library_entry_missing`, `duplicate_entry_id` naming the files and pointing at `rqh library validate`, or `library_entry_invalid` when the one memory file answering to the id is not a valid entry, naming that file and pointing at `rqh library validate` — so `rqh validate`, `validate_run` and confirming a candidate report the ambiguity or the broken entry beside every other issue instead of guessing. A valid memory entry shadowing a shipped benchmark of the same id is precedence, not ambiguity; an invalid one never falls through to that benchmark, because the user who wrote the file meant to override it. `search` still hides an invalid file, so it lists the benchmark; only the lookup that a run cites reports it. Until the user resolves a duplicate, `search` lists both entries. `remove` raises `NotFound` for an id that is not an `entry_id` slug or that no file answers to. Schema loading and `load_yaml` live in the leaf module `rqharness.schemas`, which both `library` and `validate` import.

### `rqharness.routing.resolve`

```python
def resolve(parameter_family: str, profile: OrgProfile | None, *, scenario_type: str | None = None) -> list[Route]: ...
# Route(system_kind, owner_role, expected_artifact, connectors: list[str], people: list[Person], systems: list[System], scenario_types: list[str])
```

Resolution reads the shipped connector map and fills in `people` and `systems` from the org profile when one exists. A route may carry `scenario_types`; with a `scenario_type`, routes tagged for it come first, then general routes, then routes tagged only for other types (added at the slice 13 review so a BEC run asks finance and the incident tracker, not the asset register). The report's closing section and the Accuracy route both use it.

### Plugin and skills

| Skill | Role |
|-------|------|
| `risk-quant` | router: runs the loop in § Skill chain and hand-offs, invoking `scope-scenario`, `collect-data`, `simulate` and `report` as `rqh status` names them, then the memory batch once. It does no phase work itself |
| `risk-quant-resume` | a thin entry into the router loop for an existing run; for an `awaiting_data` run it invokes `collect-data` first |
| `risk-quant-org-setup` | build or refresh `org-profile.yaml`; also called inline with the minimal scope a run needs |
| `risk-quant-memory` | the end-of-run batch (one yes or no per item, invoked by the router), plus browse, add, prune and re-validate |
| `scope-scenario`, `collect-data`, `simulate`, `report` | phase skills, invoked by the router or directly; none invokes another phase skill. `collect-data` is one skill with a YOLO reference and an Accuracy reference, because both routes share the parameter list, the provenance rules and the per-parameter overrides (`rqh run route <path> <yolo\|accuracy>`); it also handles resumed collection. YOLO never runs inline org setup |
| `agents/benchmark-researcher.md` | YOLO research per parameter group: uses the shipped benchmark library hits collect-data passes in (never memory entries, which collect-data resolves itself), then web search; returns canonical URLs. It holds only WebSearch and WebFetch (no shell, no file access), because it reads untrusted pages — quality gate, 2026-11-11 |

Each skill uses the host's structured question tool when present (Claude Code `AskUserQuestion`) and numbered options otherwise. `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json` make the repository its own marketplace.

## Data models

### Entities

`Estimate` (any PERT in `inputs.yaml`):

| Field | Type | Invariant | Enforced by |
|-------|------|-----------|-------------|
| `min`, `mode`, `max` | number | `min ≤ mode ≤ max`; probabilities in [0, 1]; amounts ≥ 0 | cross-reference rule in `validate_run` |
| `unit` | string | currency code for amounts, `events/year` for frequencies | schema `enum` and `pattern` |
| `provenance.tier` | enum | `internal_data \| sme_estimate \| benchmark \| agent_assumption` | schema `enum` |
| `provenance.source_ids` | string[] | each resolves to `sources[].id`; required per tier as listed under `validate_run` | cross-reference rule |
| `provenance.rationale` | string | required for `agent_assumption` | schema `if`/`then` |

`Source`: `id`, `kind` (`person | internal_system | web | benchmark_library | memory`), `title`, `url` (`^https://`, required for `web` and `benchmark_library`), `library_entry_id` (required for `memory`), `owner_role`, `retrieved_at` (date), `applicability_note`.

`Inputs` top level: `schema_version`, `scenario_id`, `currency` (ISO 4217), `parameters`, `sources[]`, `variants[]`.

`Variant`: `id` (slug, not `baseline`), `label`, `overrides` (map from estimate path, e.g. `vulnerability.probability`, to an `Estimate`), and `annual_cost` (an `Estimate` in the run currency, optional).

`RunState` (`run.yaml`): `schema_version`, `scenario_id`, `route` (`yolo | accuracy`), `route_overrides` (map from estimate path to route, set by `rqh run route`), `n`, `seed`, `status`, `created_at`, `updated_at`.

`Request`: `id`, `parameter_path`, `ask`, `target` (`owner_role`, optional `person`), `draft_message`, `status`, `created_at`, `due_at`, `answer` (`value` as an `Estimate` or a note, `received_at`). `(parameter_path, target.owner_role, target.person)` is unique.

`Candidate`: `id`, `parameter_path`, `value` (an `Estimate`), `evidence_kind` (`measured | judgement`), `origin` (`request:<id>` or `connector:<name>`), `link`, `status`.

`LibraryEntry`: `entry_id`, `parameter_family`, `value` (an `Estimate`), `tier`, `source` (a `Source`), `scenario_tags`, `segment` (`industry`, `size_band`), `period` (`start`, `end`), `captured_at`, `stale_after_months`, `sensitivity` (`public | internal | confidential`), `note` (≤ 500 characters). Shipped entries additionally require tier `benchmark`, sensitivity `public` and a URL.

`OrgProfile`: `org_name`, `teams[]`, `people[]` (`name`, `role`, `team`, `contact_hint`), `systems[]` (`id`, `kind`, `name`, `owner_role`, `connector`), `theme` (`logo_data_uri` ≤ 200 KB, `accent` as a hex colour, `display_name`).

`RunSummary` (per version): per variant, the mean, median, p10, p25, p75, p90, p95 and p99 of annual loss, with `currency`, plus P(annual loss > 0) and the mean, median and p90 of LEF and of the event count. Per variant against the baseline, the ALE reduction (mean and p90) and the return on control, `(ALE reduction − annual cost) / annual cost`, when a cost is given. It also holds per-parameter sensitivity contributions summing to 1, the data-quality score and grade, and 200-point loss exceedance curves and 60-bin histograms per variant for the report.

Sensitivity: the contribution of a parameter is its squared Spearman correlation with baseline annual loss, normalised to sum to 1. All correlations are computed over the same iterations. A per-event parameter uses its per-iteration mean, and in an iteration with no events that statistic is the parameter's PERT mean. A degenerate parameter (`min = max`) contributes 0. When every correlation is 0, the contributions fall back to equal weights and the summary sets `sensitivity_fallback: true`. Grade: score = Σ contribution × tier score (internal 1.0, SME 0.7, benchmark 0.4, assumption 0.1), mapped to A ≥ 0.85, B ≥ 0.65, C ≥ 0.40, else D.

### Illegal states

| Illegal combination | Made unrepresentable by |
|---------------------|-------------------------|
| A parameter without a value at simulation time | the inputs schema requires every PERT the chosen models need; there is no `incomplete` flag |
| An unconfirmed figure used in the model | candidates live only in `requests.yaml`; the inputs schema has no candidate state |
| A variant that changes the model structure | overrides are keyed by estimate path, and validation rejects a path absent from the baseline |
| `internal_data` with no internal source | the tier-to-source-kind rule in `validate_run` |
| A model-written number in the report | the placeholder grammar and the literal rule |
| A half-written version visible to readers | `v<N>.tmp/` plus rename; the latest version is the highest complete directory |
| `awaiting_data` with no open request | guard on the `pause` transition, plus the automatic move to `collecting` when the last open request closes |
| A version rendered from files changed after finalize | `finalize` snapshots scenario and theme into `v<N>/`, the narrative is stored there, and rendering reads only `v<N>/` |
| Amounts in two currencies in one run | the currency rule in `validate_run` |
| A shipped benchmark that is private or uncited | the shipped-entry profile plus `tests/test_benchmarks.py` |
| Raw exports or PII in memory | `additionalProperties: false`, no raw-data field, a 500-character `note` cap, `sensitivity` required |
| Skills writing status directly | `run.yaml`, `requests.yaml` and `v<N>/` have one writer, `rqh`; the guardrail lint rejects skill text that edits them |

### Transitions — `RunState.status`

| From | To | Trigger |
|------|----|---------|
| `scoping` | `collecting` | `rqh run confirm --route <r>` after the structured question |
| `collecting` | `scoping` | `rqh run rescope`; clears the route confirmation |
| `collecting` | `awaiting_data` | `rqh run pause`, with at least one request `drafted` or `sent` |
| `awaiting_data` | `collecting` | `rqh run resume`, or the last open request reaching a terminal status |
| `collecting` | `finalized` | `finalize` returns `Finalized` |
| `awaiting_data` | `finalized` | `finalize` returns `Finalized`; unresolved parameters keep their fallback tier |
| `finalized` | `collecting` | `rqh run reopen`; the next `finalize` creates `v<N+1>` |

A run directory without `run.yaml` is in `scoping`; `rqh run confirm` creates `run.yaml`. A failed `finalize` leaves the status unchanged. A crash after the rename but before the status write leaves a complete `v<N>/` and the publish journal; the run reads as `finalized` with that version as the latest, and the next locked write records the status (see `finalize` Recovery). A run that lost `run.yaml` but has versions is re-confirmed with the `n` and seed of its latest version's manifest unless `--n` or `--seed` is given.

### Transitions — `Request.status`

| From | To | Trigger |
|------|----|---------|
| `drafted` | `sent` | the user says they sent it |
| `drafted` | `withdrawn` | the user drops the ask |
| `sent` | `answered` | an answer is recorded; creates a `pending` candidate |
| `sent` | `unavailable` | the owner has no such data |
| `sent` | `withdrawn` | the user drops the ask |

`answered`, `unavailable` and `withdrawn` are terminal.

### Transitions — `Candidate.status`

| From | To | Trigger |
|------|----|---------|
| `pending` | `confirmed` | `rqh candidates confirm`; writes the value into `inputs.yaml` |
| `pending` | `rejected` | `rqh candidates reject` |

### Workspace layout

```
.riskquant/
  .gitignore                 # "*" — a team opts in to sharing by deleting it
  org-profile.yaml
  library/<entry_id>.yaml
  runs/<scenario-id>/
    run.yaml  scenario.yaml  inputs.yaml  requests.yaml  narrative.draft.md  .lock  .lock.break  .pending-status.yaml
    v1/  inputs.snapshot.yaml  scenario.snapshot.yaml  theme.snapshot.yaml
         run_manifest.json  run_summary.json  draws.npz  narrative.md  report.html
    v2/  …
```

### Migration and compatibility

This is a fresh repository with fresh v1 schemas and no compatibility with the earlier prototype's `scenario.v2` or `inputs.v1` formats. The prototype stays as it is. Every file carries `schema_version: "1"`. A later major version ships a forward migration command, and v1 readers refuse v2 files with a clear issue rather than misreading them.

## Risks

| ID | Risk | Likelihood | Impact | Mitigation | Slice |
|----|------|------------|--------|------------|-------|
| R1 | Vectorised per-event draws with common random numbers are slower or more intricate than planned; SciPy's Beta inverse CDF is an iterative solver | M | H | the engine is the first behaviour slice, pinned by the speed budget on the stated load and a monotonicity test. If `betaincinv` misses the budget, each estimate's inverse CDF is a 4,096-point quantile table with linear interpolation, and the table method is recorded in the manifest | 3 |
| R2 | A benchmark is applied to the wrong industry or company size | M | H | segment fields are required, and the report shows each source's applicability note | 11 |
| R3 | YOLO cites a source that does not exist or does not say what is claimed | M | H | the URL is required for the benchmark tier, the researcher must return canonical URLs, and a weekly link check runs | 2, 18, 21 |
| R4 | The org profile or memory is committed to a public repository | L | H | `.gitignore` with `*`, sensitivity flags and a README warning | 7 |
| R5 | Benchmark entries reproduce copyrighted report text | L | M | entries store derived ranges and citations only, and `note` is capped | 11 |
| R6 | Markup in scenario text executes when the report is shared | L | H | Jinja2 autoescape and a test with `<script>` in the title | 13 |
| R7 | The literal-number rule rejects legitimate prose | M | L | digits pass unless next to a currency marker, a `%` or a magnitude suffix; the skill retries once with a placeholder | 14 |
| R8 | Skills behave differently in Cursor or Codex | M | L | best-effort support, the numbered-option fallback and the guardrail lint | 17, 18 |
| R9 | Skill evals need an API key that CI does not have, so per-commit CI cannot see questions or tool calls | M | M | CI runs a deterministic replay of the CLI sequence each route performs; the live suite asserts the question count and the absence of send calls, and the release workflow refuses a tag without a passing live-eval record for that version | 19 |
| R10 | Live trigger evals are flaky, because which skill a host picks for a prompt is not deterministic | M | M | each case runs three trials and passes at two; every near-miss prompt is written for a sibling skill, so a failure names the confusable pair and the fix is a sharper `description` | 20 |

## Build Order

Sizing: 21 slices. Ceiling: per `slice/references/sizing.md`. Over: slice 1, because the scaffold creates root files that each count as a system; slice 11, because each benchmark entry is one data file (at least 16); slices 17 and 18, because the plugin manifest, the skills it lists and the agent ship together with their lint test; slice 19, because the release gate belongs with the live suite it checks; slice 21, because the launch kit is many small root and `.github` files. Contracts land before engine behaviour, so the riskiest unknown, the vectorised engine (R1), is slice 3, right after the core schemas it consumes.

| # | Slice | Delivers | Surface | Blocked by | ACs | Verify | Size |
|---|-------|----------|---------|------------|-----|--------|------|
| 1 | Package scaffold and CLI shell | an installable `rqh` with command discovery over `rqharness.commands`, the Apache-2.0 license and `NOTICE`, and the three-OS CI matrix | `pyproject.toml`, `LICENSE`, `NOTICE`, `README.md`, `src/rqharness/__init__.py`, `src/rqharness/cli.py`, `.github/workflows/ci.yml`, `tests/cli/**` | — | 1 | `pytest tests/cli` | 8 files · 7 systems · 1 AC |
| 2 | Core schemas and validation | the scenario and inputs v1 schemas with provenance tiers and variants, the cross-reference rules, and `rqh validate`, exposing the `validate_run` contract | `src/rqharness/schemas/scenario.v1.json`, `src/rqharness/schemas/inputs.v1.json`, `src/rqharness/validate.py`, `src/rqharness/commands/validate.py`, `tests/validate/**` | 1 | 2, 3 | `pytest tests/validate` | 5 files · 2 systems · 2 ACs |
| 3 | Vectorised engine with common random numbers | the `simulate` contract: the ported engine semantics vectorised, with per-estimate-path streams and the speed budget | `src/rqharness/engine.py`, `src/rqharness/pert.py`, `src/rqharness/model.py`, `tests/engine/**` | 2 | 5, 6, 7 | `pytest tests/engine` | 4 files · 2 systems · 3 ACs |
| 4 | State schemas | the run-state, request, library-entry, org-profile and connector-map v1 schemas with version refusal | `src/rqharness/schemas/run.v1.json`, `src/rqharness/schemas/requests.v1.json`, `src/rqharness/schemas/library-entry.v1.json`, `src/rqharness/schemas/org-profile.v1.json`, `src/rqharness/schemas/connector-map.v1.json`, `tests/state_schemas/**` | 2 | 4 | `pytest tests/state_schemas` | 6 files · 2 systems · 1 AC |
| 5 | Run summary and sensitivity | `run_summary.json` and `run_manifest.json` with per-variant statistics, deltas, return on control and normalised rank-correlation sensitivity | `src/rqharness/summary.py`, `src/rqharness/manifest.py`, `src/rqharness/sensitivity.py`, `tests/summary/**` | 3 | 8, 9 | `pytest tests/summary` | 4 files · 2 systems · 2 ACs |
| 6 | Data-quality grade | the sensitivity-weighted tier score and its A–D grade in the summary | `src/rqharness/quality.py`, `tests/quality/**` | 5 | 10 | `pytest tests/quality` | 2 files · 2 systems · 1 AC |
| 7 | Workspace and run lifecycle | `rqh init` with the private-by-default `.gitignore`, and `rqh run` enforcing the run-status transition table | `src/rqharness/workspace.py`, `src/rqharness/runstate.py`, `src/rqharness/commands/init.py`, `src/rqharness/commands/run.py`, `tests/workspace/**` | 4 | 11, 12 | `pytest tests/workspace` | 5 files · 2 systems · 2 ACs |
| 8 | Finalize and versioning | the `finalize` contract: atomic `v<N>/` versions with the default `n` and a recorded seed | `src/rqharness/finalize.py`, `src/rqharness/commands/finalize.py`, `tests/finalize/**` | 6, 7 | 13 | `pytest tests/finalize` | 3 files · 2 systems · 1 AC |
| 9 | Requests, candidates and next step | `rqh requests`, `rqh candidates` and `rqh status`, with transition tables, confirm-into-inputs and the `next_step` contract that names the next skill | `src/rqharness/requests.py`, `src/rqharness/chain.py`, `src/rqharness/commands/requests.py`, `src/rqharness/commands/candidates.py`, `src/rqharness/commands/status.py`, `tests/requests/**` | 7, 8 | 14, 15, 34 | `pytest tests/requests` | 6 files · 2 systems · 3 ACs |
| 10 | Memory library | `rqh library search` and `add` over workspace memory, with staleness, segment filters and idempotent adds | `src/rqharness/library.py`, `src/rqharness/commands/library.py`, `tests/library/**` | 7 | 16, 17 | `pytest tests/library` | 3 files · 2 systems · 2 ACs |
| 11 | Seeded benchmark library | at least two cited, segment-tagged entries for each of the eight scenario types, drafted by the builder and reviewed by the maintainer before merge | `src/rqharness/data/benchmarks/**`, `tests/benchmarks/**` | 10 | 18 | `pytest tests/benchmarks` | 17+ files · 2 systems · 1 AC |
| 12 | Connector map and routing | the shipped connector map, org-profile loading and `routing.resolve` | `src/rqharness/data/connector-map.yaml`, `src/rqharness/orgprofile.py`, `src/rqharness/routing.py`, `tests/routing/**` | 4 | 19, 20 | `pytest tests/routing` | 4 files · 2 systems · 2 ACs |
| 13 | Report renderer and static charts | the `render_report` contract: the Jinja2 template per `DESIGN.md`, static SVG charts, the section order, the closing collection section and the self-containment check | `src/rqharness/report/__init__.py`, `src/rqharness/report/render.py`, `src/rqharness/report/context.py`, `src/rqharness/report/svg.py`, `src/rqharness/report/templates/**`, `src/rqharness/report/assets/report.css`, `src/rqharness/commands/report.py`, `tests/report/**` | 8, 12 | 21, 22 | `pytest tests/report` | 8 files · 2 systems · 2 ACs |
| 14 | Narrative placeholders | placeholder resolution and the literal-figure rule, with exit 4 | `src/rqharness/report/narrative.py`, `tests/narrative/**` | 13 | 23 | `pytest tests/narrative` | 2 files · 2 systems · 1 AC |
| 15 | Report interactivity and theming | the inline script (hover, variant toggle, threshold probability) and the CSS-variable theme override with light and dark modes | `src/rqharness/report/assets/report.js`, `src/rqharness/report/theme.py`, `src/rqharness/report/templates/**`, `tests/report_assets/**` | 13 | 24, 25 | `pytest tests/report_assets` | 4 files · 2 systems · 2 ACs |
| 16 | Optional search and no-network guarantee | `rqh search` ported from the earlier prototype's search client, and the import scan proving it is the only networked module | `src/rqharness/search.py`, `src/rqharness/commands/search.py`, `tests/search/**` | 1 | 26 | `pytest tests/search` | 4 files · 2 systems · 1 AC |
| 17 | Plugin manifest, router and core skills | the plugin and marketplace manifests, the `risk-quant` router and the `scope-scenario`, `simulate` and `report` phase skills, with the manifest, wording and router tests | `.claude-plugin/**`, `skills/risk-quant/**`, `skills/scope-scenario/**`, `skills/simulate/**`, `skills/report/**`, `tests/plugin/**` | 9, 10, 14, 15, 16 | 27, 29, 35 | `pytest tests/plugin` | 9 files · 3 systems · 3 ACs |
| 18 | Collection, resume, org and memory skills | the `collect-data` skill with its YOLO and Accuracy references, the `risk-quant-resume` entry, `risk-quant-org-setup`, `risk-quant-memory` with the end-of-run batch, and the `benchmark-researcher` agent, with the guardrail lint | `skills/collect-data/**`, `skills/risk-quant-resume/**`, `skills/risk-quant-org-setup/**`, `skills/risk-quant-memory/**`, `agents/benchmark-researcher.md`, `tests/skill_guardrails/**` | 11, 12, 17 | 28 | `pytest tests/skill_guardrails` | 8 files · 3 systems · 1 AC |
| 19 | Route replays and live eval suite | deterministic YOLO and Accuracy replays in CI, the `claude plugin eval` live suite with stubbed search, and the release workflow that requires a passing live-eval record | `evals/**`, `tests/replays/**`, `.github/workflows/release.yml` | 18 | 30, 31, 33 | `pytest tests/replays` | 7 files · 3 systems · 3 ACs |
| 20 | Per-skill live evals | trigger, near-miss and hand-off cases for each of the eight skills and a behaviour case for the researcher agent, added to the live suite and its release record, plus the CI test that every skill folder has its cases | `evals/live/skills/**`, `tests/skill_evals/**` | 19 | 36 | `pytest tests/skill_evals` | 10+ files · 2 systems · 1 AC |
| 21 | Sample report and launch kit | the two-variant sample run and its report, the Pages and link-check workflows, community files and the full README | `examples/**`, `README.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/CODEOWNERS`, `.github/PULL_REQUEST_TEMPLATE/**`, `.github/workflows/pages.yml`, `.github/workflows/linkcheck.yml`, `tests/launch_kit/**` | 20 | 32 | `pytest tests/launch_kit` | 12 files · 7 systems · 1 AC |

## Decisions

| ID | Decision | Options | Recommended | Wrong when | Status |
|----|----------|---------|-------------|------------|--------|
| D1 | Repository and history | make the earlier prototype public / fresh public repo under `Joaovsales` / an organisation account | fresh repo `Joaovsales/cyber-risk-quantification-harness`, private until launch, clean history | an organisation later wants to own the project — then transfer the repo | settled |
| D2 | License | MIT / Apache-2.0 | Apache-2.0 with `NOTICE`, for its patent grant and easier corporate approval | the maintainer prefers brevity over the patent clause | settled |
| D3 | Distribution | plugin only / Agent Skills folder only / both plus PyPI | Agent Skills-format `skills/` packaged as a Claude Code plugin, the repo as its own marketplace, and `rqh` on PyPI as `risk-quantification-harness` | a host cannot run a local Python command — then that host needs a hosted engine, out of scope | settled |
| D4 | Agents | delete / inline plus research fan-out / keep as an advanced mode | all phases run inline as skills; only `benchmark-researcher` remains, for parallel YOLO research capped at 4 | research fan-out costs more than it saves for small scenarios — the cap and library-first rule contain it | settled |
| D5 | Scope cut | — | port the engine semantics, schema ideas and golden sample; drop the wiki, markdown and PNG reports, the prototype's architecture notes, its compliance-specific script and the workflow scaffolding | an adopter needs a wiki export — a later exporter reads the same `run_summary.json` | settled |
| D6 | Route selection | fixed / default with per-parameter overrides / inferred | both routes share one scoping interview; one structured question confirms the scenario and picks the route; per-parameter overrides are allowed | — | settled |
| D7 | YOLO gates and defaults | zero / one / two gates | one gate; `n = 50,000`, a random seed, both recorded; Accuracy shows and allows changing them | a regulated user needs a recorded human approval of inputs — they use Accuracy | settled |
| D8 | Org knowledge | connectors only / profile only / both | a local `org-profile.yaml` built inline when missing, enriched from connectors, plus a memory library of real figures | — | settled |
| D9 | Reaching people | name only / draft / send | name the owner, search connectors read-only for context, and draft the message when the search adds detail; never send | a user explicitly asks to send through a connector — a later opt-in, not v1 | settled |
| D10 | Asynchronous collection | single session / tracker and resume | `requests.yaml`, `rqh status`, `risk-quant-resume`, and finalize-anytime with versioned reports | — | settled |
| D11 | Connector suggestions | improvised / curated map | a curated, versioned `connector-map.yaml` checked against live connectors | — | settled |
| D12 | YOLO data sources | Tavily / host search / both plus seeded library | host web search first, Tavily optional, and a seeded library of 2–4 entries for each of 8 scenario types, drafted by the agent and reviewed by the maintainer | — | settled |
| D13 | Provenance and grade | none / simple share / sensitivity-weighted | four tiers, a sensitivity-weighted A–D grade, a YOLO banner and a closing "what to collect to improve the degree of accuracy" section | — | settled |
| D14 | Who builds the report | deterministic renderer / agent-authored HTML / hybrid | a deterministic Jinja2 renderer; the agent writes only `narrative.md` through placeholders | — | settled |
| D15 | Output formats | HTML only / plus markdown / all | `report.html` plus the JSON artifacts | — | settled |
| D16 | Variants | single scenario / first-class variants / plus portfolio | first-class variants as overrides on the baseline with an optional annual cost and common random numbers; portfolio aggregation is v2 | — | settled |
| D17 | State location | per project / user-global / split | `./.riskquant/` per project, gitignored by default; teams share by committing it in a private repo | — | settled |
| D18 | Memory writes | automatic / end-of-run batch / manual only | an end-of-run batch with yes or no per item; entries older than 18 months are flagged stale | — | settled |
| D19 | Schemas | fresh v1 / extend existing | fresh v1 schemas; the earlier prototype is left as it is | — | settled |
| D20 | Hosts | Claude Code only / first-class plus best-effort / all equal | Claude Code tested first-class; Cursor and Codex best-effort with the numbered-option fallback | — | settled |
| D21 | Naming | — | GitHub repo `Joaovsales/cyber-risk-quantification-harness`; PyPI package and plugin `risk-quantification-harness`, import `rqharness`, command `rqh` with subcommands `init`, `validate`, `run` (`confirm`, `route`, `pause`, `resume`, `reopen`, `rescope`), `finalize`, `report`, `requests`, `candidates`, `status`, `library` and `search` (the agreed `resume-status` is `status`) | — | settled |
| D22 | Engine implementation | port the loop / vectorise with per-path streams | vectorise with inverse-CDF draws from per-estimate-path streams, which gives common random numbers and meets the speed budget | exact draw-for-draw parity with the earlier prototype's engine is required — it is not, since no runs migrate | settled |
| D23 | Command registration | central `cli.py` edits / discovery | `cli.py` discovers `rqharness.commands.*` modules, so slices add commands without editing a shared file. Discovery stays the registration mechanism, but it does not forbid editing `cli.py`: the maintainer lifted that no-edit reading on 2026-11-12, so shared command helpers such as `require_workspace` live there | — | settled |
| D24 | Skill evaluation | live evals in CI / deterministic replay in CI plus on-demand live evals | replay in CI; `claude plugin eval` with a stubbed search on demand | — | settled |
| D25 | Report visual direction | A) `taste:brutalist-skill:swiss-industrial-print` with references `ibm` and `clickhouse`, a dense grid that prints well · B) `taste:minimalist-skill` with `linear.app` and `notion`, quiet and editorial · C) `taste:soft-skill:the-editorial-split`, a narrative executive feel | A, chosen by the maintainer on 2026-11-09 after comparing three spikes built from the same computed sample data (B and C are kept in `design/concepts/alternatives/`). `DESIGN.md` records the brief. The approved concept is `design/concepts/report.html`, SHA-256 `525413fd8e98234793d2383f73c71ff0fe3af695b09f8834540075cbc2654ac7`. Slice 13 builds the production template from both and edits neither; a changed concept invalidates this digest | the audience turns out to be mostly on-screen executives, in which case C is reconsidered through `design-stack refresh` | settled |
| D26 | Engine, versioning and report-safety corrections from the critic pass | accept / decline per item | accept all: a stable `blake2b` stream key; a counter-based Philox addressed by (iteration, ordinal) with named `events` and `secondary_events` streams; version-local rendering with snapshots and a stored narrative; `https://` and data-URI patterns plus a CSP meta tag; LEF and event-count placeholders, a wider literal rule and the `--omit-narrative` fallback; common-iteration sensitivity with degenerate and fallback rules; a declared run currency; memory and SME source rules; `evidence_kind`, `rqh run route`, stored `n` and seed, request idempotency; automatic exit from `awaiting_data`; tolerances in standard errors and dominance-defined variants; a stated perf load; and a single-writer lock in place of the concurrency claim | any item proves unnecessary during slice 3's measurement — then it is removed by editing this row | settled |
| D27 | How the YOLO one-gate and no-send constraints are verified | per-commit replay only / live suite as a release gate / reword the constraints | the CLI replay runs in CI; the live suite asserts the question count and the absence of send calls; the release workflow requires a passing live-eval record. YOLO never runs inline org setup, and the count is per confirmation pass after scoping | the maintainer wants these checked per commit — then CI needs an API key secret | settled |
| D28 | How skills chain | one front-door skill that runs every phase inline / phase skills that call each other / a router loop over `next_skill` from `rqh status` | the router loop: `rqh` owns which skill comes next, phase skills hand off only through workspace files and never call each other, `risk-quant-resume` is a thin entry into the same loop, the end-of-run memory batch belongs to `risk-quant-memory`, and `collect-data` stays one skill with a reference per route. Raised in review on 2026-11-10 | a phase needs context that cannot be written to the workspace — then that context gets a schema-owned file rather than living in the conversation | settled |
| D29 | Evals for every skill | route-level evals only / per-skill live cases in the release gate / per-skill cases replayed from recorded transcripts in CI | per-skill live cases in the release gate: each skill gets a prompt that must trigger it, a near-miss from a sibling skill that must not, and a hand-off case; the researcher agent gets a behaviour case. Three trials per case, two to pass. CI checks only that every skill has its cases, because live runs need an API key. Chosen by the maintainer on 2026-11-10 | the trigger cases cost more than they catch — then keep the hand-off cases and drop the trigger pair for skills that are never invoked by description | settled |
| D30 | Whether the engine validates its own input | the engine is a public API that accepts unvalidated input: keep its guards and add a schema-parity test / the engine trusts validated documents: keep only structural reads | trust validated documents: the contract of `model.load_model_inputs` and the engine is an inputs document that has passed `validate_inputs` (the inputs schema plus the cross-reference rules), which `rqh finalize` runs through `validate_run` before it snapshots and simulates; `quality` takes the summary rows finalize builds from that document. They keep only structural reads, and the schema owns the model enums, the estimate set per model, `min ≤ mode ≤ max`, `analysis_period_years > 0`, override targets and the tier enum. The model's read tables (which estimates each model computes with) stay, pinned to the schema by `tests/validate/test_estimate_paths.py`. Keeping the guards with a parity test was rejected because the guards state the schema's rules a second time (APOSD information leakage): every schema change would have to be mirrored or finalize raises on a document that validated. A write to `inputs.yaml` between validation and the snapshot is outside D26's single writer; a frozen `run_summary.json` is trusted as written. `tests/engine` and `tests/quality` prove validation rejects each rule the engine and quality trust. Chosen by the maintainer on 2026-11-12 | the engine gains a caller that does not validate first — then that caller validates, or the guards return with a schema-parity test | settled |
| D31 | One failure model, and which exit code an out-of-range draw argument gets | keep three styles (result unions, `cli.CommandError`, `ValueError`) / one raised `DomainError` family below the CLI / returned unions everywhere; for `--n`/`--seed` out of range: exit 1 (a rejected `run.yaml` field) / exit 2 (a usage error) | domain functions raise the kinds in the leaf `rqharness.outcomes` (`Rejected`, `Usage`, `IllegalTransition`, `NarrativeRejected`, `NotFound`), `cli.EXIT_CODES` maps each to one exit code and `cli.main` is the only handler. An out-of-range `--n` or `--seed` is exit 2 from every command, issue `argv.<flag>` rule `range`, checked before the run is read: the value is a command-line argument the user typed, and exit 2 is the code for arguments unusable as given (argparse errors, `outside_workspace`, `--ask-file`). Before this, `rqh run confirm` let it reach `run.yaml` validation and exited 1 while `rqh finalize` exited 2 | a skill needs to tell a bad stored `run.yaml` from a bad argument by exit code alone — it already can: the stored case stays exit 1 at `run.*` | settled |
| D32 | How a run too large for memory is rejected | a hard cap on `--n` / a byte budget measured at run time / a cell budget estimated from the inputs and n before simulating | a cell budget estimated before simulating. `engine.event_budget(model)` owns the estimate and the comparison: its cells per iteration are the sum, over the baseline and every variant, of the expected events per iteration (`engine.expected_events` on each estimate's PERT mean: the LEF formula the simulation uses, times `analysis_period_years`) times one plus the `slef` mean when secondary loss is present, and it answers whether an n fits and the largest n that does. `rqh finalize` is the one path into `engine.simulate`, so the n it resolves (`--n`, else the n `rqh run confirm` stored in `run.yaml`) is checked there once, after validation and before anything is written: above `engine.MAX_EVENT_CELLS` = 40,000,000 it exits 1 with a `memory_budget` issue on `inputs.parameters` that names the n, its source and the largest n that fits, or, when even n = 1 does not fit, asks for a lower frequency or `slef`. Measured peak memory is 13 to 93 bytes per cell (the high end with all twelve loss forms), so the budget keeps a run under about 4 GB; at the default n = 50,000 it admits 800 expected events per iteration. The default n is unchanged | the engine streams iterations in chunks, so memory no longer grows with n — then the budget bounds each chunk instead | settled |

## Acceptance Criteria

- AC1: Installing the package exposes `rqh`; `rqh --version` prints the package version, the package imports as `rqharness`, the repository carries Apache-2.0 `LICENSE` and `NOTICE`, and CI runs the tests on Ubuntu, macOS and Windows.
- AC2: `rqh validate <run> --json` returns `ok` for the sample run and, for each scenario or inputs schema violation, an issue naming its dotted field path, with exit 1.
- AC3: Validation rejects: unresolved `source_ids`; a `benchmark` tier without an `https://` URL source; an `internal_data` tier without a person, internal-system or matching memory source; an `sme_estimate` without a person or matching memory source; an `agent_assumption` without a rationale; an amount or `annual_cost` whose unit differs from the declared `currency`; a variant override of an estimate absent from the baseline; and a PERT with `min > mode` or `mode > max`.
- AC4: The run-state, request, candidate, library-entry, org-profile and connector-map schemas validate their fixtures and reject an unknown `schema_version` major version.
- AC5: For each of the four frequency models, both vulnerability models and secondary loss, degenerate PERTs at a fixed seed produce a mean annual loss within four standard errors of the analytic value the engine semantics give.
- AC6: A variant with no overrides produces annual losses identical to the baseline per iteration. A variant that only lowers vulnerability, scaling its `min`, `mode` and `max` by one factor below 1, never produces a higher per-iteration loss than the baseline.
- AC7: `n = 50,000` with a baseline and two variants at the load stated in the speed constraint completes in under 5 s on `ubuntu-latest`, stream keys are identical across processes, and identical arguments produce identical results.
- AC8: `run_summary.json` holds the per-variant statistics, deltas against the baseline, return on control when a cost is given, currency on every amount, and byte-identical content for identical inputs, `n`, seed and version.
- AC9: Sensitivity contributions sum to 1 over a common set of iterations and rank first the parameter that dominates variance in a fixture built for it; a degenerate parameter contributes 0; an all-constant fixture falls back to equal weights with `sensitivity_fallback: true`.
- AC10: The data-quality grade is the sensitivity-weighted tier score mapped to A, B, C and D at 0.85, 0.65 and 0.40, with one fixture per grade.
- AC11: `rqh init` creates `.riskquant/` with a `.gitignore` containing `*`, and running it twice changes nothing.
- AC12: `rqh run` refuses every transition missing from the run-status table with exit 3 and accepts every listed one.
- AC13: Each successful `rqh finalize` creates the next `v<N>/` with the inputs, scenario and theme snapshots, the manifest, the summary and the draws. It uses the seed stored in `run.yaml` unless overridden, leaves earlier versions byte-identical (including their reports after later edits to run-level files), cleans up a leftover `v<N>.tmp/`, and exits 1 while another `finalize` holds the lock.
- AC14: `rqh requests` and `rqh candidates` refuse every transition missing from their tables with exit 3. A repeated `rqh requests add` for the same parameter and target returns `Duplicate`. Closing the last open request moves an `awaiting_data` run to `collecting`. `rqh status` lists open requests, pending candidates and parameters still on fallback tiers.
- AC15: A candidate never appears in `inputs.yaml` until confirmed. Confirming it writes the value at its parameter path, with tier `internal_data` for `measured` evidence and `sme_estimate` for `judgement`, adds a source row with its link, and is safe to repeat after a crash between the two writes.
- AC16: `rqh library search` returns memory hits before benchmark hits, filters by industry and size band, marks entries past `stale_after_months` as stale, and flags hits in a currency other than the run's as `currency_mismatch`.
- AC17: `rqh library add` validates the entry, refuses one without a sensitivity flag or with a `note` over 500 characters, never writes into shipped data, and returns `Duplicate` for the same id and content.
- AC18: The shipped library holds at least two cited entries for each of ransomware, business email compromise, credential phishing leading to account takeover, third-party breach, cloud misconfiguration, DDoS, insider data theft and lost or stolen devices, and every entry has tier `benchmark`, sensitivity `public`, a URL, a retrieval date and a segment.
- AC19: The connector map covers every parameter family, and `routing.resolve` returns system kind, owner role, expected artifact and example connectors, adding matching people and systems when an org profile is present.
- AC20: The org-profile schema accepts the sample profile, refuses a logo over 200 KB or a non-hex accent, and rejects unknown fields.
- AC21: `rqh report` writes one `report.html` that carries the Content-Security-Policy meta tag and no external or protocol-relative reference in `src`, `srcset`, `href`, `xlink:href`, `@import` or `url()` except `https://` citation anchors. It stays at or under 1 MB for the two-variant sample, escapes scenario markup, and reads nothing outside `v<N>/`.
- AC22: The report sections run in order: the takeaway with the YOLO banner when the route is YOLO and the grade; summary cards; the loss exceedance curve; the distribution; the drivers; the variants comparison; the scenario; the provenance table; a collapsed technical appendix; and last, "What to collect to improve the degree of accuracy", naming the three parameters with the highest contribution × (1 − tier score), each with its owner role, system and, when known, person.
- AC23: Narrative placeholders resolve from the summary, including LEF and event-count statistics. An unknown placeholder or any prose pattern the literal rule lists returns exit 4 with its line and token and writes no file. `--omit-narrative` renders with the fixed placeholder takeaway and marks the narrative as omitted.
- AC24: Charts are static SVG in the markup, so the report prints without JavaScript; the embedded script adds a hover readout, a variant toggle, and a threshold input that shows P(annual loss > X) from the embedded curve.
- AC25: A theme in the org profile changes only CSS custom properties and the logo, and the report honours `prefers-color-scheme` for light and dark.
- AC26: `rqh search` returns Tavily results as JSON when `TAVILY_API_KEY` is set, exits 2 without it, and is the only module in the package that opens a network connection.
- AC27: `plugin.json` and `marketplace.json` parse with their required fields, their version equals the package version, and every skill folder has a `SKILL.md` with `name` and `description`.
- AC28: The skill guardrail lint finds, in the relevant skills: the structured-question rule with its numbered-option fallback, read-only connector use, drafts-only messaging, candidate-until-confirmed, the end-of-run memory batch in `risk-quant-memory`, the research cap of 4, `collect-data` ending with the next skill from `rqh status` and invoking no phase skill, every phase hand-off handing back to the router and the router carrying on after it, `risk-quant-resume` entering the router loop, and no instruction to edit `run.yaml`, `requests.yaml` or `v<N>/` directly.
- AC29: Templates and skill text contain no "SWAG", and neither the package nor the plugin name contains "FAIR".
- AC30: The YOLO replay drives the sample scenario's recorded CLI sequence through `rqh` with stubbed search, calling `rqh status` between phases and following its `next_skill`, and ends with a valid `report.html` carrying the YOLO banner, including when the narrative is rejected twice.
- AC31: The Accuracy replay, using a fixture org profile and canned answers, follows `next_skill` between phases, creates requests with drafts, pauses (`next_skill` null with the open requests in `waiting_on`), resumes, confirms a candidate and finalizes `v2` with v1's seed and a higher data-quality score than `v1`.
- AC33: The live eval suite asserts that YOLO asks exactly one question per confirmation pass after scoping and never runs org setup, and that Accuracy makes no send-type Bash call and shows each draft unsent; question counts and drafts are judged on the reply by an `llm` grader with a sonnet judge. The release workflow refuses to publish a version without a passing live-eval record for it.
- AC32: The repository carries `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `.github/CODEOWNERS` and a benchmark-entry pull request template with a citation and applicability checklist; a Pages workflow publishes the sample report; and a weekly workflow checks every shipped benchmark URL.
- AC34: `rqh status <run> --json` returns `next_skill`, `waiting_on`, `latest_version` and `reason` for a fixture in each row of the `next_step` table: `scope-scenario` for a run without `run.yaml`; `collect-data` for invalid inputs or a pending candidate; `simulate` for valid inputs; null with the open request ids for `awaiting_data`; `report` for a finalized version without `report.html`; and null once it has one. A missing workspace exits 5, and the command writes nothing.
- AC35: The `risk-quant` skill holds the router loop — status, invoke `next_skill`, stop on null or on an unchanged state, one memory batch after `report` — and the read-`SKILL.md` fallback for hosts without skill invocation; `scope-scenario`, `simulate` and `report` each end by naming the next skill from `rqh status` and invoke no other phase skill.
- AC36: Each of the eight skills has live eval cases in `evals/live/skills/<skill>/`: a prompt that must invoke it, a near-miss prompt written for a sibling skill that must not, and a hand-off case. The hand-off cases assert that the router invokes the skill `next_skill` names; each phase skill ends by naming the next skill from `rqh status`, hands back to the router, and invokes no other phase skill; `risk-quant-resume` enters `collect-data` for an `awaiting_data` run; `risk-quant-memory` asks one yes or no per item and writes only through `rqh library add`; and `risk-quant-org-setup` makes only read-only connector calls. The `benchmark-researcher` agent has a behaviour case asserting no shell call, that a segment-matched library hit passed in is returned as the proposal, that a path with no usable result is reported as such rather than given an invented range, only `https://` source URLs, and at most 12 web tool calls (the release run disables web tools, so that budget binds only in a web-enabled run). Each case runs three trials and passes at two. `tests/skill_evals/` fails when a skill folder or the agent has no cases, and the release workflow's live-eval record includes these cases.

## Implementation Paths

- `pyproject.toml`, `LICENSE`, `NOTICE`, `README.md` — packaging, the `rqh` entry point, the license and the user guide
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md` — the contribution kit
- `DESIGN.md`, `design/**` — the report's visual brief and approved concept
- `.github/**` — CI matrix, Pages, link check, CODEOWNERS and pull request templates
- `.claude-plugin/**` — plugin and marketplace manifests
- `skills/**`, `agents/**` — the skills and the research subagent
- `src/rqharness/**` — schemas, validation, engine, summary, sensitivity, grade, workspace, finalize, requests, library, routing, search, report renderer and shipped data
- `tests/**` — unit, contract, guardrail and replay tests
- `evals/**` — the YOLO and Accuracy replay fixtures and the on-demand live eval suite, run in the Linux container `evals/docker/` because a case that grants Bash needs an OS sandbox
- `examples/**` — the sample phishing run with two variants and its rendered report
