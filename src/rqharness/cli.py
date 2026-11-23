"""The `rqh` shell: command discovery, the JSON envelope and exit codes.

Every subcommand lives in its own module under ``rqharness.commands`` and is
found by discovery (spec D23). A command handler returns an :class:`Outcome` on
success and raises an :class:`rqharness.outcomes.DomainError` kind on failure;
:data:`EXIT_CODES` is the one place a kind becomes an exit code, and :func:`main`
the one handler. Either way this module renders the envelope skills parse
(``--json``) or plain text.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from rqharness import __version__, outcomes, workspace
from rqharness.outcomes import Issue, issue

ENVELOPE_SCHEMA_VERSION = "1"

EXIT_OK = 0
EXIT_REJECTED = 1  # validation or rejection; issues name every dotted field path
EXIT_USAGE = 2
EXIT_TRANSITION = 3  # illegal status transition
EXIT_NARRATIVE = 4  # narrative rejected
EXIT_MISSING = 5  # required artifact missing

# The only map from a failure kind to its exit code: the same kind exits the same way from every command.
EXIT_CODES: dict[type[outcomes.DomainError], int] = {
    outcomes.Rejected: EXIT_REJECTED,
    outcomes.Usage: EXIT_USAGE,
    outcomes.IllegalTransition: EXIT_TRANSITION,
    outcomes.NarrativeRejected: EXIT_NARRATIVE,
    outcomes.NotFound: EXIT_MISSING,
}

WORKSPACE_DIRNAME = ".riskquant"
WORKSPACE_ENV = "RQH_WORKSPACE"


@dataclass
class Outcome:
    """What a command handler returns; ``main`` renders it."""

    exit_code: int = EXIT_OK
    data: dict[str, Any] | None = None
    issues: list[Issue] = field(default_factory=list)
    text: str | None = None

    @property
    def ok(self) -> bool:
        return self.exit_code == EXIT_OK


def ok(data: dict[str, Any] | None = None, text: str | None = None) -> Outcome:
    return Outcome(EXIT_OK, data if data is not None else {}, [], text)


def _failed(error: outcomes.DomainError, text: str | None = None) -> Outcome:
    """The outcome of a raised failure: the exit code of the nearest listed kind in its MRO."""
    code = next(EXIT_CODES[kind] for kind in type(error).__mro__ if kind in EXIT_CODES)
    return Outcome(code, None, list(error.issues), text)


# --- workspace and run resolution (shared by every command) -----------------


def workspace_root(cwd: Path | None = None) -> Path:
    """The workspace directory: ``$RQH_WORKSPACE`` or ``./.riskquant``."""
    env = os.environ.get(WORKSPACE_ENV)
    if env:
        return Path(env)
    return (cwd or Path.cwd()) / WORKSPACE_DIRNAME


def existing_workspace() -> Path | None:
    """:func:`workspace_root` when it exists, else ``None``: for reads that also work without one."""
    root = workspace_root()
    return root if root.is_dir() else None


def require_workspace() -> Path:
    """The configured :func:`workspace_root`, which must be an existing directory.

    Raises :class:`~rqharness.outcomes.NotFound` with the ``rqh init`` hint otherwise.
    """
    return workspace.require_workspace(workspace_root())


def resolve_run(ref: str) -> workspace.Run:
    """The run a reference names: a run id in the workspace, or the path of a directory in its ``runs/``.

    Raises :class:`~rqharness.outcomes.NotFound` when the workspace or the run is missing, and
    :class:`~rqharness.outcomes.Usage` (as for any argument naming a file outside where it must be) when the
    path is a directory outside ``<workspace>/runs/``: a copied run is never read with the org
    profile and library of whatever folder sits above it.
    """
    root = require_workspace()
    missing = outcomes.NotFound([issue("run", "missing", f"no run named {ref!r} in {root}")])
    as_path = Path(ref)
    by_path = as_path.is_dir() and (os.sep in ref or "/" in ref or ref.startswith("."))
    try:
        run = workspace.Run(root, as_path) if by_path else workspace.Run.named(root, ref)
    except ValueError as exc:
        if not by_path:  # an id that cannot be a run name names no run
            raise missing from None
        raise outcomes.Usage([issue(
            "run", "outside_workspace",
            f"{exc}; move it there, or set {WORKSPACE_ENV} to the workspace that holds it")]) from None
    if not run.dir.is_dir():
        raise missing
    return run


# --- discovery ----------------------------------------------------------------

Register = Callable[[argparse._SubParsersAction], None]


def discover_commands() -> dict[str, Register]:
    """Map each module name under ``rqharness.commands`` to its ``register``."""
    import rqharness.commands as package

    found: dict[str, Register] = {}
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda m: m.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            found[info.name] = register
    return found


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D401 - argparse hook
        raise _UsageError(f"{self.prog}: {message}")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="rqh", description="risk-quantification-harness command line")
    parser.add_argument("--version", action="version", version=f"rqh {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)
    for register in discover_commands().values():
        register(subparsers)
    return parser


# --- rendering ------------------------------------------------------------------


def envelope(outcome: Outcome) -> dict[str, Any]:
    return {
        "schema_version": ENVELOPE_SCHEMA_VERSION,
        "ok": outcome.ok,
        "data": outcome.data if outcome.ok else None,
        "issues": [] if outcome.ok else list(outcome.issues),
    }


def _render(outcome: Outcome, as_json: bool) -> None:
    if as_json:
        sys.stdout.write(json.dumps(envelope(outcome), indent=2, ensure_ascii=False) + "\n")
        return
    if outcome.text is not None:
        stream = sys.stdout if outcome.ok else sys.stderr
        stream.write(outcome.text.rstrip("\n") + "\n")
    elif not outcome.ok:
        for i in outcome.issues:
            sys.stderr.write(f"{i['path']}: {i['message']} [{i['rule']}]\n")
    elif outcome.data:
        sys.stdout.write(json.dumps(outcome.data, indent=2, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run one command; returns its exit code. ``--json`` may appear anywhere."""
    args_in = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args_in
    args_in = [a for a in args_in if a != "--json"]
    parser = build_parser()
    try:
        args = parser.parse_args(args_in)
    except _UsageError as exc:
        outcome = _failed(outcomes.Usage([issue("argv", "usage", str(exc))]))
    else:
        outcome = _run(parser, args, as_json)
    _render(outcome, as_json)
    return outcome.exit_code


def _run(parser: argparse.ArgumentParser, args: argparse.Namespace, as_json: bool) -> Outcome:
    handler = getattr(args, "handler", None)
    if handler is None:
        if not as_json:
            parser.print_help(sys.stderr)
        return _failed(outcomes.Usage([issue("argv", "usage", "no command given")]), text="")
    try:
        return handler(args)
    except outcomes.DomainError as error:
        return _failed(error)


def entry() -> None:
    """Console-script entry point."""
    sys.exit(main())
