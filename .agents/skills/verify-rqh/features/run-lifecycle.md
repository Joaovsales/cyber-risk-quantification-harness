# Run lifecycle

A user creates a private workspace, puts a scenario and its inputs in a run directory, validates them, confirms the
run with a route, sample size and seed, and finalizes it into an immutable numbered version. An optional org profile
next to the runs themes the report and names owners. Every write to a run's state takes the run lock.

## Sub-features

- `version` prints `rqh <version>` and exits 0 (`rqh --version`; plain text, no envelope).
- `init` creates `.riskquant/` (or `$RQH_WORKSPACE`) with a `.gitignore` of `*`.
- `validate` accepts the sample run and rejects broken inputs with issues and exit 1. Given a file, it infers the
  document kind from the file name (`scenario.yaml`, `inputs.yaml`, `run.yaml`, `requests.yaml`, `org-profile.yaml`,
  `connector-map.yaml`); any other name needs `--kind` (exit 2 otherwise).
- `aliases` refuses a YAML alias in any document rqh reads (exit 1, rule `yaml` at `<kind>.document`, with a hint to
  re-save the file without anchors).
- `confirm` moves the run from `scoping` to `collecting` and writes `run.yaml` with route, n and seed. `--n` must be
  1 to 10,000,000 and `--seed` 0 to 2^63−1 (exit 2, rule `range`, at `argv.n` / `argv.seed`). Without `--seed` a
  random seed is picked and stored.
- `route` overrides the route of one estimate (`run.yaml` `route_overrides`) while `collecting` or `awaiting_data`.
- `rescope` moves `collecting` back to `scoping`; confirm again to continue.
- `finalize` writes `v<N>/` (`inputs.snapshot.yaml`, `scenario.snapshot.yaml`, `theme.snapshot.yaml`,
  `run_summary.json`, `run_manifest.json`, `draws.npz`) and sets status `finalized`. It runs from `collecting` or
  `awaiting_data`.
- `reopen` returns a finalized run to `collecting` so the next finalize writes `v<N+1>/`.
- `org-profile` is `.riskquant/org-profile.yaml`, written by hand or by the org-setup plugin skill (no CLI writes it).
  Finalize validates it and freezes its theme, people and systems into `v<N>/theme.snapshot.yaml`.
- `lock` serialises writers on `runs/<id>/.lock`: a writer waits up to 2 s for it, then refuses with exit 1.

## How to get to it (user POV)

- `rqh --version`
- `rqh init`
- `rqh validate <run>` or `rqh validate <file> [--kind KIND]`
- `rqh run confirm <run> --route yolo|accuracy [--n N] [--seed S]`
- `rqh run route <run> <estimate path> yolo|accuracy`
- `rqh run rescope <run>`
- `rqh finalize <run> [--n N] [--seed S]`
- `rqh run reopen <run>`
- Write `.riskquant/org-profile.yaml` (see `tests/routing/fixtures/org-profile.yaml`).

## Driving it with verify.py and a browser

Preconditions:

- `verify.py doctor` is ok. For the by-hand recipes, a workspace as in [the index](./README.md#a-workspace-by-hand).

- **Happy path.** Run `verify.py run`. In `summary.json`, the `steps` named init, validate, run_confirm and finalize all
  have `exit` 0, and `finalize_n_seed` passes with n 50000 and seed 20261109.
- **Version.** `rqh --version` prints `rqh 0.1.0` (the package version) and exits 0.
- **Rejected input.** In a fresh workspace, change `$RD/inputs.yaml` so one PERT has min > max, then
  `rqh validate credential-phishing-bec`. Expect exit 1 with an issue whose `rule` is `pert_order` at the estimate
  path (for example `inputs.parameters.primary_loss.response`, not `.min`).
- **Alias refused.** Add an anchor and an alias to `$RD/inputs.yaml` (`scenario_id: &s credential-phishing-bec` and a
  line `x: *s`). `rqh validate credential-phishing-bec` is exit 1, rule `yaml`, path `inputs.document`, and the message
  says "found an alias" and how to re-save the file.
- **One file.** `rqh validate $RD/inputs.yaml` is exit 0 with `data.documents` `["inputs"]`. Copy it to
  `$RD/draft.yaml`: `rqh validate $RD/draft.yaml` is exit 2 naming `--kind`; with `--kind inputs` exit 0; with
  `--kind scenario` exit 1.
- **Illegal from scoping.** In a fresh workspace, `rqh finalize credential-phishing-bec` is exit 3, rule
  `illegal_transition`; so is `rqh run route credential-phishing-bec primary_loss.response accuracy`.
- **Range.** `rqh run confirm credential-phishing-bec --route yolo --n 0` is exit 2, rule `range`, path `argv.n`;
  `--seed -1` is exit 2 at `argv.seed`; `rqh finalize … --n 20000000` is exit 2, rule `range`.
- **Repeated confirm.** On a confirmed run, `rqh run confirm … --route accuracy` again is exit 0 and keeps n and seed;
  asking another `--n` or `--seed` is exit 3, naming `rqh run rescope`.
- **Route.** `rqh run route credential-phishing-bec primary_loss.response yolo` is exit 0 with
  `data.route_overrides` `{"primary_loss.response": "yolo"}`. An unknown path (`primary_loss.nope`) is exit 1, rule
  `unknown_path`.
- **Rescope.** `rqh run rescope credential-phishing-bec` is exit 0, `data.status` `scoping`; `rqh status` then names
  `scope-scenario`. Confirming again is exit 0 and keeps `route_overrides`.
- **Memory budget.** `rqh finalize credential-phishing-bec --n 10000000` is exit 1, rule `memory_budget`, and writes no
  `v1/`.
- **Org profile.** Write `.riskquant/org-profile.yaml` with `org_name: 42`: `rqh validate .riskquant/org-profile.yaml`
  is exit 1 and `rqh finalize` is exit 1 at `org-profile.org_name`, with no `v1/`. Copy
  `tests/routing/fixtures/org-profile.yaml` there instead: validate is exit 0 (`["org-profile"]`), finalize is exit 0,
  and `v1/theme.snapshot.yaml` holds "Northwind". `verify.py run --profile` checks the report side (`profile_applied`).
- **Leftover tmp.** `mkdir $RD/v1.tmp`, then finalize: exit 0, `data.version` 1, and `v1.tmp/` is gone.
- **Illegal transition.** On a finalized run, `rqh finalize credential-phishing-bec` again is exit 3, rule
  `illegal_transition`.
- **Second version.** `rqh run reopen credential-phishing-bec`, then `rqh finalize credential-phishing-bec --seed 99`.
  Expect `data.version` 2 and seed 99 in `v2/run_manifest.json`, while `run.yaml` keeps seed 7. `rqh status` reports
  `latest_version` 2, and every file in `v1/` is byte-unchanged.
- **From awaiting_data.** Reopen, add a request (see [requests and candidates](./requests-and-candidates.md)),
  `rqh run pause`, then finalize: exit 0, the next version.
- **Lock held.** Create `$RD/.lock` holding any text. `rqh finalize credential-phishing-bec` waits about 2 s, then is
  exit 1, rule `lock_held`, message "another rqh command holds the run lock; try again shortly". The same holds for
  `rqh run …`, `rqh requests …` and `rqh candidates …` writes.
- **Stale lock and break guard.** Backdate `.lock` by 11 minutes (`touch -d '11 minutes ago' $RD/.lock`) and create a
  fresh `$RD/.lock.break`: finalize is still exit 1 `lock_held` (another writer is breaking it). Backdate both files:
  finalize is exit 0 and both files are gone.
- **Interrupted publish.** On a reopened run, copy the latest `v<N>/` to `v<N+1>/` and write
  `$RD/.pending-status.yaml` holding `trigger: finalize` and `path: v<N+1>`. `rqh status` reads the run as `finalized`
  with `latest_version` N+1 and leaves the file; the next locked write (for example `rqh run reopen`) records the status
  first, then removes the journal.

## Gotchas

- The lock wait is 2 s, so a lock-held refusal takes at least that long. A lock untouched for ten minutes is stale; a
  live holder refreshes it every minute, so only a dead holder's lock goes stale.
- `.lock.break` is the guard a writer holds while it breaks a stale lock. A fresh guard means another writer is
  breaking it, so the command refuses rather than racing it.
- `.pending-status.yaml` is a journal, not state you edit. `rqh status` never writes, so it reads through the journal
  without removing it.
- `--seed` on finalize is recorded in the manifest only. `run.yaml` keeps its seed.
- A `v<N>.tmp/` left behind is cleaned up by the next finalize. It is not a version.
- Editing the org profile after finalize changes nothing in that version's report; re-finalize to pick it up.
- `rqh validate <file>` checks that one document. Rules that need both documents (the scenario id match, a missing
  `inputs.yaml`) come only from `rqh validate <run>`.
