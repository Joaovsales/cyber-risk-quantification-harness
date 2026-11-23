"""`rqh search`: optional Tavily web search for the data-collection skill."""

from __future__ import annotations

import argparse
import os

from rqharness import cli, search
from rqharness.outcomes import Rejected, Usage, issue

API_KEY_ENV = "TAVILY_API_KEY"


def _run(args: argparse.Namespace) -> cli.Outcome:
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise Usage([issue(f"env.{API_KEY_ENV}", "missing", f"{API_KEY_ENV} is not set; web search is optional")])
    try:
        result = search.search(args.query, max_results=args.max_results, depth=args.depth, api_key=api_key)
    except search.SearchError as exc:  # a network fault, not a domain rule: it becomes one here
        raise Rejected([issue("search", "network", str(exc))]) from None
    return cli.ok(dict(result))


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("search", help="optional Tavily web search (needs TAVILY_API_KEY)")
    parser.add_argument("query")
    parser.add_argument("--max-results", type=int, default=5, metavar="N")
    parser.add_argument("--depth", choices=("basic", "advanced"), default="basic")
    parser.set_defaults(handler=_run)
