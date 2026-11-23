---
name: report
description: Use when `rqh status` names `report` as the next skill, or when the user asks for the report, the write-up or the executive summary of a finalized risk-quantification run. It writes a short narrative using only placeholders, runs `rqh report`, and gives the user the path to the single-file HTML report. It asks the user nothing.
---

# report: the narrative and the HTML report

`rqh report` renders the report. You write only the short narrative that becomes its takeaway, and you write it with placeholders, because every number a reader sees is computed by `rqh` from `run_summary.json`. This phase never invokes another phase skill.

## Ground rules

- Run `rqh` from the PATH; if it is not found, use `python -m rqharness` with the same arguments. Read each envelope (`ok`, `data`, `issues`) and exit code. A non-zero exit other than 4 is shown to the user in plain words, with each issue's `path` and `message`, and the phase stops.
- Never type a figure. A number you write yourself is rejected by the renderer.
- Never edit anything inside `v<N>/`. Write only `narrative.draft.md`, in the run directory `.riskquant/runs/<run>/`.
- Say "estimate", and call the method FAIR-aligned. You ask the user nothing.

## Steps

1. Read `.riskquant/runs/<run>/v<N>/run_summary.json` for the latest version `N` (`data.latest_version` from `rqh status <run> --json`). Use it only to learn which variant ids exist (`variants[].id`, the first is `baseline`), which have an `annual_cost`, and the quality grade. Do not copy any number out of it.
2. Write `narrative.draft.md` in two to four short paragraphs: what the scenario costs a year, how a bad year looks, what each variant would change, and how much to trust it (the quality grade). Use only placeholders for figures.
3. Run `rqh report <run> --narrative .riskquant/runs/<run>/narrative.draft.md --json`. The file path is relative to the current directory, not to the run.
4. On exit 0, give the user `data.path` (the report) and one sentence on what it shows.
5. On exit 4 the narrative was rejected. The envelope has one issue; its `path` is `narrative.line.<L>` and its `message` names the offending token. Rewrite the draft ONCE: on line `L`, replace that token with a placeholder or reword the sentence so it states no figure. Run the same command again.
6. If the retry is also rejected, do not try again. Run `rqh report <run> --omit-narrative --json` so the run still ends with a report, and tell the user the narrative was left out and why.

## Placeholders

A placeholder is `{{ <path> }}` or `{{ <path>|<format> }}`.

- `<variant>.<metric>.<stat>`: `<variant>` is `baseline` or a variant id from the summary. `<metric>` is `annual_loss`, `lef` or `event_count`, with `<stat>` one of `mean`, `median`, `p10`, `p25`, `p75`, `p90`, `p95`, `p99` for `annual_loss` and `mean`, `median`, `p90` for `lef` and `event_count`. `<variant>.annual_cost.mean` gives a variant's yearly cost.
- `delta.<variant>.<metric>.<stat>`: the baseline minus that variant, for example `delta.mfa.annual_loss.mean`. `delta.<variant>.return_on_control.mean` is the return on the control.
- `{{ quality.grade }}`: the data-quality grade, a letter.
- Formats: `money` (the default for `annual_loss` and `annual_cost`), `pct`, `rate` (the default for return on control), `int`. `|pct` on a delta is the cut relative to the baseline's same statistic. `lef` and `event_count` default to two decimals.

## The literal rule

Prose may not state a number. In plain words:

- No digits next to a currency symbol or code, a percent sign, or a magnitude such as `k`, `m`, `bn`, `million` or `billion`.
- No spelled-out numbers from two upward (two, three, ten, twenty, and so on). The word "one" as a pronoun is fine.
- No ratios or frequencies such as "1 in 20" or "one year in ten". Say "in a bad year" and use a `p90` placeholder.

When unsure, use a placeholder or leave the number out.

## Worked example

```markdown
We estimate that this scenario costs {{ baseline.annual_loss.mean|money }} a year on average. In a bad year the loss reaches {{ baseline.annual_loss.p90|money }} or more.

Adding multi-factor authentication would cut the average annual loss by {{ delta.mfa.annual_loss.mean|money }}, which is {{ delta.mfa.annual_loss.mean|pct }} of today's level, and would leave {{ mfa.annual_loss.mean|money }} a year. Against its yearly cost of {{ mfa.annual_cost.mean|money }}, the return on control is {{ delta.mfa.return_on_control.mean }}.

The inputs behind this estimate earn a data-quality grade of {{ quality.grade }}.
```

Use the variant ids that are really in the summary (`mfa` above is only an example), and omit the sentences about a variant that has no `annual_cost`.

## Hand-off

Run `rqh status <run> --json`. Tell the user the `next_skill` it returns, in one sentence, or quote `reason` when it is null (the run is done). Say it without invoking it: the router or the user starts the next skill. When the `risk-quant` router invoked you, that sentence is not the end of the reply: hand back to the router, which runs `rqh status` again and carries on in the same reply. Never invoke another phase skill from here.
