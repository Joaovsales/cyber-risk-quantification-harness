# Contributing

Thanks for helping. Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) first; report security
problems as described in [SECURITY.md](SECURITY.md), not in public issues.

## Development setup

```bash
python -m pip install -e ".[dev]"
rqh --version
python -m pytest
```

Python 3.11 or newer. CI runs the tests on Linux, macOS and Windows.

## How we work

- **Test first.** Write the failing test, see it fail, then write the smallest change that passes it.
- **Small slices.** One change, one reason. Every changed line should trace to the task; no drive-by refactors.
- **Match the surrounding style.** Type hints, `from __future__ import annotations`, small modules.
- **Wording.** Say "estimate". The method is "FAIR-aligned". No name contains "FAIR".
- **No network** from the package, except the optional `rqh search`. Tests never touch the network.
- **Commits** follow conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).

## Adding a benchmark entry

Entries are YAML files in `src/rqharness/data/benchmarks/<scenario_type>/`. Use an existing entry as
the model, then:

1. Open the publisher's own page and read the figure there; do not copy from a secondary article.
2. Fill `source` (canonical `https://` `url`, `title`, `retrieved_at`, `applicability_note`),
   `value` (`min`, `mode`, `max`, `unit`), `period`, `segment`, `scenario_tags` and a `note` that says
   how min, mode and max map from the source.
3. Run `rqh library validate` and `python -m pytest tests/benchmarks -q`.
4. Open a pull request with the **benchmark entry** template
   (`.github/PULL_REQUEST_TEMPLATE/benchmark_entry.md`: add `?template=benchmark_entry.md` to the
   new-pull-request URL). Every shipped URL is checked weekly by the `linkcheck` workflow.

## Live evals

`python evals/run_live.py` runs the real skills through Claude Code. It needs a Claude login and
**spends Claude usage** (roughly 12 to 30 USD for the whole suite; cap it with `--max-cost-usd`).
CI does not run it. Details are in [`evals/live/README.md`](evals/live/README.md).

## Releasing

1. Bump `__version__` in `src/rqharness/__init__.py` and the version in `.claude-plugin/`.
2. Run `python evals/run_live.py`; it writes `evals/records/<version>.json`. Commit that record.
3. Tag the commit `v<version>` and push the tag. The release workflow refuses a tag that does not
   match the package version or has no passing record, then publishes to PyPI and GitHub.

## Sample report

The sample report on GitHub Pages is built from `examples/credential-phishing-bec/` by the `pages`
workflow on every push to `main`. The same workflow publishes `src/rqharness/schemas/*.v1.json` under
`schemas/`, where each schema's `$id` points. Do not commit a rendered `report.html`.
