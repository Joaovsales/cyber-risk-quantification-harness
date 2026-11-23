"""`rqh report <run>`: render a finalized version into one self-contained HTML file."""

from __future__ import annotations

import argparse
from pathlib import Path

from rqharness import cli
from rqharness.report import render


def _handle(args: argparse.Namespace) -> cli.Outcome:
    result = render.render_report(cli.resolve_run(args.run).dir, args.version,
                                  narrative=Path(args.narrative) if args.narrative else None,
                                  omit_narrative=args.omit_narrative)
    return cli.ok({"path": str(result.path), "version": result.version, "narrative_omitted": result.narrative_omitted},
                  text=f"wrote {result.path}")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("report", help="render a finalized version as a single HTML report")
    parser.add_argument("run", help="a run directory or id")
    parser.add_argument("--version", type=int, help="the version to render (default: the latest)")
    parser.add_argument("--narrative", metavar="FILE", help="a narrative to validate, store and show as the takeaway")
    parser.add_argument("--omit-narrative", action="store_true", help="render without any stored narrative")
    parser.set_defaults(handler=_handle)
