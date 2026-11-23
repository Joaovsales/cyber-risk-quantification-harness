---
name: simulate
description: Use when `rqh status` names `simulate` as the next skill, or when the user asks to run, rerun or finalize the Monte Carlo simulation for a risk-quantification run whose inputs are valid. It runs `rqh finalize` and reports the new version. It asks the user nothing.
---

# simulate: run the Monte Carlo and write a version

`rqh finalize` validates the run, simulates the baseline and every variant, and writes a new `v<N>/` directory. You run it and report. You compute nothing and ask nothing. This phase never invokes another phase skill.

## Ground rules

- Run `rqh` from the PATH; if it is not found, use `python -m rqharness` with the same arguments. Read each envelope (`ok`, `data`, `issues`) and exit code. A non-zero exit is shown to the user in plain words, with each issue's `path` and `message`, and the phase stops.
- Never edit `run.yaml`, `inputs.yaml` or any `v<N>/` file.

## Steps

1. Run `rqh status <run> --json`. Read `data.n` and `data.seed`: these are what `finalize` will use. If `data.next_skill` is not `simulate`, tell the user what it is instead and stop here, with the hand-off below.
2. Run `rqh finalize <run> --json`. Add `--n` or `--seed` only when the user asked for different values for this version.
3. On exit 0, tell the user the version (`data.version`), `n` and `seed` from `data`, and the path (`data.path`).
4. On exit 1 with a `lock_held` issue, another finalize is running or was cut short: tell the user, and stop. Do not delete the lock yourself.
5. On exit 1 with validation issues, show each `path` and `message`; the inputs need fixing, so stop. On exit 3 (illegal transition), say the run is not in a state that can be simulated and show `rqh status` output; do not run `rqh run reopen` unless the user asks for another version.

## Hand-off

Run `rqh status <run> --json`. Tell the user the `next_skill` it returns, in one sentence, or quote `reason` when it is null. Say it without invoking it: the router or the user starts the next skill. When the `risk-quant` router invoked you, that sentence is not the end of the reply: hand back to the router, which runs `rqh status` again and carries on in the same reply. Never invoke another phase skill from here.
