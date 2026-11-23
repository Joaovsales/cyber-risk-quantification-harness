#!/usr/bin/env python3
"""Run the live eval suite and write `evals/records/<plugin version>.json`.

THIS SPENDS CLAUDE USAGE (about 15 agent runs per 5 cases, three trials each). Run it by hand,
once per release, after `pip install -e .` and with no TAVILY_API_KEY in the environment.
See evals/live/README.md. CI never calls it; the release workflow only checks its record.

    python evals/run_live.py [--max-cost-usd 25]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_record  # noqa: E402

REPO = check_record.EVALS.parent
THRESHOLD = check_record.THRESHOLD
# Each run's trace, copied out of its kept temp dir. evals/live/results is gitignored and left out
# of the suite hash, so keeping traces never makes a record stale.
TRACES = check_record.EVALS / "live" / "results" / "traces"


def plugin_version() -> str:
    text = (REPO / "src" / "rqharness" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "(.+)"$', text, re.MULTILINE).group(1)


def eval_command(raw: Path, max_cost_usd: str) -> list[str]:
    """The `claude plugin eval` call. `--scaffold` runs each hand-off case's own `scaffold.sh`,
    which writes that case's fixtures into the run's empty workspace."""
    return ["claude", "plugin", "eval", str(REPO), "--eval-dir", "evals/live", "--trust-plugin",
            "--scaffold", "--allow-tools", "Bash", "Write", "Edit", "--disallow-tools", "WebSearch", "WebFetch",
            "--ablation", "none", "--runs", "3", "--concurrency", "4", "--judge-model", "sonnet",
            "--threshold", str(THRESHOLD),
            "--max-cost-usd", max_cost_usd, "--no-publish", "--keep-temp", "--json", str(raw)]


def keep_traces(result: dict, dest: Path) -> int:
    """Copy each trial's trace to `dest/<case>-<trial>.jsonl`; return how many were copied.
    `--keep-temp` leaves each run's dir read-only, so it is opened first; a trace that is missing
    is skipped rather than failing a finished run. Traces from an earlier run are removed first."""
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    copied = 0
    for case in result.get("cases", []):
        for trial, run in enumerate((case.get("arms") or {}).get("with") or [], start=1):
            trace = Path(run.get("tracePath") or "")
            if not run.get("tracePath"):
                continue
            try:
                trace.parent.parent.chmod(0o700)
                shutil.copyfile(trace, dest / f"{case['name']}-{trial}.jsonl")
                copied += 1
            except OSError:
                continue
    return copied


def logged_in() -> bool:
    """Whether `claude` can make calls. A logged-out eval run does not stop: every case fails with
    "Not logged in" only after its time runs out, so the runner asks first."""
    try:
        status = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True)
        return json.loads(status.stdout).get("loggedIn") is True
    except (OSError, ValueError, AttributeError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-cost-usd", default="25")
    args = parser.parse_args(argv)
    if sys.platform == "win32":
        # A run that grants Bash needs an OS sandbox (bubblewrap on Linux, Seatbelt on macOS);
        # native Windows has none, so claude plugin eval refuses every case rather than score it.
        print("the live suite cannot run on native Windows: run it in the container, see evals/docker/README.md",
              file=sys.stderr)
        return 2
    if os.environ.get("TAVILY_API_KEY"):
        print("unset TAVILY_API_KEY: the live suite runs with search stubbed out", file=sys.stderr)
        return 2
    if not logged_in():
        print("claude is not logged in: in the container, set CLAUDE_CODE_OAUTH_TOKEN from `claude setup-token`"
              " (see evals/docker/README.md); elsewhere run `claude auth login`", file=sys.stderr)
        return 2
    version = plugin_version()
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "aggregate-result.json"
        code = subprocess.run(eval_command(raw, args.max_cost_usd), cwd=REPO).returncode
        if not raw.is_file():
            print(f"no result written (claude plugin eval exited {code})", file=sys.stderr)
            return code or 1
        result = json.loads(raw.read_text(encoding="utf-8"))
    print(f"kept {keep_traces(result, TRACES)} run traces in {TRACES}")
    record = {**result, "plugin_version": version, "threshold": THRESHOLD,
              "suite_sha256": check_record.suite_sha256(), "eval_exit_code": code}
    target = check_record.EVALS / check_record.RECORDS / f"{version}.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {target} (claude plugin eval exit {code}); check it with: python evals/check_record.py {version}")
    return code


if __name__ == "__main__":
    sys.exit(main())
