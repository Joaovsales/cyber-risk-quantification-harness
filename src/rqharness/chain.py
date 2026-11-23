"""`next_step`: which skill the router loop runs next. A pure read of the run directory and its workspace."""

from __future__ import annotations

from dataclasses import dataclass

from rqharness import finalize, requests, runstate, validate, workspace
from rqharness.outcomes import NotFound, issue
from rqharness.workspace import Run


@dataclass(frozen=True)
class NextStep:
    skill: str | None
    status: str
    waiting_on: list[str]
    latest_version: int | None
    reason: str


def next_step(run: Run) -> NextStep:
    workspace.require_workspace(run.workspace)
    run_dir = run.dir
    if not run_dir.is_dir():
        raise NotFound([issue("run", "missing", f"no run directory at {run_dir}")])
    status = runstate.status_of(run_dir)
    latest = finalize.latest_version(run_dir)

    def step(skill: str | None, reason: str, waiting_on: list[str] | None = None) -> NextStep:
        return NextStep(skill, status, waiting_on or [], latest, reason)

    if status == "scoping" or not (run_dir / "scenario.yaml").is_file():
        return step("scope-scenario", "The scenario is not scoped and confirmed yet.")
    if status == "awaiting_data":
        waiting = [r["id"] for r in requests.open_requests(run_dir)]
        if not waiting:  # an interrupted auto-resume or a hand edit; nothing will ever close it
            return step(None, "The run waits for answers but has no open request; run `rqh run resume`.")
        return step(None, "The run waits for answers to its open requests.", waiting)
    if status == "collecting":
        if validate.validate_run(run).readiness_issues:  # the rule rqh finalize applies
            return step("collect-data", "The inputs are missing or do not validate.")
        if requests.pending_candidates(run_dir):
            return step("collect-data", "A candidate value waits for confirmation.")
        return step("simulate", "The inputs are valid and nothing is pending.")
    if latest is None:  # a hand edit or a deleted version: there is nothing to report
        return step(None, "The run is finalized but has no version; run `rqh run reopen`, then finalize again.")
    if not (run_dir / f"v{latest}" / "report.html").is_file():
        return step("report", f"Version {latest} is finalized and has no report yet.")
    return step(None, "The run is done until `rqh run reopen`.")
