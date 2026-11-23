"""``finalize``: the one non-idempotent command and the source of every report.

A version is built in ``v<N>.tmp/`` and renamed to ``v<N>/``, so a reader sees only
complete versions; the run lock (:func:`runstate.locked`) serialises writers and is always
released, and :func:`runstate.publish` makes the rename and the status write one recoverable step.
A refused finalize raises a :mod:`rqharness.outcomes` kind and writes nothing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rqharness import engine, manifest, model, orgprofile, runstate, sensitivity, summary, workspace
from rqharness.outcomes import Issue, Rejected, issue
from rqharness.validate import ReadyRun, validate_run

_VERSION_DIR = re.compile(r"^v[1-9][0-9]*$")
_TMP_DIR = re.compile(r"^v[0-9]+\.tmp$")


@dataclass(frozen=True)
class Finalized:
    version: int
    path: Path
    n: int
    seed: int


def latest_version(run_dir: Path) -> int | None:
    """The highest complete ``v<N>/``, read from the directory every time."""
    if not run_dir.is_dir():
        return None
    found = [int(p.name[1:]) for p in run_dir.iterdir() if p.is_dir() and _VERSION_DIR.match(p.name)]
    return max(found, default=None)


def latest_draws(run_dir: Path) -> tuple[int, int] | None:
    """The ``(n, seed)`` the latest version's manifest records, or None when the run has no version.

    Raises :class:`Rejected` when that manifest cannot be read.
    """
    latest = latest_version(run_dir)
    if latest is None:
        return None
    path = run_dir / f"v{latest}" / "run_manifest.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        return int(record["n"]), int(record["seed"])
    except (OSError, ValueError, TypeError, KeyError):
        raise Rejected([issue(f"v{latest}.run_manifest", "unreadable",
                              f"{path} cannot be read for its n and seed; pass --n and --seed")]) from None


def _is_link(path: Path) -> bool:
    """Whether ``path`` itself is a symlink or a Windows junction, so a delete through it leaves the run."""
    real_parent = os.path.realpath(path.parent)
    return os.path.normcase(os.path.realpath(path)) != os.path.normcase(os.path.join(real_parent, path.name))


def _remove_leftovers(run_dir: Path) -> None:
    """Delete crash remnants ``v<N>.tmp/``, never through a link.

    A remnant that is itself a link is unlinked, not emptied. In a run directory that is a
    link, a remnant is refused with :class:`Rejected` rather than deleted through it.
    """
    leftovers = [p for p in run_dir.iterdir() if _TMP_DIR.match(p.name) and (p.is_dir() or _is_link(p))]
    if leftovers and _is_link(run_dir):
        names = ", ".join(sorted(p.name for p in leftovers))
        raise Rejected([issue("run.dir", "linked_run",
                              f"{run_dir} links to {os.path.realpath(run_dir)}; finalize does not delete "
                              f"{names} through it: remove them by hand and finalize again")])
    for leftover in leftovers:
        if _is_link(leftover):
            try:
                os.unlink(leftover)
            except (IsADirectoryError, PermissionError):  # a Windows directory link or junction
                os.rmdir(leftover)
        else:
            shutil.rmtree(leftover)


def _theme_snapshot(workspace_dir: Path) -> dict:
    """Everything the report needs from the org profile; rendering reads only ``v<N>/``."""
    return orgprofile.to_snapshot(orgprofile.load_profile(workspace_dir))


def _memory_budget_issues(inputs_model: model.ModelInputs, n: int, n_source: str) -> list[Issue]:
    """One issue when n draws of these inputs would lay out more than engine.MAX_EVENT_CELLS."""
    budget = engine.event_budget(inputs_model)
    if budget.fits(n):
        return []
    fix = (f"rerun with --n {budget.max_n:,} or lower" if budget.max_n >= 1 else
           "even n = 1 is over it; lower the frequency estimates or secondary_loss.slef")
    return [issue("inputs.parameters", "memory_budget",
                  f"n = {n:,} draws (from {n_source}) x about {budget.cells_per_iteration:,.1f} expected "
                  f"events per draw (baseline and every variant, secondary events included) is about "
                  f"{budget.cells(n):,.0f} event cells, over the engine's budget of "
                  f"{engine.MAX_EVENT_CELLS:,}; {fix}")]


def _write_version(run: workspace.Run, ready: ReadyRun, tmp: Path, version: int, state: dict,
                   n: int, seed: int) -> Finalized:
    """Snapshot and simulate the documents ``ready`` carries, never a fresh read of the run."""
    run_dir = run.dir
    inputs, inputs_model = ready.inputs, ready.inputs_model
    (tmp / "inputs.snapshot.yaml").write_bytes(ready.inputs_bytes)
    (tmp / "scenario.snapshot.yaml").write_bytes(ready.scenario_bytes)
    workspace.write_yaml(tmp / "theme.snapshot.yaml", _theme_snapshot(run.workspace))

    result = engine.simulate(inputs_model, n=n, seed=seed)
    doc = summary.build_summary(inputs, inputs_model, result, sensitivity.contributions(result))
    (tmp / "run_summary.json").write_text(summary.dumps(doc), encoding="utf-8", newline="\n")

    arrays = {f"{vid}.{name}": getattr(draws, name)
              for vid, draws in result.variants.items() for name in ("annual_loss", "lef", "event_count")}
    np.savez(tmp / "draws.npz", **arrays)

    record = manifest.build_manifest(
        scenario_id=inputs["scenario_id"], version=version, n=n, seed=seed,
        inputs_sha256=manifest.sha256_file(tmp / "inputs.snapshot.yaml"), generated_at=workspace.utc_now(),
        route=state["route"])
    (tmp / "run_manifest.json").write_text(manifest.dumps(record), encoding="utf-8", newline="\n")
    return Finalized(version, run_dir / f"v{version}", n, seed)


def finalize(run: workspace.Run, *, n: int | None = None, seed: int | None = None) -> Finalized:
    """Write the next version; raises ``IllegalTransition`` from ``scoping`` and ``Rejected`` when
    the lock is held, the run has no inputs.yaml, or the run (or its org profile) does not validate."""
    run_dir = run.dir
    with runstate.locked(run_dir):  # the status is checked and written under the lock every run.yaml writer takes
        runstate.check(run_dir, "finalize")
        ready = validate_run(run).ready()  # the one read: validated, snapshotted and simulated
        state = runstate.read_state(run_dir)
        n_source = "--n" if n is not None else "run.yaml, set by rqh run confirm"
        n = n if n is not None else state["n"]
        seed = seed if seed is not None else state["seed"]
        over_budget = _memory_budget_issues(ready.inputs_model, n, n_source)
        if over_budget:
            raise Rejected(over_budget)
        _remove_leftovers(run_dir)
        version = (latest_version(run_dir) or 0) + 1
        tmp = run_dir / f"v{version}.tmp"
        tmp.mkdir()
        try:
            finalized = _write_version(run, ready, tmp, version, state, n, seed)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)  # the directory this call just created, nothing older
            raise
        runstate.publish(run_dir, tmp, finalized.path.name, "finalize")
        return finalized
