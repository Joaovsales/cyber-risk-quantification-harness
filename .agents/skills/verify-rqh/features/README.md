# rqh verification map

This directory maps how to verify the user-facing behaviour of `rqh` and the report it writes. Read this index
before driving, then use the matching feature file as the recipe.

## Baseline preconditions

- `verify.py doctor` reports `"ok": true` for this checkout.
- Every drive uses a fresh workspace made by `verify.py run`, or by hand as below. Never drive a user's real
  `./.riskquant/`.
- `rqh` means `<venv python> -m rqharness` with `PYTHONPATH=<repo>/src`, so the code under test is this checkout.
- The sample run is `tests/validate/fixtures/sample-run/` (scenario `credential-phishing-bec`, USD, variants `mfa` and
  `mfa-sandbox`).

## A workspace by hand

Most recipes start from one of these two states. In Git Bash, macOS or Linux (use `.venv/bin/python` off Windows):

```bash
REPO=$(git rev-parse --show-toplevel)            # run from inside the checkout
export PYTHONPATH="$REPO/src"; unset RQH_WORKSPACE TAVILY_API_KEY
rqh() { "$REPO/.venv/Scripts/python.exe" -m rqharness "$@" --json; echo "exit $?"; }
cd "$(mktemp -d)"
rqh init
cp -r "$REPO/tests/validate/fixtures/sample-run" .riskquant/runs/credential-phishing-bec   # "a fresh workspace"
rqh run confirm credential-phishing-bec --route accuracy --n 2000 --seed 7                 # "a confirmed run"
RD=.riskquant/runs/credential-phishing-bec
```

A small `--n` keeps finalize fast; the sample checks in `verify.py run` use the defaults.

## Driving conventions

- Pass `--json` and read the envelope, not prose. Assert `ok`, `data` fields, the first issue's `path` and `rule`, and
  the exit code together.
- Run ids are directory names under `.riskquant/runs/`; a path to a run directory also works.
- Confirm every write through a second user-facing view (`rqh status`, a `list` command, a re-render, or the report in
  the browser), never by reading internal state with Python.
- In the browser, prefer `data-section`, `id`, `role`, `aria-*`, form state and visible text over coordinates.
- Every file a command reads with `--request-file`, `--answer-file`, `--candidate-file`, `--ask-file` or `--draft-file`
  must sit inside the run directory; write test files into `$RD`.

## Proof and skip reporting

- CLI proof: argv, exit code and envelope (in `evidence/steps.json` for `verify.py run`; in your log for a recipe run
  by hand).
- Report proof: `evidence/report.html`, `summary.json` checks, live browser measurements and screenshots someone
  actually looked at.
- Account for each entry point separately. A flag not exercised (for example `--narrative`) is reported as not run,
  not as covered by the plain render. A recipe that needs something you do not have (a web-search key, a print
  driver) is `BLOCKED`, never `PASS`.

## Feature entry contract

Each feature file starts with an H1 and one paragraph, then exactly four H2 sections in this order:
`Sub-features`, `How to get to it (user POV)`, `Driving it with verify.py and a browser`, `Gotchas`. Each names the
commands, flags, exit codes and files written, and gives a recipe that drives them.

## Features

- [Run lifecycle](./run-lifecycle.md) covers init, validate (a run or one file with `--kind`), run
  confirm/route/rescope/reopen, finalize and versioning, the org profile, the run lock and `rqh --version`.
- [Run status and next step](./run-status.md) covers `rqh status`, the `next_skill` router answer, run resolution and
  `RQH_WORKSPACE`.
- [Requests and candidates](./requests-and-candidates.md) covers `rqh requests`, `rqh candidates`, `run pause` and
  `run resume`, and the refusals on a finalized run.
- [Memory library](./memory-library.md) covers `rqh library search/add/list/remove/validate`.
- [Web search](./web-search.md) covers the optional `rqh search` and its `TAVILY_API_KEY`.
- [Report rendering](./report-rendering.md) covers `rqh report` with and without a narrative, and its exit codes.
- [Reading the report](./report-in-browser.md) covers section order, charts, mobile width, interactivity and theme.
