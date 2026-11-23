"""`rqh init`: create the private `.riskquant/` workspace."""

from __future__ import annotations

import argparse

from rqharness import cli, workspace


def _handle(args: argparse.Namespace) -> cli.Outcome:
    root = cli.workspace_root()
    created = workspace.init_workspace(root)
    gitignore = "present" if (root / ".gitignore").is_file() else "absent"
    return cli.ok({"workspace": str(root), "created": created, "gitignore": gitignore},
                  text=f"workspace {'created' if created else 'ready'} at {root}")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("init", help="create the private .riskquant workspace")
    parser.set_defaults(handler=_handle)
