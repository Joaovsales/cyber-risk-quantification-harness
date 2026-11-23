"""`rqh requests`: add, update and list requests for data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from rqharness import cli, requests, tiers, workspace
from rqharness.outcomes import Rejected, Usage, issue

EVIDENCE = tuple(tiers.EVIDENCE_TIER)
# The envelope's `result` names are a CLI contract skills parse: never derive them from class names.
_RESULT_NAMES = {requests.Added: "added", requests.Updated: "updated", requests.Confirmed: "confirmed"}
_STATUSES = sorted({*requests.REQUEST_TRANSITIONS, *(s for to in requests.REQUEST_TRANSITIONS.values() for s in to)})


def outcome(result: requests.Added | requests.Duplicate | requests.Updated | requests.Confirmed, key: str, *,
            text: str = "") -> cli.Outcome:
    """The envelope of a ``requests`` success; its failures are raised and never reach here."""
    if isinstance(result, requests.Duplicate):
        return cli.ok({"result": "duplicate", key: result.item}, text=f"duplicate of {result.item['id']}")
    if isinstance(result, requests.Updated) and not result.changed:
        return cli.ok({"result": "unchanged", key: result.item}, text=text)
    item = result.candidate if isinstance(result, requests.Confirmed) else result.item
    return cli.ok({"result": _RESULT_NAMES[type(result)], key: item}, text=text)


VALUE_KEYS = ("min", "mode", "max", "unit")


def value_of(fields: dict) -> dict | None:
    """The value in ``fields`` (from the flags or from an input file), or None when it holds none."""
    given = [fields.get(k) is not None for k in VALUE_KEYS]
    if not any(given):
        return None
    if not all(given):
        raise Rejected([issue(
            "value", "incomplete", "a value needs --min, --mode, --max and --unit together")])
    return {k: fields[k] for k in VALUE_KEYS}


def add_value_arguments(parser: argparse.ArgumentParser, *, required: bool) -> None:
    for name in ("min", "mode", "max"):
        parser.add_argument(f"--{name}", type=float, required=required)
    parser.add_argument("--unit", required=required)
    parser.add_argument("--evidence", choices=EVIDENCE, required=required)


def _file_error(flag: str, message: str) -> Usage:
    return Usage([issue(f"argv.{flag}", "file", message)])


def _run_file(run_dir: Path, value: str, flag: str) -> str:
    """The UTF-8 text of a file inside the run directory; anything else is a usage error (exit 2).

    Skills write connector-derived text to such a file so it never passes through a shell.
    """
    path = Path(value).resolve()
    if not path.is_relative_to(run_dir.resolve()):
        raise _file_error(flag, f"--{flag} must name a file inside the run directory {run_dir}")
    if not path.is_file():
        raise _file_error(flag, f"--{flag}: no file at {value}")
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError:
        raise _file_error(flag, f"--{flag}: {value} is not UTF-8 text") from None


# The fields of a request: each request-file key, with the flags that supply it when there is no request file.
_FIELDS = {"owner_role": ("--owner-role",), "person": ("--person",), "ask": ("--ask", "--ask-file"),
           "draft": ("--draft", "--draft-file")}
_OPTIONAL = ("person",)


def _usage_error(message: str) -> Usage:
    return Usage([issue("argv", "usage", message)])


def _missing(fields: dict) -> list[str]:
    return [key for key in _FIELDS if key not in _OPTIONAL and fields.get(key) is None]


def run_mapping(run_dir: Path, value: str, flag: str, keys: tuple[str, ...], required: tuple[str, ...]) -> dict:
    """The fields of one input file inside the run directory: JSON when it ends in .json, else YAML.

    Any problem with the file itself is a usage error (exit 2) at ``argv.<flag>``. The values are
    stored verbatim; their types are checked by the requests schema on save. A null value is absent.
    """
    text = _run_file(run_dir, value, flag)
    try:  # the alias-refusing parser every rqh document goes through
        data = json.loads(text) if Path(value).suffix.lower() == ".json" else workspace.parse_yaml(text.encode("utf-8"))
    except (ValueError, yaml.YAMLError):
        raise _file_error(flag, f"--{flag}: {value} is not valid YAML or JSON") from None
    data = {} if data is None and not required else data
    if not isinstance(data, dict):
        raise _file_error(flag, f"--{flag}: {value} must hold a mapping of {', '.join(keys)}")
    unknown = sorted(map(str, set(data) - set(keys)))
    missing = [key for key in required if data.get(key) is None]
    if unknown or missing:
        raise _file_error(flag, f"--{flag}: {value} " + "; ".join(
            ([f"has unknown keys {', '.join(unknown)}"] if unknown else [])
            + ([f"needs {', '.join(missing)}"] if missing else [])))
    return {key: v for key, v in data.items() if v is not None}


def flags_given(args: argparse.Namespace, flags: tuple[str, ...]) -> list[str]:
    """The flags among ``flags`` that the command line set."""
    return [flag for flag in flags if getattr(args, flag[2:].replace("-", "_")) is not None]


def _request_file(run_dir: Path, value: str) -> dict:
    """The owner role, person, ask and draft from one request file inside the run directory."""
    return run_mapping(run_dir, value, "request-file", tuple(_FIELDS),
                       tuple(key for key in _FIELDS if key not in _OPTIONAL))


def _request_flags(run_dir: Path, args: argparse.Namespace) -> dict:
    fields = {"owner_role": args.owner_role, "person": args.person,
              "ask": _run_file(run_dir, args.ask_file, "ask-file") if args.ask_file else args.ask,
              "draft": _run_file(run_dir, args.draft_file, "draft-file") if args.draft_file else args.draft}
    if missing := _missing(fields):
        raise _usage_error("requests add needs --request-file, or " + " and ".join(" or ".join(_FIELDS[k]) for k in missing))
    return fields


def _request_fields(run_dir: Path, args: argparse.Namespace) -> dict:
    """The owner role, person, ask and draft: from --request-file, or from the per-field flags."""
    if not args.request_file:
        return _request_flags(run_dir, args)
    if given := flags_given(args, tuple(flag for flags in _FIELDS.values() for flag in flags)):
        raise _usage_error(f"--request-file holds the role, person, ask and draft; leave out {', '.join(given)}")
    return _request_file(run_dir, args.request_file)


def _add(args: argparse.Namespace) -> cli.Outcome:
    run_dir = cli.resolve_run(args.run).dir
    fields = _request_fields(run_dir, args)
    result = requests.add_request(
        run_dir, parameter_path=args.parameter, ask=fields["ask"], owner_role=fields["owner_role"],
        person=fields.get("person"), draft_message=fields["draft"], due_at=args.due)
    return outcome(result, "request", text=f"added {result.item['id']}")


# The fields of an answer: each answer-file key, with the flag that supplies it when there is no answer file.
_ANSWER_FIELDS = {**{key: f"--{key}" for key in VALUE_KEYS}, "evidence": "--evidence", "note": "--note"}


def _answer_fields(run_dir: Path, args: argparse.Namespace) -> dict:
    """The answer's value, evidence kind and note: from --answer-file, or from the per-field flags."""
    if not args.answer_file:
        return {key: getattr(args, key) for key in _ANSWER_FIELDS}
    if given := flags_given(args, tuple(_ANSWER_FIELDS.values())):
        raise _usage_error(f"--answer-file holds the value, evidence and note; leave out {', '.join(given)}")
    return run_mapping(run_dir, args.answer_file, "answer-file", tuple(_ANSWER_FIELDS), ())


def _update(args: argparse.Namespace) -> cli.Outcome:
    run_dir = cli.resolve_run(args.run).dir
    fields = _answer_fields(run_dir, args)
    value, note = value_of(fields), fields.get("note")
    answer = None
    if value or note:
        answer = {**({"value": value, "evidence_kind": fields.get("evidence")} if value else {}),
                  **({"note": note} if note else {})}
    result = requests.transition_request(run_dir, args.id, args.status, answer=answer)
    return outcome(result, "request", text=f"{args.id} is {args.status}")


def _list(args: argparse.Namespace) -> cli.Outcome:
    items = requests.load(cli.resolve_run(args.run).dir)["requests"]
    return cli.ok({"requests": items}, text="\n".join(f"{r['id']} {r['status']} {r['parameter_path']}" for r in items))


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("requests", help="add, update or list requests for data")
    actions = parser.add_subparsers(dest="action", metavar="<action>", parser_class=type(parser))

    add = actions.add_parser("add", help="draft a request for one parameter")
    add.add_argument("run")
    add.add_argument("--parameter", required=True)
    add.add_argument("--request-file", help="a file inside the run directory holding owner_role, person (optional), "
                                            "ask and draft, read as JSON when it ends in .json and as YAML otherwise; "
                                            "replaces --owner-role, --person, --ask/--ask-file and --draft/--draft-file")
    add.add_argument("--owner-role")
    add.add_argument("--person")
    ask = add.add_mutually_exclusive_group()
    ask.add_argument("--ask", help="the ask text")
    ask.add_argument("--ask-file", help="a file inside the run directory holding the ask text")
    draft = add.add_mutually_exclusive_group()
    draft.add_argument("--draft", help="the message text")
    draft.add_argument("--draft-file", help="a file inside the run directory holding the message text")
    add.add_argument("--due", help="YYYY-MM-DD")
    add.set_defaults(handler=_add)

    update = actions.add_parser("update", help="move a request to a new status")
    update.add_argument("run")
    update.add_argument("id")
    update.add_argument("--status", required=True, choices=_STATUSES)
    add_value_arguments(update, required=False)
    update.add_argument("--note")
    update.add_argument("--answer-file", help="a file inside the run directory holding the answer's min, mode, max, "
                                              "unit, evidence and note (each optional), read as JSON when it ends "
                                              "in .json and as YAML otherwise; replaces --min, --mode, --max, "
                                              "--unit, --evidence and --note")
    update.set_defaults(handler=_update)

    listing = actions.add_parser("list", help="list the requests of a run")
    listing.add_argument("run")
    listing.set_defaults(handler=_list)
