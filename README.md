# risk-quantification-harness

Give it one sentence about a cyber risk and get one self-contained HTML report with a Monte Carlo
estimate of annual loss. Claude Code skills hold the conversation and propose inputs; the `rqh`
command validates, simulates and writes the report, so every number comes from code and none is
written by the model.

**[See a sample report](https://joaovsales.github.io/cyber-risk-quantification-harness/)** (a
fictional organisation, built from [`examples/credential-phishing-bec/`](examples/credential-phishing-bec/)).

## Install

The command line:

```bash
pipx install risk-quantification-harness
# or
uv tool install risk-quantification-harness
rqh --version
```

The Claude Code plugin (this repository is its own marketplace):

```text
/plugin marketplace add Joaovsales/cyber-risk-quantification-harness
/plugin install risk-quantification-harness@risk-quantification-harness
```

## Quickstart

Describe a risk to Claude Code, for example "what would a ransomware attack cost us a year?". The
`risk-quant` skill is the front door: it asks `rqh status` which skill comes next and runs the chain
(scope the scenario, collect data, simulate, report).

Two routes:

- **YOLO** asks you one confirmation question, fills every input from shipped benchmarks and clearly
  labelled assumptions, and writes the report with a banner saying so. Fastest.
- **Accuracy** drafts requests for data (to the people who hold it) and waits for the answers before
  it simulates. It never sends anything itself: you send the drafts.

Without Claude, drive the same steps by hand with the sample run:

```bash
rqh init
rqh validate credential-phishing-bec
rqh run confirm credential-phishing-bec --route yolo --n 50000 --seed 20261109
rqh finalize credential-phishing-bec
rqh report credential-phishing-bec
```

See [`examples/credential-phishing-bec/`](examples/credential-phishing-bec/) for the files to put in
the run folder first.

## Commands

```text
usage: rqh [-h] [--version] <command> ...

positional arguments:
  <command>
    candidates  add, confirm, reject or list candidate values
    finalize    simulate and write the next version of a run
    init        create the private .riskquant workspace
    library     search and maintain the memory library
    report      render a finalized version as a single HTML report
    requests    add, update or list requests for data
    run         confirm, route, pause, resume, reopen or rescope a run
    search      optional Tavily web search (needs TAVILY_API_KEY)
    status      show a run's state and the skill to run next
    validate    validate a run directory or one document
```

Each command prints a JSON envelope (`schema_version`, `ok`, `data`, `issues`) with `--json`, and
sets an exit code: 0 ok, 1 rejected, 2 usage, 3 illegal transition, 4 narrative rejected, 5 missing.

## Your workspace and privacy

Everything lives in `.riskquant/` in the folder where you run `rqh init` (or in `$RQH_WORKSPACE`):
runs, versions, requests, the org profile and your memory library. `rqh init` writes a `.gitignore`
of `*` inside it, so it is never committed. The package makes no network calls except the optional
`rqh search`, which needs `TAVILY_API_KEY`.

## The report

One HTML file with no external scripts, styles, fonts or images. Its Content-Security-Policy lets only
the inlined report script run, matched by its SHA-256 hash, and sets `base-uri` and `form-action` to
`'none'`; styles stay inline.
Sections, in order: the takeaway (with the YOLO banner when that route was used, and the data-quality
grade), summary cards, the loss exceedance curve, the distribution, the drivers, the variants
comparison, the scenario, the provenance table, a collapsed technical appendix, and what to collect
to improve the degree of accuracy.

## Method

- **FAIR-aligned.** Loss event frequency and loss magnitude, with four frequency models, optional
  vulnerability and secondary loss, and six primary loss forms.
- **Estimates.** Each input is a minimum, most likely and maximum value, drawn from a Beta-PERT
  distribution with shape parameter gamma = 4, with its source and tier (`internal_data`,
  `sme_estimate`, `benchmark`, `agent_assumption`).
- **Monte Carlo with common random numbers.** Variants compared against the baseline reuse the same
  random draws, so differences come from the change, not from noise. A fixed seed reproduces a run.
- **Data-quality grade.** A sensitivity-weighted tier score mapped to A, B, C or D: inputs that
  move the answer most count most.

## Evals and release gate

Per-commit tests replay the CLI deterministically (`python -m pytest`). The skills are checked by
live evals that run the real plugin (`python evals/run_live.py`); they need a Claude login and spend
usage. A release tag is refused unless `evals/records/` holds a passing record for that version. See
[`evals/live/README.md`](evals/live/README.md) and [CONTRIBUTING.md](CONTRIBUTING.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and
[SECURITY.md](SECURITY.md).

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
