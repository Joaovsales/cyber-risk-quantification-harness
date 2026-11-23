# Report rendering

A user turns a finalized version into one self-contained `report.html`, optionally with a narrative file whose
figures must come from placeholders. A narrative that states a figure in prose, or uses a placeholder rqh does not
know, is refused with exit 4, whether it is passed now or was stored by an earlier render, and nothing is written.

## Sub-features

- `render` writes `v<N>/report.html` from `v<N>/` only, byte-identical on a repeat. The success `data` keys are
  exactly `path`, `version` and `narrative_omitted`.
- `version` renders an earlier version with `--version N`; the default is the latest.
- `narrative-accept` validates a `--narrative` file, stores it as `v<N>/narrative.md` and shows its resolved figures as
  the takeaway.
- `narrative-persist` reuses a stored `v<N>/narrative.md` on every later render of that version without `--narrative`.
- `narrative-reject` returns exit 4 with an issue at `narrative.line.<n>`, rule `literal_figure` (a figure written in
  prose) or `unknown_placeholder` (an unknown field or filter), and the offending token in the message. It writes
  neither `report.html` nor `narrative.md`.
- `stored-reject` returns exit 4 for a stored `v<N>/narrative.md` that no longer passes the rule (for example after a
  hand edit), and writes nothing; `--omit-narrative` still renders.
- `omit` renders with the fixed takeaway and reports `narrative_omitted: true`. It does not delete a stored narrative.
  With `--narrative` as well, the narrative is validated and stored but the fixed takeaway is shown.
- `currency` re-checks the version's currency at render: a `run_summary.json` whose currency is not a three-letter
  ISO code is exit 1 at `v<N>/run_summary.json.currency`, and nothing is written.
- `missing` returns exit 5 for a run with no finalized version, a missing version (`--version 7`), or a missing
  `--narrative` file.

## How to get to it (user POV)

- `rqh report <run> [--version N] [--narrative FILE] [--omit-narrative]`

## Driving it with verify.py and a browser

Preconditions:

- For the render checks, a `verify.py run` has finished with `"ok": true`, and its `ws/` still exists (run `cleanup`
  only afterwards). For the rest, a confirmed and finalized run made by hand as in
  [the index](./README.md#a-workspace-by-hand).

- **Render.** `verify.py run` already covers this: `render_idempotent`, `csp_meta_exact`, `size_budget`,
  `no_external_refs` and `section_order` all pass.
- **Missing.** Run `rqh report` against a run that is only confirmed: exit 5. On a finalized run, `--version 7` is
  exit 5, and `--narrative missing.md` is exit 5.
- **Keys.** A plain `rqh report credential-phishing-bec` is exit 0 with `data` keys `narrative_omitted` (false),
  `path` and `version`.
- **Narrative accepted.** Write `good.md` containing
  `Today a year costs about {{ baseline.annual_loss.mean|money }}.`, then run
  `rqh report credential-phishing-bec --narrative good.md`. Expect exit 0, a `v1/narrative.md` file, and the sentence
  with its money figure in the takeaway.
- **Literal figure.** Write `bad.md` containing `This costs $2M a year.` and run the same command. Expect exit 4, an
  issue at `narrative.line.1` with rule `literal_figure` whose message holds `$2M`.
- **Unknown placeholder.** Write `unk.md` containing `{{ baseline.annual_loss.mean|usd }}`: exit 4, rule
  `unknown_placeholder`. After both rejections `report.html` is byte-unchanged and `v1/narrative.md` still holds the
  good narrative.
- **Omitted.** Run `rqh report credential-phishing-bec --omit-narrative`. Expect exit 0, `data.narrative_omitted`
  true, the narrative sentence absent from the page, and `v1/narrative.md` still present.
- **Persisted.** A plain `rqh report credential-phishing-bec` afterwards shows the stored narrative again
  (`narrative_omitted` false).
- **Both flags.** `rqh report credential-phishing-bec --narrative good.md --omit-narrative`: exit 0, the fixed
  takeaway in the page.
- **Stored narrative broken.** Write `It costs $2M.` into `v1/narrative.md` by hand. A plain render is exit 4 and
  `report.html` is byte-unchanged; `--omit-narrative` is exit 0.
- **Currency.** In a copy of the run, change `"currency": "USD"` in `v1/run_summary.json` to `"currency": "US$"`: a
  render is exit 1 at `v1/run_summary.json.currency`.
- **Versions.** Reopen and finalize again: `rqh report … --version 1` renders `v1` (`data.version` 1), and a plain
  render writes `v2/report.html`.

## Gotchas

- Rendering reads only `v<N>/`. Editing `inputs.yaml`, `scenario.yaml` or the org profile after finalize does not
  change the report. Re-finalize to see the edits.
- A stored narrative belongs to its version; a new version starts without one.
- The narrative rule has no "not yet implemented" escape: a narrative with a literal figure that renders with exit 0 is
  a regression.
