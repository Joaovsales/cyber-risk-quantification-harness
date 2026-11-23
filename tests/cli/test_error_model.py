"""One domain error model, mapped to exit codes in one place."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "rqharness"
DOMAIN = ("runstate", "chain", "routing", "orgprofile", "finalize", "requests", "library", "schemas",
          "validate", "workspace", "model", "engine", "quality", "search", "report/render", "report/narrative",
          "report/context")


def _imports(path: Path) -> set[str]:
    """Every rqharness module (and imported name) a file imports."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("rqharness"):
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("rqharness"))
    return found


def test_outcomes_is_a_leaf():
    assert _imports(SRC / "outcomes.py") == set()


@pytest.mark.parametrize("module", DOMAIN)
def test_domain_module_does_not_import_cli(module):
    assert not {name for name in _imports(SRC / f"{module}.py") if name.startswith("rqharness.cli")}


def test_each_failure_kind_has_one_exit_code_in_cli():
    from rqharness import cli, outcomes

    kinds = {outcomes.Rejected, outcomes.Usage, outcomes.IllegalTransition, outcomes.NarrativeRejected,
             outcomes.NotFound}
    assert set(cli.EXIT_CODES) == kinds
    assert all(issubclass(kind, outcomes.DomainError) for kind in kinds)
    assert cli.EXIT_CODES == {outcomes.Rejected: 1, outcomes.Usage: 2, outcomes.IllegalTransition: 3,
                              outcomes.NarrativeRejected: 4, outcomes.NotFound: 5}
    assert not hasattr(cli, "CommandError") and not hasattr(cli, "fail")


def test_a_refined_kind_exits_as_its_parent_and_the_base_cannot_be_raised():
    from rqharness import cli, outcomes

    class LockHeld(outcomes.Rejected):
        pass

    assert cli._failed(LockHeld([outcomes.issue("run.lock", "lock_held", "held")])).exit_code == cli.EXIT_REJECTED
    with pytest.raises(TypeError):
        outcomes.DomainError([outcomes.issue("x", "y", "z")])
    with pytest.raises(ValueError):
        outcomes.Rejected([])


@pytest.mark.parametrize("path", sorted((SRC / "commands").glob("*.py")), ids=lambda p: p.name)
def test_no_command_names_an_exit_code(path):
    """Commands raise failure kinds; only cli turns a kind into an exit code."""
    text = path.read_text(encoding="utf-8")
    assert "EXIT_" not in text and "cli.fail" not in text and "CommandError" not in text


def test_a_raised_kind_renders_through_the_one_handler(tmp_path, monkeypatch, capsys):
    from rqharness import cli, outcomes

    def handler(_):
        raise outcomes.IllegalTransition([outcomes.issue("run.status", "illegal_transition", "cannot x")])

    class Args:
        pass

    args = Args()
    args.handler = handler
    monkeypatch.setattr(cli, "build_parser", lambda: type("P", (), {"parse_args": lambda self, a: args})())
    assert cli.main(["--json"]) == 3
    assert json.loads(capsys.readouterr().out)["issues"] == [
        {"path": "run.status", "rule": "illegal_transition", "message": "cannot x"}]


@pytest.mark.parametrize("argv, path", [
    (["run", "confirm", "s", "--route", "yolo", "--n", "0"], "argv.n"),
    (["finalize", "s", "--n", "0"], "argv.n"),
    (["run", "confirm", "s", "--route", "yolo", "--seed", "-1"], "argv.seed"),
    (["finalize", "s", "--seed", "-1"], "argv.seed"),
])
def test_an_out_of_range_draw_argument_is_a_usage_error_from_every_command(argv, path, tmp_path, monkeypatch, capsys):
    from rqharness import cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    assert cli.main(["init"]) == 0
    (tmp_path / ".riskquant" / "runs" / "s").mkdir(parents=True)
    capsys.readouterr()
    assert cli.main([*argv, "--json"]) == cli.EXIT_USAGE
    [only] = json.loads(capsys.readouterr().out)["issues"]
    assert (only["path"], only["rule"]) == (path, "range")
