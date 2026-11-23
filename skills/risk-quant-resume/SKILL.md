---
name: risk-quant-resume
description: Use when the user wants to resume, continue or check on an existing risk-quantification run, for example after waiting for data owners to answer ("pick up the ransomware run", "any answers yet?", "continue my risk estimate"). It reads the run's state and enters the router loop, starting with collect-data when the run is waiting for data. It writes nothing of its own.
---

# risk-quant-resume: pick a run up again

A thin entry into the router loop for a run that already exists. It reads the run's state, then hands the whole chain to the `risk-quant` router. It scopes, collects, simulates and reports nothing itself, writes nothing, and asks the user nothing of its own beyond which run to resume.

## Ground rules

- `rqh` alone validates and records state. Run `rqh ... --json` and read the envelope (`ok`, `data`, `issues`) and the exit code. A non-zero exit is shown to the user in plain words, and you stop there.
- Run `rqh` from the PATH; if it is not found, use `python -m rqharness` with the same arguments. The workspace is `./.riskquant/`.
- Ask with the host's structured question tool when it has one (in Claude Code, `AskUserQuestion`). Otherwise show numbered options and accept a number or free text.
- Never edit `run.yaml`, `requests.yaml`, `inputs.yaml` or any `v<N>/` file. Only `rqh` and the skills you hand over to change the workspace.
- You send nothing to anyone. Messages to people are drafts the user sends.

## Steps

1. Find the run.
   - The user named a run id or folder: use it.
   - Otherwise list the folders under `.riskquant/runs/`. Use the only one, or show the list as numbered options (or one structured question) when there are several, and ask which to resume. If there is no workspace or no run, tell the user there is nothing to resume and suggest giving a scenario sentence to the `risk-quant` router.
2. Run `rqh status <run> --json`. Tell the user, in one or two sentences, the `status`, the number of open requests and pending candidates, and the `next_skill` or `reason`.
3. If `data.status` is `awaiting_data`, invoke `collect-data` first, passing the run id. It handles resumed collection: it records answers, confirms candidates and decides with the user whether to finalize or keep waiting. When it returns, run `rqh status <run> --json` again.
4. Enter the router loop: invoke the `risk-quant` router with the run id, which repeats status, invoke `next_skill`, status until `next_skill` is null or a skill stops for the user. If the host cannot invoke a skill by name, read `skills/risk-quant/SKILL.md` and follow its loop (and its fallback) inline with the same run.

Do not choose the next skill yourself. After step 3, the answer is always the `next_skill` that `rqh status` reports, and the router asks for it.

## Never

- Never write any file, or run a command that changes the run, other than through the skills you invoke.
- Never invoke `simulate`, `report` or `scope-scenario` yourself; only the router chains phases.
- Never resume a run on the user's behalf without naming it first.
