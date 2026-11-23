"""Render one finalized version into a single self-contained ``report.html``."""

from __future__ import annotations

import base64
import functools
import hashlib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from jinja2 import Environment, PackageLoader, StrictUndefined
from markupsafe import Markup

from rqharness import finalize
from rqharness.outcomes import NotFound, issue
from rqharness.report import context
from rqharness.report.narrative import render_narrative
from rqharness.workspace import atomic_write_text

__all__ = ["Rendered", "render_report"]

REQUIRED = ("run_summary.json", "run_manifest.json", "inputs.snapshot.yaml", "scenario.snapshot.yaml",
            "theme.snapshot.yaml")
# styles stay inline (the charts and bars carry style attributes); the one script is allowed by its hash
_CSP = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src {script}; "
        "base-uri 'none'; form-action 'none'")


@dataclass(frozen=True)
class Rendered:
    path: Path
    version: int
    narrative_omitted: bool


def _missing(name: str) -> NotFound:
    return NotFound([issue(name, "missing", f"{name} is missing; run `rqh finalize` first")])


@functools.lru_cache(maxsize=1)
def _environment() -> Environment:
    return Environment(loader=PackageLoader("rqharness.report", "templates"), autoescape=True,
                       undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)


@functools.lru_cache(maxsize=1)
def _assets() -> dict[str, str]:
    folder = resources.files("rqharness.report") / "assets"
    return {item.name: item.read_text(encoding="utf-8") for item in sorted(folder.iterdir(), key=lambda i: i.name)
            if item.is_file()}


@functools.lru_cache(maxsize=1)
def _csp() -> str:
    """The page's Content-Security-Policy: only the exact inlined ``report.js`` may run."""
    script = _assets().get("report.js")
    if script is None:
        return _CSP.format(script="'none'")
    digest = base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode("ascii")
    return _CSP.format(script=f"'sha256-{digest}'")


def render_report(run_dir: Path, version: int | None = None, *, narrative: Path | None = None,
                  omit_narrative: bool = False) -> Rendered:
    """Write ``v<N>/report.html`` from that version's files only (plus package resources).

    A `narrative` file is validated first and, when accepted, stored as ``v<N>/narrative.md``; later
    renders use the stored copy. Raises ``NotFound`` for a missing version, version file or narrative
    file, ``Rejected`` for a summary ``context.load_summary`` refuses, and ``NarrativeRejected`` for a
    narrative, passed or stored, that breaks the literal rule; none of them writes a file.
    """
    number = version if version is not None else finalize.latest_version(run_dir)
    if number is None:
        raise _missing("v1")
    vdir = run_dir / f"v{number}"
    for name in REQUIRED:
        if not (vdir / name).is_file():
            raise _missing(f"v{number}/{name}")
    summary = context.load_summary(vdir)
    if narrative is not None:
        if not narrative.is_file():
            raise _missing(str(narrative))
        text = narrative.read_text(encoding="utf-8")
        rejected = render_narrative(text, summary).rejected
        if rejected is not None:
            raise rejected.error()
        atomic_write_text(vdir / "narrative.md", text)
    page = _environment().get_template("report.html.j2").render(
        c=context.build_context(vdir, omit_narrative=omit_narrative), assets=_assets(), csp=Markup(_csp()))
    target = vdir / "report.html"
    atomic_write_text(target, page)
    return Rendered(target, number, omit_narrative)
