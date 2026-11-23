# Memory library

The library holds reusable parameter values: the organisation's own memory under `.riskquant/library/` and the
benchmarks shipped inside the package. A user (or the memory skill) adds an entry from a YAML file, lists and prunes
memory, re-validates it after hand edits, and searches both for a parameter family; inputs reference entries by id.

## Sub-features

- `add` validates one library-entry file and writes it to `.riskquant/library/<entry_id>.yaml`. The same content again
  is `result` `duplicate`; the same `entry_id` with other content is exit 1, rule `entry_id_conflict`.
- `list` returns `data.entries` with `entry_id`, `parameter_family`, `tier` and `sensitivity` for memory only.
- `search` returns `data.hits` for `--family`, memory first, then the better segment match, then the newer period.
  Each hit has `entry_id`, `origin` (`memory` or `benchmark`), `stale`, `currency_mismatch` (set when `--currency` is
  given and the entry's unit is another ISO currency), `segment_match` and the `entry`. `--scenario-type`,
  `--industry` and `--size-band` filter (an entry tagged `any` still matches).
- `remove` deletes the one memory file that holds an id, in any subfolder; an unknown id is exit 5.
- `validate` re-validates every memory file; a bad one is exit 1 with issues at `library.<file name>.<field>`.
- `no-workspace` lets `search` run without a workspace (benchmarks only); `add`, `list`, `remove` and `validate` need
  one (exit 5 with the `rqh init` hint).

## How to get to it (user POV)

- `rqh library add <entry.yaml>`
- `rqh library list`
- `rqh library search --family PATH [--scenario-type T] [--industry I] [--size-band B] [--currency CUR]`
- `rqh library remove <entry_id>`
- `rqh library validate`

## Driving it with verify.py and a browser

Preconditions:

- A workspace made by hand as in [the index](./README.md#a-workspace-by-hand) (`rqh init` is enough; no run is needed),
  and an empty directory with no workspace. The fixture entry is `tests/library/fixtures/entry.yaml` (`mem-phish-loss`,
  `primary_loss.response`, USD, segment retail / mid_market). `verify.py run` does not touch these commands.

- **No workspace.** In the empty directory, `rqh library list` is exit 5, and
  `rqh library search --family primary_loss.response` is exit 0 with only `origin` `benchmark` hits.
- **Empty memory.** In the workspace, `rqh library list` is exit 0 with `data.entries` `[]`.
- **Add.** `rqh library add $REPO/tests/library/fixtures/entry.yaml`: exit 0, `data.result` `added`, and
  `.riskquant/library/mem-phish-loss.yaml` exists. Again: `data.result` `duplicate`. A copy whose `value:` flow map has `mode: 40000` replaced by `mode: 50000`: exit 1,
  rule `entry_id_conflict`. A path that does not exist: exit 5. A copy with an alias (`entry_id: &i mem-alias` plus a
  line `x: *i`): exit 1, rule `yaml`.
- **List.** `rqh library list` shows exactly `mem-phish-loss`.
- **Search.** `rqh library search --family primary_loss.response --currency EUR`: exit 0, the first hit is
  `mem-phish-loss` with `origin` `memory` and `currency_mismatch` true. With `--industry retail --currency USD` the first
  hit has `segment_match` 1 and `currency_mismatch` false. Without `--family`: exit 2.
- **Validate.** `rqh library validate` is exit 0. Edit `.riskquant/library/mem-phish-loss.yaml` so `min` is above
  `mode` (`min: 900000`): exit 1 with an issue path starting `library.mem-phish-loss`.
- **Remove.** `rqh library remove mem-phish-loss`: exit 0, `data.removed` `mem-phish-loss`, and the file is gone.
  Again: exit 5.

## Gotchas

- Memory is never written into the installed package; benchmarks are read-only and `remove` never touches them.
- `search` reads memory from `$RQH_WORKSPACE` or `./.riskquant` like every other command, so run it from the workspace
  directory or memory hits are silently absent.
- The `collect-data` skill hands the `benchmark-researcher` agent benchmark-origin hits only. That filter lives in the
  skill and agent instructions, not in `rqh library search`, which always returns both origins.
- An entry is stale when its period ended more than `stale_after_months` (default 18) before today, so the fixture's
  `stale` flag depends on the date you run it.
