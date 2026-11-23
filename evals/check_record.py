#!/usr/bin/env python3
"""Exit 0 only when `evals/records/<version>.json` is a passing, current live-eval record.

A record is the `claude plugin eval` aggregate result plus `plugin_version` and `suite_sha256`
(the hash of every file under `evals/live/`, see `suite_sha256` below). It passes when:

  * the file exists and is JSON,
  * its `plugin_version` equals the version asked for,
  * every case met THRESHOLD, two of three trials (spec D29), against each case's
    pass rate), and at least one case ran,
  * it holds a result for every case directory under `evals/live/` (a record that skips the
    per-skill cases fails),
  * its `suite_sha256` equals the hash as it is now, so a record made before a case, a grader,
    a skill, the agent, a manifest or the package changed is stale and fails,
  * `claude plugin eval` exited 0 when the record was made.

`suite_sha256` covers the cases under `evals/live/` and the trees in `TESTED_TREES`. Make the
record from a clean checkout: untracked files under those trees count too.

Standard library only: the release workflow runs it before anything is installed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

EVALS = Path(__file__).resolve().parent
LIVE = "live"
RECORDS = "records"
# What a live run exercises besides the cases: a change to any of these makes a record stale.
THRESHOLD = 0.66  # two of three trials must pass (spec D29); a record can raise the bar, never lower it
TESTED_TREES = ("skills", "agents", ".claude-plugin", "src/rqharness")


def suite_sha256(evals_dir: Path = EVALS) -> str:
    """Hash the cases under `live/` and the tested trees (repo-relative path and bytes, sorted)."""
    repo = evals_dir.parent
    live = evals_dir / LIVE
    files = [p for p in live.rglob("*") if p.is_file() and not _is_result(p, live)]
    for tree in TESTED_TREES:
        root = repo / tree
        if root.is_dir():
            files += [p for p in root.rglob("*") if p.is_file() and not _is_cache(p)]
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda p: p.relative_to(repo).as_posix()):
        digest.update(path.relative_to(repo).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n") + b"\0")
    return digest.hexdigest()


def _is_cache(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix == ".pyc"


def _is_result(path: Path, live: Path) -> bool:
    rel = path.relative_to(live)
    return rel.name == "aggregate-result.json" or rel.parts[0] in ("results", "reports")


def suite_case_names(evals_dir: Path = EVALS) -> set[str]:
    """The `name` of every case under `live/`: a directory holding a `prompt.md`."""
    names: set[str] = set()
    for prompt in (evals_dir / LIVE).rglob("prompt.md"):
        found = re.search(r"^name:\s*(\S+)\s*$", prompt.read_text(encoding="utf-8"), re.MULTILINE)
        names.add(found.group(1) if found else prompt.parent.name)
    return names


def _case_score(case: dict) -> float | None:
    """The with-plugin arm's pass rate for one case: the share of its trials that passed.

    `claude plugin eval` reports it as `aggregates.passRate`. Its `aggregates.score` is the mean
    share of graders passed (what `--threshold` compares), so a case whose every trial fails one
    grader in three still scores 0.67 there: it is never read here. Without a pass rate, count the
    trials.
    """
    rate = (case.get("aggregates") or {}).get("passRate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        return float(rate)
    trials = (case.get("arms") or {}).get("with") or []
    if not trials:
        return None
    # a trial that was never graded (no `passed`, no graders) failed: it proves nothing
    passed = [bool(t["passed"]) if "passed" in t else bool(t.get("graders")) and all(g.get("passed") for g in t["graders"])
              for t in trials]
    return sum(passed) / len(passed)


def check(version: str, evals_dir: Path = EVALS) -> list[str]:
    """Why the record for `version` does not pass; an empty list means it passes."""
    path = evals_dir / RECORDS / f"{version}.json"
    if not path.is_file():
        return [f"no live-eval record at {path}"]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        return [f"{path.name} is not valid JSON: {error}"]
    problems: list[str] = []
    if record.get("plugin_version") != version:
        problems.append(f"record is for version {record.get('plugin_version')!r}, not {version!r}")
    if record.get("suite_sha256") != suite_sha256(evals_dir):
        problems.append("the record is stale: the cases, skills, agent, manifests or package changed since it was made")
    if record.get("eval_exit_code", 0) != 0:
        problems.append(f"claude plugin eval exited {record['eval_exit_code']} when the record was made")
    cases = record.get("cases") or []
    if not cases:
        problems.append("the record has no cases")
    ran = {case.get("name", case.get("id")) for case in cases}
    for name in sorted(suite_case_names(evals_dir) - ran):
        problems.append(f"the record has no result for case {name}")
    threshold = THRESHOLD
    claimed = record.get("threshold", THRESHOLD)
    if isinstance(claimed, (int, float)) and not isinstance(claimed, bool):
        threshold = max(THRESHOLD, float(claimed))  # a record may raise the bar, never lower it
    else:
        problems.append(f"the record's threshold {claimed!r} is not a number")
    for case in cases:
        score = _case_score(case)
        if score is None or score < threshold:
            shown = score if score is None else round(score, 3)
            problems.append(f"case {case.get('name', case.get('id', '?'))} scored {shown}, below {threshold}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_record.py <version>", file=sys.stderr)
        return 2
    problems = check(argv[1])
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    if not problems:
        print(f"live-eval record for {argv[1]} passes")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
