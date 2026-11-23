"""`rqh candidates`: add, confirm, reject and list candidate values."""

from __future__ import annotations

import argparse
from pathlib import Path

from rqharness import cli, requests
from rqharness.commands.requests import VALUE_KEYS, add_value_arguments, flags_given, outcome, run_mapping, value_of
from rqharness.outcomes import Usage, issue

# The fields of a candidate: each candidate-file key, with the flag that supplies it when there is no candidate file.
_FIELDS = {**{key: f"--{key}" for key in VALUE_KEYS}, "evidence": "--evidence", "origin": "--origin", "link": "--link"}
_OPTIONAL = ("link",)


def _candidate_fields(run_dir: Path, args: argparse.Namespace) -> dict:
    """The value, evidence kind, origin and link: from --candidate-file, or from the per-field flags.

    Skills write connector-derived text (a link above all) to the file so it never passes through a shell.
    """
    required = tuple(key for key in _FIELDS if key not in _OPTIONAL)
    if args.candidate_file:
        if given := flags_given(args, tuple(_FIELDS.values())):
            raise Usage([issue("argv", "usage", "--candidate-file holds the value, evidence, origin and link; "
                                                f"leave out {', '.join(given)}")])
        return run_mapping(run_dir, args.candidate_file, "candidate-file", tuple(_FIELDS), required)
    fields = {key: getattr(args, key) for key in _FIELDS}
    if missing := [_FIELDS[key] for key in required if fields[key] is None]:
        raise Usage([issue("argv", "usage", f"candidates add needs --candidate-file, or {', '.join(missing)}")])
    return fields


def _add(args: argparse.Namespace) -> cli.Outcome:
    run_dir = cli.resolve_run(args.run).dir
    fields = _candidate_fields(run_dir, args)
    result = requests.add_candidate(
        run_dir, parameter_path=args.parameter, value=value_of(fields),
        evidence_kind=fields["evidence"], origin=fields["origin"], link=fields.get("link"))
    return outcome(result, "candidate", text=f"added {result.item['id']}")


def _confirm(args: argparse.Namespace) -> cli.Outcome:
    result = requests.confirm_candidate(cli.resolve_run(args.run), args.id)
    return outcome(result, "candidate", text=f"{args.id} confirmed")


def _reject(args: argparse.Namespace) -> cli.Outcome:
    result = requests.reject_candidate(cli.resolve_run(args.run).dir, args.id)
    return outcome(result, "candidate", text=f"{args.id} rejected")


def _list(args: argparse.Namespace) -> cli.Outcome:
    items = requests.load(cli.resolve_run(args.run).dir)["candidates"]
    return cli.ok({"candidates": items}, text="\n".join(f"{c['id']} {c['status']} {c['parameter_path']}" for c in items))


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("candidates", help="add, confirm, reject or list candidate values")
    actions = parser.add_subparsers(dest="action", metavar="<action>", parser_class=type(parser))

    add = actions.add_parser("add", help="record a found figure as a candidate")
    add.add_argument("run")
    add.add_argument("--parameter", required=True)
    add.add_argument("--candidate-file", help="a file inside the run directory holding min, mode, max, unit, "
                                              "evidence, origin and link (optional), read as JSON when it ends in "
                                              ".json and as YAML otherwise; replaces the per-field flags")
    add_value_arguments(add, required=False)
    add.add_argument("--origin", help="request:req-N or connector:<name>")
    add.add_argument("--link", help="https:// link to the evidence")
    add.set_defaults(handler=_add)

    for name, handler in (("confirm", _confirm), ("reject", _reject)):
        sub = actions.add_parser(name, help=f"{name} a pending candidate")
        sub.add_argument("run")
        sub.add_argument("id")
        sub.set_defaults(handler=handler)

    listing = actions.add_parser("list", help="list the candidates of a run")
    listing.add_argument("run")
    listing.set_defaults(handler=_list)
