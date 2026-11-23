---
name: risk-quant-memory
description: Use after a risk-quantification report is finished to save the figures the organisation really measured or judged (the end-of-run batch, invoked once by the router), or when the user wants to browse, add, prune or re-validate the memory library of real figures. It asks one yes or no per item and stores nothing without a yes.
---

# risk-quant-memory: the library of real figures

The memory library holds the organisation's own derived figures, so the next run can start from them. It stores a value, a pointer to its source and a sensitivity flag; it never holds raw exports or personal data. `rqh library add` is the only write path. Nothing is stored without a yes from the user.

## Ground rules

- Run `rqh` from the PATH; if it is not found, use `python -m rqharness` with the same arguments. The workspace is `./.riskquant/`.
- Ask with the host's structured question tool when it has one (in Claude Code, `AskUserQuestion`). Otherwise show numbered options and accept a number or free text.
- Never write or edit anything under `.riskquant/library/` yourself; only `rqh library add` and `rqh library remove` change it.
- Never edit `run.yaml`, `requests.yaml`, `inputs.yaml` or any `v<N>/` file. This skill reads a run and leaves it unchanged.
- Memory holds derived figures only: never paste a raw export, a message, a document body or a personal detail into `note` (at most 500 characters). Name roles, not individuals. Always set `sensitivity`.
- You send nothing to anyone.

## Batch mode (end of run)

The router invokes this once after `report`. If the session ended before then, the user can run this skill later.

1. Take the run id from the caller, or ask the user (numbered options) when there are several runs. Read `inputs.yaml` and `scenario.yaml` for it, read only.
2. List the items: every estimate whose `provenance.tier` is `internal_data` or `sme_estimate`, which means a figure a person or a system confirmed. Skip an estimate that already has a `memory` source, because it came from the library. Skip `benchmark` and `agent_assumption`. If the list is empty, tell the user there is nothing to save and stop.
3. Ask exactly ONE yes or no per item, never a blanket question. The question shows the parameter, the range with its unit, its source role or system, the sensitivity you propose (`internal` by default, `confidential` for figures about legal exposure, personnel or a named customer) and the scenario type. Accept a changed sensitivity in the same answer.
4. For each yes, write the entry to a scratch file `.riskquant/library-entry.draft.yaml` (not inside `.riskquant/library/`) and run `rqh library add .riskquant/library-entry.draft.yaml --json`. The entry:
   - `schema_version: "1"`, and an `entry_id` slug of lowercase letters, digits and hyphens, 2 to 63 characters, from the scenario id and the parameter path (underscores and dots become hyphens).
   - `parameter_family` (the estimate path), `value` (the estimate's min, mode, max and unit, no provenance) and `tier`.
   - `source`: a copy of the run's source row, with an `id` slug, `kind`, `title` and `owner_role`, no personal names, and `retrieved_at`.
   - `scenario_tags` (the scenario's `scenario_type`), `segment` (the scenario's `industry` and `size_band`), `period` (`start` and `end`, `YYYY-MM-DD`: the period the figure covers, or the year before the retrieval date when it does not say), `captured_at` (today), `stale_after_months` (default 18), `sensitivity`, and a short `note` saying how the figure was derived.
5. On exit 1 show each issue's `path` and `message`, fix the entry with the user, and run it once more; do not fix by dropping the sensitivity. A `Duplicate` result is fine: tell the user it was already stored. Remove the scratch file when the item is done.
6. Finish with one line: how many entries were stored, how many already existed, how many the user declined.

## Browse, add, prune and re-validate

When the user invokes this skill directly:

- Browse: run `rqh library list --json`, or `rqh library search --family <path> --json` (with `--scenario-type`, `--industry`, `--size-band` or `--currency` to narrow) and show hits with their origin, sensitivity and whether they are `stale`.
- Add: ask the user for the figure and its source (one question at a time), build the entry as in batch step 4, show it, and ask one yes or no before `rqh library add`.
- Prune: show the entry, ask one yes or no, then run `rqh library remove <entry_id>`. Stale entries (older than their `stale_after_months`) are the ones to offer first, never remove them unasked.
- Re-validate: run `rqh library validate --json` and show each issue's `path` and `message`.
