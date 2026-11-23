---
name: risk-quant
description: Use when the user gives a cyber risk scenario in a sentence (for example "what would a ransomware attack cost us a year?") or asks to quantify, estimate or model a risk, or to continue a risk-quantification run. This is the front door. It runs the whole chain by asking `rqh status` which skill comes next and invoking it, and it does no phase work itself.
---

# risk-quant: the router

You route. You never scope, collect, simulate or write a report yourself. The `rqh` command owns which skill comes next; you ask it, invoke that skill, and ask again. You ask the user nothing of your own: any question belongs to the skill you invoke.

## Ground rules

- `rqh` alone validates, simulates, computes every number and writes the report. Skills converse, propose and run `rqh ... --json`, then read the envelope `{schema_version, ok, data, issues}` and the exit code (0 ok, 1 rejected, 2 usage, 3 illegal transition, 4 narrative rejected, 5 missing artifact).
- Run `rqh` from the PATH (installed with `pipx install risk-quantification-harness` or `uv tool install risk-quantification-harness`). If `rqh` is not found, use `python -m rqharness` with the same arguments.
- The workspace is `./.riskquant/` in the current project. It is private: its `.gitignore` holds `*`.
- Wording: say "estimate", and call the method FAIR-aligned. Do not invent figures.
- You send nothing to anyone. Messages to people are drafts the user sends.

## The loop

1. If `.riskquant/` is missing, run `rqh init --json` once.
2. Find the run.
   - The user named a run id or folder: use it.
   - The user gave a new scenario sentence and there is no run for it yet: there is no run directory for `rqh status` to read, so invoke `scope-scenario` directly with the sentence. It creates the run directory `.riskquant/runs/<scenario_id>/`; when it returns, continue from step 3 with that `scenario_id` as the run.
   - The user gave nothing: list the folders under `.riskquant/runs/`. Use the only one, or show the list as numbered options when there are several.
3. Run `rqh status <run> --json`. Read `data.next_skill`, `data.status`, `data.reason` and `data.waiting_on`.
4. Invoke the skill named by `next_skill`, passing the run id and the scenario sentence if there is one.
5. When it returns, run `rqh status <run> --json` again and compare. Repeat from step 3. A skill's closing line, such as "the next skill is `collect-data`" or "the router will start it", is that skill handing back to you, not the end of your reply: keep going in the same reply until a stop rule below holds.

Stop when any one of these holds:

- `next_skill` is `null`. Tell the user `reason`; if `waiting_on` is not empty, name the open requests it lists. The run is either done or waiting for answers.
- A skill returned and both `data.status` and `data.next_skill` are unchanged from before you invoked it. That skill stopped for the user (a failed command, a declined confirmation). Show what it reported and stop. Never invoke the same skill again on an unchanged state.
- The user ends the session.

After the `report` skill returns inside the loop, invoke `risk-quant-memory` in batch mode exactly once, then stop. Do not invoke it at any other point, and not again if the loop re-enters `report`.

Show the user, at each step, one line: which skill you are invoking and why (`reason`). When the loop ends, give the report path if `rqh status` shows `latest_version` and the run is finalized: `.riskquant/runs/<run>/v<latest_version>/report.html`.

## When the host cannot invoke a skill

Some hosts cannot invoke a skill by name. Then read `skills/<next_skill>/SKILL.md` (relative to this plugin's root), follow it inline as if you were that skill, and continue the loop from step 5. The same stop rules apply. Do this for the memory batch too.

## Never

- Edit `run.yaml`, `requests.yaml` or any `v<N>/` file. Only `rqh` writes them.
- Pick the next skill yourself from the conversation. The answer is always `next_skill` from `rqh status`.
- Invoke two skills in a row without running `rqh status` between them.
