---
name: scope-scenario
description: Use when a risk-quantification run has no scoped scenario yet, when `rqh status` names `scope-scenario` as the next skill, or when the user wants to scope or re-scope a cyber risk scenario. It interviews the user, writes scenario.yaml, validates it, and asks one structured question to confirm the scenario and choose the route (YOLO or Accuracy), the draw count n and the seed.
---

# scope-scenario: the scoping interview

Turn a scenario sentence into a validated `scenario.yaml`, then confirm it with the user once. This phase never invokes another phase skill.

## Ground rules

- `rqh` alone validates and records state. You converse and propose; you run `rqh ... --json` and read the envelope (`ok`, `data`, `issues`) and the exit code. A non-zero exit is shown to the user in plain words, with each issue's `path` and `message`, and the phase stops there.
- Run `rqh` from the PATH; if it is not found, use `python -m rqharness` with the same arguments. The workspace is `./.riskquant/`; run `rqh init --json` first if it does not exist.
- Ask with the host's structured question tool when it has one (in Claude Code, `AskUserQuestion`). Otherwise show numbered options and accept a number or free text.
- Write only `scenario.yaml`. Never edit `run.yaml`, `requests.yaml` or any `v<N>/` file; `rqh` owns them.
- Say "estimate", never anything stronger. Do not put figures in the scenario: this phase has no numbers.

## 1. Prepare

1. If `.riskquant/org-profile.yaml` exists, read it. Use its `org_name`, `segment` and system names to make the interview shorter; do not ask for what it already says. If it does not exist, carry on without it. Never run org setup from here.
2. Take the scenario sentence from the user's request, or ask for it in plain words if there is none.

## 2. Interview

Ask short questions, a few at a time, only for what the sentence leaves open. Aim to fill every field below. Offer a proposed answer for each so the user can just agree.

| Field in `scenario.yaml` | What it holds |
|---|---|
| `title` | a short name |
| `scenario_statement` | one or two sentences in the user's words |
| `scenario_type` | one of `ransomware`, `business_email_compromise`, `credential_phishing`, `third_party_breach`, `cloud_misconfiguration`, `ddos`, `insider_data_theft`, `lost_or_stolen_device`, `other` |
| `segment` | `industry` (a lowercase slug or `any`) and `size_band` (`smb`, `mid_market`, `enterprise` or `any`) |
| `threat_actor` | `category`, `description`, optional `intent` |
| `asset` | `description`, optional `location_context` and `sensitivity_or_volume_notes` |
| `method` | `description` of how the loss event happens |
| `effects` | list of `{cia_dimension: confidentiality\|integrity\|availability, description}` |
| `loss_event_definition` | the exact event that counts as one loss event |
| `out_of_scope` | list of things this estimate excludes |
| `controls_context` | the controls in place today |

Also set `schema_version: "1"` and `scenario_id`, a lowercase slug of letters, digits and hyphens (2 to 63 characters, for example `ransomware-finance-systems`).

## 3. Write and validate

1. Create `.riskquant/runs/<scenario_id>/` if needed and write `scenario.yaml` there. Follow `schemas/scenario.v1.json`; unknown keys are rejected.
2. Run `rqh validate <scenario_id> --json`. On exit 1, fix the named `path`s with the user and validate again. On any other non-zero exit, show it and stop.

## 4. Confirm (exactly one question per pass)

Ask exactly ONE structured question per confirmation pass. It shows the scenario in a few lines (title, type, segment, loss event definition, out of scope) and asks the user to decide, in one question, the following together:

- Confirm the scenario as written, or go back to change it.
- Route: **YOLO** (default: the harness gathers benchmarks itself and asks you nothing more) or **Accuracy** (the harness routes each input to the people and systems that hold the data, and you confirm what comes back).
- `n`, default 50,000 draws, and the seed, default a random seed that `rqh` draws and records. Either route can change them.

Offer the options as: "Confirm, YOLO route, defaults", "Confirm, Accuracy route, defaults", "Confirm and set n or seed", "Change the scenario". If the user picks the third, take `n` and seed as free text in that same answer; do not ask a second question.

- On a yes: run `rqh run confirm <scenario_id> --route <yolo|accuracy> --n <n> --seed <seed> --json`, leaving out `--n` and `--seed` for the defaults. On exit 0 tell the user the route, `n` and the stored seed from `data`. On a non-zero exit, show it and stop.
- On a decline: return to step 2 with what the user said, rewrite and revalidate `scenario.yaml`, and ask the question again as a new pass. Each pass has exactly one question.

## Hand-off

Run `rqh status <scenario_id> --json`. Tell the user the `next_skill` it returns, in one sentence. If `next_skill` is null, quote `reason` instead. Say it without invoking it: the router or the user starts the next skill. When the `risk-quant` router invoked you, that sentence is not the end of the reply: hand back to the router, which runs `rqh status` again and carries on in the same reply. Never invoke another phase skill from here.
