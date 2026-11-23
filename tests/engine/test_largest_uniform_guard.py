"""No test spells the largest uniform itself: a copy keeps proving a stale value if the unit mapping changes."""
from __future__ import annotations

import ast
import math
import operator
from pathlib import Path

import numpy as np
import pytest

from rqharness import engine

_ARITHMETIC = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
               ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}

# The one test that pins the value itself, as (path under tests/, name of the def it sits in).
_LARGEST_UNIFORM_PINS = {
    ("engine/test_engine_simulate.py", "test_unit_mapping_keeps_the_extreme_bits_inside_the_open_interval"),
}


def _last_name_segment(node: ast.AST) -> str | None:
    """`inf` for both `inf` and `math.inf`; None for anything that is not a name."""
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _literal_value(node: ast.AST) -> float | None:
    """The value of an arithmetic expression over number literals (and `inf`), or None if it reads anything else."""
    if _last_name_segment(node) == "inf":
        return math.inf
    operands = ([node.left, node.right] if isinstance(node, ast.BinOp)
                else [node.operand] if isinstance(node, ast.UnaryOp) else [])
    values = [_literal_value(operand) for operand in operands]
    try:  # in floats, so a huge power overflows at once instead of growing an int
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return float(node.value)
        if values and None not in values and type(node.op) in _ARITHMETIC:
            return _ARITHMETIC[type(node.op)](*values)
    except ArithmeticError:
        pass
    return None


def _spells_largest_uniform(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and _last_name_segment(node.func) == "nextafter" and len(node.args) == 2:
        start, toward = map(_literal_value, node.args)
        return None not in (start, toward) and np.nextafter(start, toward) == engine.LARGEST_UNIFORM
    return _literal_value(node) == engine.LARGEST_UNIFORM


def _largest_uniform_spellings(source: str) -> set[tuple[str, int]]:
    """(enclosing def or "<module>", line) of every expression in `source` that writes the largest uniform.

    Matching on the value an expression evaluates to, not on its text, catches every spelling at once:
    nextafter(1, 0), 1 - 2**-53, 0.9999999999999999, whatever the whitespace.
    """
    hits = set()

    def visit(node: ast.AST, function: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            function = node.name
        if _spells_largest_uniform(node):
            hits.add((function, node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, function)

    visit(ast.parse(source), "<module>")
    return hits


@pytest.mark.parametrize("spelling", [
    "nextafter(1, 0)", "np.nextafter( 1.0 ,0.0 )", "math.nextafter(1, -math.inf)", "1 - 2**-53", "1.0 - 2.0 ** -53",
    "(1-2**-53)", "0.9999999999999999", "0.99999999999999994", "1 - 1e-16",
])
def test_the_guard_sees_every_spelling_of_the_largest_uniform(spelling):
    assert _largest_uniform_spellings(f"def test_x():\n    assert u == {spelling}\n") == {("test_x", 2)}


@pytest.mark.parametrize("other", [
    "engine.LARGEST_UNIFORM", "1 - 2**-52", "2**-54", "2**53 - 1", "1 - 1e-12", "nextafter(1, 2)", "nextafter(x, 0)",
    "'0.9999999999999999'", "10**10**10", "9" * 400, "1 / 0",
])
def test_the_guard_ignores_every_other_value(other):
    assert _largest_uniform_spellings(f"def test_x():\n    assert u == {other}\n") == set()


def test_the_guard_names_the_module_for_a_spelling_outside_any_test():
    assert _largest_uniform_spellings("U = 1 - 2**-53\n") == {("<module>", 1)}


def test_tests_read_the_largest_uniform_from_the_engine():
    tests = Path(__file__).parents[1]
    hits = {(p.relative_to(tests).as_posix(), function, line) for p in tests.rglob("*.py")
            for function, line in _largest_uniform_spellings(p.read_text(encoding="utf-8"))}
    spelled_in = {(path, function) for path, function, _ in hits}
    stray = sorted((path, function, line) for path, function, line in hits
                   if (path, function) not in _LARGEST_UNIFORM_PINS)
    assert stray == [], "use engine.LARGEST_UNIFORM"
    assert _LARGEST_UNIFORM_PINS <= spelled_in, "a pin no longer spells the value: drop it"
