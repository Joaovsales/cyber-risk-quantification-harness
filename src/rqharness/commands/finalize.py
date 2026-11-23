"""`rqh finalize <run>`: simulate and write the next ``v<N>/`` version."""

from __future__ import annotations

import argparse

from rqharness import cli, finalize
from rqharness.commands._draws import require_in_range


def _handle(args: argparse.Namespace) -> cli.Outcome:
    require_in_range(args.n, args.seed)
    result = finalize.finalize(cli.resolve_run(args.run), n=args.n, seed=args.seed)
    return cli.ok(
        {"version": result.version, "path": str(result.path), "n": result.n, "seed": result.seed},
        text=f"finalized v{result.version} ({result.n} draws, seed {result.seed})")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("finalize", help="simulate and write the next version of a run")
    parser.add_argument("run", help="a run directory or id")
    parser.add_argument("--n", type=int, help="draws per variant (default: the run's n)")
    parser.add_argument("--seed", type=int, help="seed for this version (default: the run's seed)")
    parser.set_defaults(handler=_handle)
