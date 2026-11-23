"""`rqh validate <target>`: check a run directory or one document against its schema."""

from __future__ import annotations

import argparse
from pathlib import Path

from rqharness import cli, library
from rqharness.outcomes import Issue, Rejected, Usage, issue
from rqharness.schemas import known_kinds, load_yaml, validate_document
from rqharness.validate import KIND_BY_FILENAME, validate_inputs, validate_run


def _validate_file(path: Path, kind: str | None) -> tuple[list[str], list[Issue]]:
    kind = kind or KIND_BY_FILENAME.get(path.name)
    if kind not in known_kinds():
        raise Usage([issue("argv", "usage", f"cannot tell the document kind of {path.name}; pass --kind "
                           f"(one of {', '.join(known_kinds())})")])
    data, issues = load_yaml(path, kind)
    if issues:
        return [kind], issues
    if kind != "inputs":
        return [kind], validate_document(kind, data, stem=kind)
    # the memory of the workspace a run would be resolved in, when it exists, so a lone inputs
    # file and `rqh validate <run>` agree
    return [kind], validate_inputs(data, entry_lookup=library.entry_lookup(cli.existing_workspace()))


def _handle(args: argparse.Namespace) -> cli.Outcome:
    target = Path(args.target)
    if target.is_file():
        documents, issues = _validate_file(target, args.kind)
    else:
        report = validate_run(cli.resolve_run(args.target))
        documents, issues = report.documents, report.issues
    if issues:
        raise Rejected(issues)
    return cli.ok({"target": args.target, "documents": documents}, text="ok")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("validate", help="validate a run directory or one document")
    parser.add_argument("target", help="a run directory or id, or a document file")
    parser.add_argument("--kind", help="document kind when the file name does not say")
    parser.set_defaults(handler=_handle)
