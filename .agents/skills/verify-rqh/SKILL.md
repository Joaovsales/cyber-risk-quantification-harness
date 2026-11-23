---
name: verify-rqh
description: Prove risk-quantification-harness works through its real user surfaces — drive the `rqh` command (init, validate, run confirm, finalize, report, status, and the requests, candidates, library and search commands) in a throwaway workspace on the shipped sample run, then open the written report.html in a browser and check it. Use before opening a pull request that changes src/rqharness/, after any change to the report, or when asked "does the report still render", "verify rqh end to end".
disable-model-invocation: false
harness: universal
---

# verify-rqh — drive `rqh` and read the report it writes

## Surface and capability ceiling

- **Primary surface:** the `rqh` CLI. Each command prints a JSON envelope `{schema_version, ok, data, issues}` with
  `--json` and sets an exit code (0 ok, 1 rejected, 2 usage, 3 illegal transition, 4 narrative rejected, 5 missing).
- **Secondary surface:** the self-contained `report.html` that `rqh report` writes into `v<N>/`, read in a browser.
- **Out of scope:** the Claude Code plugin skills in `skills/` and the agents in `agents/`. They are verified by their
  eval suites under `evals/` (the offline replays run in `tests/replays/`; `evals/run_live.py` runs the live suite),
  not by this skill.
- **What you need:** this repository, its venv (Python ≥ 3.11 with `pip install -e ".[dev]"`) and a Chromium-family
  browser (Edge, Chrome or Chromium). Nothing else.
- **Driver:** `scripts/verify.py` (subprocess calls to `python -m rqharness` from this checkout, an HTML parser, and
  headless Edge or Chrome screenshots), plus a browser you can run JavaScript in for the live DOM checks: the DevTools
  console of any Chromium browser, or an agent's browser tool (for example the Claude Code browser pane,
  `mcp__Claude_Browser__*`).
- **Strongest proof:** CLI = exit codes plus envelopes plus persisted files read back through `rqh status` (FUNCTIONAL).
  Report = parsed structure (STRUCTURAL), live DOM measurements (DOM-FUNCTIONAL), and full-page screenshots (VISUAL,
  only once someone has looked at the PNG). A visual criterion that nobody looked at is `BLOCKED`, never `PASS`.
  Printing is not checked (no driver); report it as `BLOCKED` if a criterion asks.

## Launch

`rqh` is a short-lived CLI with no server, so there is nothing to keep running. Every drive builds its own workspace.

```bash
.venv/Scripts/python.exe .agents/skills/verify-rqh/scripts/verify.py run            # Windows
.venv/bin/python .agents/skills/verify-rqh/scripts/verify.py run                    # macOS / Linux
```

- **Isolation:** each `run` creates `<out>/<timestamp>-<6 hex>/` with `ws/` (the workspace; every `rqh` call runs with
  `cwd=ws` and `RQH_WORKSPACE` unset, so the workspace is `ws/.riskquant/`) and `evidence/`. `<out>` defaults to
  `$RQH_VERIFY_OUT` or `<system temp>/rqh-verify`. Concurrent runs never share state.
- **Options:** `--route yolo|accuracy` (default `yolo`), `--n` (default 50000), `--seed` (default 20261109), `--out DIR`,
  `--profile FILE` (an org profile installed as `.riskquant/org-profile.yaml` before finalize;
  `tests/routing/fixtures/org-profile.yaml` gives a theme accent, a display name, people and systems).
- **Readiness:** the command returns. Exit 0 means every step and check passed; the JSON on stdout names `run_dir`.
- **Teardown ownership:** this run owns `run_dir/ws`, `run_dir/profile-*`, `run_dir/mobile-frame.html` (present only
  while screenshots are taken, or after a crash during them) and, after `serve`, the one server PID in
  `run_dir/server.pid`. Nothing else.

## Doctor

```bash
.venv/Scripts/python.exe .agents/skills/verify-rqh/scripts/verify.py doctor
```

This is read-only. It requires all of these: Python ≥ 3.11; `rqharness` imported from THIS checkout's `src/`
(the path is printed); the sample run at `tests/validate/fixtures/sample-run/`; and `design/concepts/report.html` at
SHA-256 `525413fd…54ac7` (spec decision D25 in `specs/v1-harness.md`). It also names the headless browser it found.
Stop on `"ok": false`.

## Drive

`verify.py run` performs these user steps in order, each through `python -m rqharness <args> --json`:

1. `rqh init` → exit 0. It creates `.riskquant/` with a `.gitignore` of `*`.
2. Copy the sample run directory `tests/validate/fixtures/sample-run/` (its `scenario.yaml` and `inputs.yaml`) to
   `.riskquant/runs/credential-phishing-bec/`. This is the user writing their run files. With `--profile`, the profile
   is copied to `.riskquant/org-profile.yaml` first.
3. `rqh validate credential-phishing-bec` → exit 0.
4. `rqh run confirm credential-phishing-bec --route yolo --n 50000 --seed 20261109` → exit 0.
5. `rqh finalize credential-phishing-bec` → exit 0, `data.version` 1, `data.n`/`data.seed` as given.
6. `rqh report credential-phishing-bec` → exit 0, `data.path` …`/v1/report.html`.
7. `rqh report credential-phishing-bec` again → byte-identical file (`render_idempotent`).
8. `rqh status credential-phishing-bec` → the second view: `status` finalized, `latest_version` 1, `next_skill` null.

`evidence/steps.json` is written at this point, before any browser starts, so a browser fault cannot lose it.

Static report checks (`checks[]` in the JSON):
- `csp_meta_exact` (the policy allows the one inline script by its own SHA-256, plus `base-uri 'none'` and
  `form-action 'none'`)
- `section_order` (`data-section` = takeaway, summary, lec, distribution, drivers, variants, scenario, provenance,
  appendix, collect)
- `section_numbers` (the `.sec-no` labels read 01 to 09)
- `title_suffix` (the page `<title>` ends with "/ risk report")
- `appendix_collapsed` (a `<details>` without `open`)
- `yolo_banner_matches_route`
- `size_budget` (≤ 1,000,000 bytes)
- `no_external_refs`
- `no_css_import_or_remote_url`
- `static_charts_present` (one `svg[role=img]` for the LEC plus one per `#hists .hist`; exactly 4 for the sample)
- `collect_requests` (exactly the sample's 3 "What to collect" requests, each with "Owner" and "System of record")
- `profile_applied` (only with `--profile`: the masthead badge `.org` is the profile's `theme.display_name`, else its
  `org_name`)
- `status_second_view`
- `finalize_n_seed`

Then the live browser checks:

```bash
.venv/Scripts/python.exe .agents/skills/verify-rqh/scripts/verify.py serve <run_dir>    # prints {"url": ...}
```

Open the printed `url` (`http://127.0.0.1:<free port>/report.html`) and run each expression in the page (DevTools
console, or the browser tool's JavaScript call):

- Mobile: set the viewport to 375×812 (DevTools device toolbar, or `resize_window` `width: 375, height: 812`), reload,
  then `[innerWidth, document.documentElement.scrollWidth]`. The two numbers must be equal (no page scroll at 375 px;
  a chart inside its own `overflow-x` figure is allowed).
- Order: `[...document.querySelectorAll('[data-section]')].map(e => e.dataset.section)` must match the static check.
- Collect: the "What to collect to improve the degree of accuracy" section lists three requests, each with an owner and
  a system: `[...document.querySelectorAll('#s09 li.ck')].map(li => li.querySelector('h3').textContent)`.
- Script: `document.documentElement.classList.contains('js')` is true.
- Threshold: type `750k` into `#thr-in`. The "Chance annual loss exceeds" rows change and `#thr-lbl` reads `$750k`.
  Type `abc`: `#thr-help` gains the class `err` and asks for an amount such as 750k.
- Variant toggle: click the second radio in `#hv-toggle` (`input[name=hv]`). It becomes `checked`, and
  `[...document.querySelectorAll('#hists .hist:not(.is-hidden)')].map(h => h.dataset.variant)` returns only that
  radio's `value`.
- Theme: `getComputedStyle(document.documentElement).getPropertyValue('--sig')` is `#E61919` in light mode and
  `#FF2A2A` in dark mode (DevTools Rendering → `prefers-color-scheme`, or `resize_window` `colorScheme`). On a
  `--profile` run it is the profile's accent (`#1F6FEB` for the fixture) in light mode.
- Reset the viewport (`resize_window` `preset: "desktop"`) when done.

VISUAL: open `evidence/report-desktop-1280.png` and `evidence/report-mobile-375.png` and compare them against
`design/concepts/report.html` (Swiss print look, numbered sections 01–09, one signal colour, hairline charts). Headless
Edge may report `prefers-color-scheme: dark`, so a dark screenshot is expected. Record what you looked at.

## Evidence

`<run_dir>/evidence/` holds the proof and survives cleanup:
- `summary.json`: steps, checks, screenshot paths and `ok`.
- `steps.json`: every argv, exit code, full envelope and stderr tail.
- `report.html`: a copy of the rendered report.
- `report-desktop-1280.png` and `report-mobile-375.png`: present when a headless browser exists.

Quote `summary.json`'s `ok`, the failing check names, and the live browser measurements in the verification report.

## Cleanup

```bash
.venv/Scripts/python.exe .agents/skills/verify-rqh/scripts/verify.py cleanup <run_dir>
```

Cleanup stops only the PID recorded in `run_dir/server.pid` (`taskkill /PID <pid> /T` on Windows, SIGTERM elsewhere;
never by process name). It deletes `run_dir/ws`, `run_dir/profile-*` and a leftover `run_dir/mobile-frame.html`, and
lists the evidence files it kept. Run it after every iteration, including failed ones. Then `ls <run_dir>/evidence` to
confirm the proof survived.

## Helpers

- `scripts/verify.py` is the only helper: `doctor`, `run [--route] [--n] [--seed] [--out] [--profile]`, `serve <run_dir>`,
  `cleanup <run_dir>`. Run it with the repo's venv Python (it imports nothing from `rqharness` itself).
- `tests/replays/` loads `check_report` from `verify.py` and tests the driver itself, so `pytest tests/replays` must
  stay green after any change to the script.

## Feature map

Read [`features/README.md`](features/README.md) and use the matching feature file as the recipe.

## Maintenance

When a change alters user-facing behaviour (a command, flag, exit code, file written, or what the report shows),
update the matching feature file in the same pull request, run its recipe, and add or fix a `verify.py` check when the
behaviour is one the sample drive exercises. A surface with no feature file gets one, in the format the
[feature entry contract](features/README.md#feature-entry-contract) gives.
