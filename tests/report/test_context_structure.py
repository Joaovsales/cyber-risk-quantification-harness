"""The report view model's structure: one formatting module, sectioned builders, one YAML reader."""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from pathlib import Path

import pytest

from rqharness import tiers
from rqharness.report import context, formatting

REPORT = Path(context.__file__).parent


def _imports_of(module_file: Path) -> list[tuple[str, int]]:
    """(module, depth) for every import; depth 0 is the module's top level."""
    found: list[tuple[str, int]] = []

    def walk(node: ast.AST, depth: int) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ImportFrom) and child.module:
                found.append((child.module, depth))
            elif isinstance(child, ast.Import):
                found.extend((alias.name, depth) for alias in child.names)
            nested = isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            walk(child, depth + 1 if nested else depth)

    walk(ast.parse(module_file.read_text(encoding="utf-8")), 0)
    return found


# AC1 -----------------------------------------------------------------------------------------

def test_formatting_module_owns_display_helpers():
    for name in ("lower_first", "fmt_money", "fmt_pct", "fmt_rate", "fmt_int", "pick_focus", "largest_cut"):
        assert getattr(formatting, name).__module__ == "rqharness.report.formatting", name
    assert formatting.fmt_money(120_000, "EUR") == "€120k"


@pytest.mark.parametrize("name", ["narrative.py", "svg.py", "context.py"])
def test_report_modules_take_formatters_from_formatting(name):
    modules = [m for m, _ in _imports_of(REPORT / name)]
    assert "rqharness.report.formatting" in modules
    assert "rqharness.report.context" not in modules


def test_context_imports_are_top_level():
    assert [(m, d) for m, d in _imports_of(REPORT / "context.py") if d] == []


# AC2 -----------------------------------------------------------------------------------------

def test_build_context_delegates_sections_to_builders():
    source = inspect.getsource(context.build_context)
    for builder in ("_hero", "_cards", "_appendix"):
        assert f"{builder}(" in source, builder


@pytest.mark.parametrize("name", ["_hero", "_cards", "_appendix", "_headlines", "_variant_rows", "_collect_next"])
def test_builder_trailing_parameters_are_keyword_only(name):
    params = list(inspect.signature(getattr(context, name)).parameters.values())
    leading = [p for p in params if p.kind is not inspect.Parameter.KEYWORD_ONLY]
    assert len(leading) <= 2, [p.name for p in leading]


# AC3 -----------------------------------------------------------------------------------------

def test_snapshot_dates_reach_the_view_model_as_iso_strings(make_run):
    run = make_run()
    snapshot = run / "v1" / "scenario.snapshot.yaml"
    snapshot.write_text(snapshot.read_text(encoding="utf-8").replace(
        "out_of_scope:\n", "out_of_scope:\n  - 2026-01-31\n", 1), encoding="utf-8")
    facts = dict((label, text) for label, text, _ in context.build_context(run / "v1")["scenario"]["facts"])
    assert facts["Out of scope"].startswith("2026-01-31; ")


def test_provenance_headline_counts_follow_the_tier_table(make_run, monkeypatch):
    run = make_run()  # the sample's 8 parameters: 1 internal_data, 1 sme_estimate, 4 benchmark, 2 agent_assumption
    assert context.build_context(run / "v1")["heads"]["provenance"] == (
        "Only 1 of 8 inputs comes from Northwind's own systems; 6 rely on public benchmarks or assumptions")
    table = dict(tiers.TIERS)
    table["sme_estimate"] = replace(table["sme_estimate"], is_own_data=True)
    table["benchmark"] = replace(table["benchmark"], is_fallback=False)
    monkeypatch.setattr(tiers, "TIERS", table)
    assert context.build_context(run / "v1")["heads"]["provenance"] == (
        "Only 2 of 8 inputs come from Northwind's own systems; 2 rely on public benchmarks or assumptions")


def test_missing_snapshot_raises_file_not_found(make_run):
    run = make_run()
    (run / "v1" / "theme.snapshot.yaml").unlink()
    with pytest.raises(FileNotFoundError):
        context.build_context(run / "v1")
