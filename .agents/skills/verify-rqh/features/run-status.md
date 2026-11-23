# Run status and next step

A user, or the router skill, asks `rqh status` where a run stands. The answer gives the next phase skill (or none),
what the run waits on, the latest version, open requests, pending candidates and the inputs still on fallback tiers.
The command never writes, not even the run lock.

## Sub-features

- `scope` reports `next_skill` `scope-scenario` while the run is `scoping`, or in any status when `scenario.yaml` is
  missing.
- `collect` reports `collect-data` while `collecting` when the inputs are missing or do not validate, or a candidate is
  pending.
- `simulate` reports `simulate` while `collecting` when the inputs are valid and nothing is pending.
- `waiting` reports null with the open request ids in `waiting_on` while `awaiting_data`; with no open request left it
  reports null and a reason naming `rqh run resume`.
- `report` reports `report` for a finalized version without `report.html`, and null once it has one.
- `journal` reads a run whose `.pending-status.yaml` names a published version as the status that publish fired (see
  [run lifecycle](./run-lifecycle.md)).
- `missing` returns exit 5 for a missing workspace or run.
- `resolve` finds `<run>` as an id under `<workspace>/runs/` or as a path to a directory there. The workspace is
  `$RQH_WORKSPACE` when set, else `./.riskquant`. A directory path outside `<workspace>/runs/` is exit 2, rule
  `outside_workspace`.

## How to get to it (user POV)

- `rqh status <run> --json` (data keys: `run`, `scenario_id`, `status`, `route`, `next_skill`, `waiting_on`,
  `latest_version`, `reason`, `open_requests`, `pending_candidates`, `fallback_parameters`, `n`, `seed`)

## Driving it with verify.py and a browser

Preconditions:

- A fresh workspace from `verify.py run` (its `ws/`), or one made by hand as in
  [the index](./README.md#a-workspace-by-hand).

- **Done run.** `verify.py run` covers this: `status_second_view` passes with `next_skill` null, `latest_version` 1
  and `status` finalized.
- **Scoping.** In a fresh workspace (not yet confirmed), `rqh status credential-phishing-bec` names `scope-scenario`.
- **Collecting.** After `rqh run confirm` only, expect `simulate` (the sample's inputs are valid and it has no
  `requests.yaml`).
- **No scenario.** On a confirmed run, rename `$RD/scenario.yaml` away: expect `scope-scenario`. Put it back.
- **Invalid inputs.** On a confirmed run, break `$RD/inputs.yaml` (rename the `scenario_id:` key): expect
  `collect-data`. Restore it.
- **Waiting and pending.** [Requests and candidates](./requests-and-candidates.md) drives these: a paused run with
  open requests gives null and `waiting_on` `["req-1", "req-2"]`; a pending candidate gives `collect-data`; a confirmed
  or rejected one gives `simulate` again.
- **Before report.** Confirm and finalize, then `rqh status credential-phishing-bec`. Expect `next_skill` `report`.
- **Missing.** In an empty directory, `rqh status x` exits 5; in a workspace, `rqh status nope` exits 5.
- **Writes nothing.** List the workspace files with their sizes and mtimes before and after `rqh status`. They are
  identical.
- **Workspace from the environment.** From another directory, `RQH_WORKSPACE=<ws>/.riskquant rqh status
  credential-phishing-bec` answers for that workspace.
- **Outside the workspace.** Copy the run directory to `./copied` outside `<workspace>/runs/`, then
  `rqh status ./copied`: exit 2, rule `outside_workspace`.

## Gotchas

- `rqh status` resolves `<run>` under `./.riskquant/runs/` of the current directory unless `RQH_WORKSPACE` is set. Run
  it from `ws/`, and unset `RQH_WORKSPACE` in your shell first.
- An argument is read as a path only when it is an existing directory and contains a path separator or starts with
  `.`; anything else is a run id.
- A copied run is never read with the profile and library of whatever folder sits above it, which is why a path
  outside `runs/` is refused rather than resolved.
