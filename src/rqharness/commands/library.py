"""`rqh library`: search, add, list, remove and validate the memory library."""

from __future__ import annotations

import argparse
from pathlib import Path

from rqharness import cli, library
from rqharness.outcomes import NotFound, Rejected, issue
from rqharness.schemas import load_yaml


def _search(args: argparse.Namespace) -> cli.Outcome:
    query = library.LibraryQuery(args.family, args.scenario_type, args.industry, args.size_band, args.currency)
    hits = library.search(query, workspace=cli.existing_workspace())
    return cli.ok({"hits": [
        {"entry_id": h.entry["entry_id"], "origin": h.origin, "stale": h.stale,
         "currency_mismatch": h.currency_mismatch, "segment_match": h.segment_match, "entry": h.entry}
        for h in hits
    ]})


def _add(args: argparse.Namespace) -> cli.Outcome:
    root = cli.require_workspace()
    path = Path(args.entry)
    if not path.is_file():
        raise NotFound([issue("entry", "missing", f"no file at {path}")])
    data, issues = load_yaml(path, "entry")
    if issues:
        raise Rejected(issues)
    result = library.add(data, workspace=root)
    name = "added" if isinstance(result, library.Added) else "duplicate"
    return cli.ok({"result": name, "path": str(result.path)}, text=f"{name}: {result.path}")


def _list(_: argparse.Namespace) -> cli.Outcome:
    keys = ("entry_id", "parameter_family", "tier", "sensitivity")
    entries = [{k: e[k] for k in keys} for e in library.memory_entries(cli.require_workspace())]
    return cli.ok({"entries": entries})


def _remove(args: argparse.Namespace) -> cli.Outcome:
    library.remove(args.entry_id, workspace=cli.require_workspace())
    return cli.ok({"removed": args.entry_id}, text=f"removed {args.entry_id}")


def _validate(_: argparse.Namespace) -> cli.Outcome:
    issues = library.validate_all(workspace=cli.require_workspace())
    if issues:
        raise Rejected(issues)
    return cli.ok({}, text="ok")


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("library", help="search and maintain the memory library")
    sub = parser.add_subparsers(dest="library_command", required=True)

    search = sub.add_parser("search", help="find entries for a parameter family")
    search.add_argument("--family", required=True, help="parameter family, e.g. primary_loss.response")
    search.add_argument("--scenario-type")
    search.add_argument("--industry")
    search.add_argument("--size-band")
    search.add_argument("--currency", help="the run currency; hits in another currency are flagged")
    search.set_defaults(handler=_search)

    add = sub.add_parser("add", help="add one entry to memory")
    add.add_argument("entry", help="path to a library-entry YAML file")
    add.set_defaults(handler=_add)

    sub.add_parser("list", help="list memory entries").set_defaults(handler=_list)

    remove = sub.add_parser("remove", help="prune one memory entry")
    remove.add_argument("entry_id")
    remove.set_defaults(handler=_remove)

    sub.add_parser("validate", help="re-validate every memory entry").set_defaults(handler=_validate)
