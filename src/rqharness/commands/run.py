"""`rqh run`: confirm, route, pause, resume, reopen and rescope a run."""

from __future__ import annotations

import argparse
import secrets
from typing import Callable

from rqharness import cli, finalize, runstate
from rqharness.commands._draws import require_in_range
from rqharness.model import ESTIMATE_PATHS
from rqharness.outcomes import IllegalTransition, Rejected, issue
from rqharness.validate import validate_run

ROUTES = ("yolo", "accuracy")
DEFAULT_N = 50_000


def _confirm(args: argparse.Namespace) -> cli.Outcome:
    require_in_range(args.n, args.seed)
    run = cli.resolve_run(args.run)
    run_dir = run.dir
    state = runstate.read_state(run_dir)
    if state and state["status"] == "collecting" and state["route"] == args.route:
        _refuse_other_draws(state, args.n, args.seed)
        return cli.ok(state, text="already confirmed")
    validated = validate_run(run)
    scenario = validated.scenario  # the document validated, never a second read of the file
    if scenario is None:
        raise Rejected([i for i in validated.issues if i["path"].startswith("scenario")])
    # A run that lost run.yaml but kept its versions resumes their n and seed, never a fresh draw;
    # with both given, the manifest is not read, so --n and --seed get past one that cannot be.
    asked_both = args.n is not None and args.seed is not None
    recorded = finalize.latest_draws(run_dir) if state is None and not asked_both else None
    state = state or ({"n": recorded[0], "seed": recorded[1]} if recorded else {})
    saved = runstate.apply(
        run_dir, "confirm",
        scenario_id=scenario["scenario_id"],
        route=args.route,
        route_overrides=state.get("route_overrides", {}),
        n=args.n if args.n is not None else state.get("n", DEFAULT_N),
        seed=args.seed if args.seed is not None else state.get("seed", secrets.randbits(63)),
    )
    return cli.ok(saved, text=f"confirmed {saved['scenario_id']} on the {saved['route']} route")


def _refuse_other_draws(state: dict, n: int | None, seed: int | None) -> None:
    """A repeated confirm keeps the stored n and seed; asking for others is exit 3, never silently ignored."""
    asked = {k: v for k, v in (("n", n), ("seed", seed)) if v is not None and v != state[k]}
    if asked:
        raise IllegalTransition([issue(
            "run.status", "illegal_transition",
            f"the run is already confirmed with n = {state['n']} and seed {state['seed']}; to change "
            f"{' and '.join(asked)}, run `rqh run rescope` and confirm again, or pass them to `rqh finalize` "
            f"for one version")])


def _route(args: argparse.Namespace) -> cli.Outcome:
    run_dir = cli.resolve_run(args.run).dir
    if args.path not in ESTIMATE_PATHS:
        raise Rejected([issue(
            "run.route_overrides", "unknown_path", f"{args.path!r} is not an estimate path")])
    overrides = (runstate.read_state(run_dir) or {}).get("route_overrides", {})
    saved = runstate.update(run_dir, allowed=("collecting", "awaiting_data"), action="route an estimate",
                            route_overrides={**overrides, args.path: args.route})
    return cli.ok(saved, text=f"{args.path} -> {args.route}")


def _trigger_handler(trigger: str) -> Callable[[argparse.Namespace], cli.Outcome]:
    def handle(args: argparse.Namespace) -> cli.Outcome:
        saved = runstate.apply(cli.resolve_run(args.run).dir, trigger)
        return cli.ok(saved, text=f"run is {saved['status']}")
    return handle


def register(subparsers: argparse._SubParsersAction) -> None:
    run = subparsers.add_parser("run", help="confirm, route, pause, resume, reopen or rescope a run")
    actions = run.add_subparsers(dest="action", metavar="<action>", parser_class=type(run))

    confirm = actions.add_parser("confirm", help="confirm the scope and the route")
    confirm.add_argument("run")
    confirm.add_argument("--route", required=True, choices=ROUTES)
    confirm.add_argument("--n", type=int)
    confirm.add_argument("--seed", type=int)
    confirm.set_defaults(handler=_confirm)

    route = actions.add_parser("route", help="override the route of one estimate")
    route.add_argument("run")
    route.add_argument("path", help="estimate path, e.g. primary_loss.response")
    route.add_argument("route", choices=ROUTES)
    route.set_defaults(handler=_route)

    for name in ("pause", "resume", "reopen", "rescope"):
        sub = actions.add_parser(name, help=f"{name} a run")
        sub.add_argument("run")
        sub.set_defaults(handler=_trigger_handler(name))
