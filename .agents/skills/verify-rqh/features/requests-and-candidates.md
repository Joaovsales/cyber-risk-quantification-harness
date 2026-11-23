# Requests and candidates

While a run is collecting, a user (or the data-collection skill) drafts requests for data to the people who own it,
sends them, and records the answers. An answer with a value, or a figure found elsewhere, becomes a candidate; only
confirming a candidate writes it into `inputs.yaml`. A run can pause while it waits for answers. Everything is stored
in `runs/<id>/requests.yaml`, under the run lock, and a finalized run refuses these writes until it is reopened.

## Sub-features

- `request-add` drafts a request (`req-N`, status `drafted`) for one estimate path. The owner role, optional person,
  ask and draft message come from one `--request-file` (YAML, or JSON when it ends in `.json`) or from the per-field
  flags. The same parameter and target while a request is still open is `result` `duplicate`, not a new request.
- `request-update` moves a request along `drafted → sent | withdrawn` and `sent → answered | unavailable | withdrawn`.
  An answer (value, evidence kind, note) comes from `--answer-file` or the per-field flags. An answer with a value adds
  a pending candidate with origin `request:req-N`.
- `repeat` repeats the current status: an identical answer is exit 0 and changes nothing; a different one is exit 3,
  rule `answer_recorded`, pointing at `rqh candidates add`.
- `auto-resume` moves an `awaiting_data` run back to `collecting` when the last open request closes.
- `pause` / `resume` move `collecting ↔ awaiting_data` by hand. Pause needs a drafted or sent request (exit 3,
  rule `pause_guard`, otherwise).
- `candidate-add` records a found figure (`cand-N`, status `pending`) from one `--candidate-file` or the value flags
  plus `--origin request:req-N|connector:<name>` and an optional `https://` `--link`.
- `candidate-confirm` writes the value into `inputs.yaml` (tier from the evidence kind, the candidate as its source)
  and marks it `confirmed`. A second confirmed candidate for the same parameter is exit 3, rule `already_confirmed`.
- `candidate-reject` marks a pending candidate `rejected`.
- `list` returns `data.requests` / `data.candidates`.
- `frozen` refuses every request and candidate write on a finalized run with exit 3, naming `rqh run reopen`. Only
  withdrawing a request is allowed.
- `files` confines `--request-file`, `--answer-file`, `--candidate-file`, `--ask-file` and `--draft-file` to the run
  directory (exit 2 at `argv.<flag>` otherwise, or for a file that is not valid YAML or JSON, YAML aliases included).

## How to get to it (user POV)

- `rqh requests add <run> --parameter PATH (--request-file FILE | --owner-role R [--person P] (--ask T | --ask-file F) (--draft T | --draft-file F)) [--due YYYY-MM-DD]`
- `rqh requests update <run> <req-N> --status drafted|sent|answered|unavailable|withdrawn [--answer-file FILE | --min --mode --max --unit --evidence measured|judgement --note]`
- `rqh requests list <run>`
- `rqh run pause <run>`, `rqh run resume <run>`
- `rqh candidates add <run> --parameter PATH (--candidate-file FILE | --min --mode --max --unit --evidence --origin [--link])`
- `rqh candidates confirm|reject <run> <cand-N>`, `rqh candidates list <run>`

## Driving it with verify.py and a browser

Preconditions:

- A confirmed run made by hand as in [the index](./README.md#a-workspace-by-hand) (`$RD` is its directory).
  `verify.py run` does not touch these commands.

- **Pause guard.** `rqh run pause credential-phishing-bec` before any request: exit 3, rule `pause_guard`.
- **Add from a file.** Write `$RD/request.yaml`:
  ```yaml
  owner_role: Incident response lead
  person: Dana Reyes
  ask: Total incident-response cost per BEC case in 2025
  draft: Hi Dana, could you share the IR cost per case?
  ```
  `rqh requests add credential-phishing-bec --parameter primary_loss.response --request-file $RD/request.yaml`: exit 0,
  `data.result` `added`, `data.request.id` `req-1`, status `drafted`. Run it again: `data.result` `duplicate`.
- **File confinement.** Copy the file outside the run directory and pass that path: exit 2, issue path
  `argv.request-file`. Passing `--request-file` together with `--person` is exit 2 too.
- **Add from flags.** `rqh requests add credential-phishing-bec --parameter secondary_loss.slef --owner-role Controller
  --ask "Legal cost per case" --draft "Hi, could you share legal costs?" --due 2026-12-31`: exit 0, `req-2`.
  `rqh requests list credential-phishing-bec` shows `req-1` and `req-2`.
- **Pause.** `rqh run pause credential-phishing-bec`: exit 0, `data.status` `awaiting_data`. `rqh status` gives
  `next_skill` null and `waiting_on` `["req-1", "req-2"]`.
- **Transitions.** `rqh requests update credential-phishing-bec req-1 --status answered` from `drafted` is exit 3,
  rule `illegal_transition`. `--status sent` is exit 0, `data.result` `updated`. Withdraw `req-2` (exit 0).
- **Answer from a file.** Write `$RD/answer.yaml` (`min: 6000`, `mode: 18000`, `max: 60000`, `unit: USD`,
  `evidence: measured`, `note: from IR invoices`), then `rqh requests update credential-phishing-bec req-1 --status
  answered --answer-file $RD/answer.yaml`: exit 0. No request is open any more, so the run auto-resumes: `rqh status`
  gives `status` `collecting`, `next_skill` `collect-data` and `pending_candidates` `[cand-1]`.
- **Repeated answer.** The same command again is exit 0. With `min: 7000` instead it is exit 3, rule
  `answer_recorded`. An answer file with a YAML alias (`min: &a 6000`, `mode: *a`) is exit 2 at `argv.answer-file`.
- **Confirm.** `rqh candidates list credential-phishing-bec` shows `cand-1` `pending`, origin `request:req-1`.
  `rqh candidates confirm credential-phishing-bec cand-1`: exit 0, `data.result` `confirmed`; `$RD/inputs.yaml` now holds
  mode 18000 with source `cand-1`, and `rqh status` names `simulate`.
- **Candidate from a file.** Write `$RD/candidate.yaml` (value fields, `evidence: judgement`,
  `origin: connector:ticketing`, `link: https://tickets.example.test/IR-42`), then
  `rqh candidates add credential-phishing-bec --parameter primary_loss.response --candidate-file $RD/candidate.yaml`:
  exit 0, `cand-2` pending. Confirming it is exit 3, rule `already_confirmed`; `rqh candidates reject … cand-2` is
  exit 0, status `rejected`. The same file outside `$RD` is exit 2 at `argv.candidate-file`; an unknown id
  (`cand-9`) is exit 5.
- **Resume by hand.** Add a request and pause, then edit that request's `status` in `$RD/requests.yaml` to
  `withdrawn` (as a crash or a hand edit could leave it): `rqh status` gives null with a reason naming
  `rqh run resume`. `rqh run resume credential-phishing-bec` is exit 0, `collecting`.
- **Frozen.** `rqh finalize credential-phishing-bec`, then `rqh requests add …` and `rqh candidates add …`: each exit
  3 with a message naming `rqh run reopen`, and `$RD/requests.yaml` is byte-unchanged.
- **Lock.** With `$RD/.lock` present (see [run lifecycle](./run-lifecycle.md)), `rqh requests add …` waits about 2 s,
  then exit 1, rule `lock_held`.

## Gotchas

- Every file flag resolves the path and requires it inside the run directory, so write the test files into `$RD`, not
  next to the workspace.
- A duplicate is detected only among open (`drafted`, `sent`) requests with the same parameter and the same target
  (owner role and person).
- An answer with a value needs an evidence kind (`measured` or `judgement`); the tier written on confirm follows it.
- Confirming a candidate validates the whole `inputs.yaml` against the workspace library; a candidate that would make
  the inputs invalid is exit 1 and leaves the candidate pending.
