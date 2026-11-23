"""`rqh status <run>`: the run's state and the skill to run next. Writes nothing."""

from __future__ import annotations

import argparse

from rqharness import chain, cli, requests, runstate, schemas


def _read(path, stem: str) -> object | None:
    """A file skills edit by hand: malformed YAML reads as absent (next_step routes it to collect-data)."""
    return schemas.load_yaml(path, stem)[0] if path.is_file() else None


def _handle(args: argparse.Namespace) -> cli.Outcome:
    run = cli.resolve_run(args.run)
    run_dir = run.dir
    step = chain.next_step(run)
    state = runstate.read_state(run_dir) or {}
    scenario = _read(run_dir / "scenario.yaml", "scenario")
    inputs = _read(run_dir / "inputs.yaml", "inputs")
    data = {
        "run": run_dir.name,
        "scenario_id": state.get("scenario_id") or (scenario or {}).get("scenario_id"),
        "status": step.status,
        "route": state.get("route"),
        "next_skill": step.skill,
        "waiting_on": step.waiting_on,
        "latest_version": step.latest_version,
        "reason": step.reason,
        "open_requests": requests.open_requests(run_dir),
        "pending_candidates": requests.pending_candidates(run_dir),
        "fallback_parameters": requests.fallback_parameters(inputs) if isinstance(inputs, dict) else [],
        "n": state.get("n"),
        "seed": state.get("seed"),
    }
    return cli.ok(data, text=f"{data['status']}: next {data['next_skill'] or 'none'} ({step.reason})")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("status", help="show a run's state and the skill to run next")
    parser.add_argument("run", help="a run directory or id")
    parser.set_defaults(handler=_handle)
