"""AC1: an installable `rqh`, `--version`, the `rqharness` import, command discovery."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_package_imports_as_rqharness():
    import rqharness

    assert rqharness.__name__ == "rqharness"
    assert isinstance(rqharness.__version__, str)


def test_version_flag_prints_package_version(capsys):
    from rqharness import __version__, cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"rqh {__version__}"


def test_pyproject_exposes_rqh_entry_point():
    project = _pyproject()["project"]
    assert project["name"] == "risk-quantification-harness"
    assert project["scripts"]["rqh"] == "rqharness.cli:entry"
    assert project["license"] == "Apache-2.0"
    assert project["requires-python"] == ">=3.11"
    deps = {d.split(">")[0].split("=")[0].split("<")[0].strip().lower() for d in project["dependencies"]}
    assert deps == {"numpy", "scipy", "jsonschema", "pyyaml", "jinja2", "markupsafe"}


def test_module_entry_runs_as_subprocess():
    from rqharness import __version__

    import os

    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    out = subprocess.run(
        [sys.executable, "-m", "rqharness", "--version"],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    assert out.stdout.strip() == f"rqh {__version__}"


@pytest.fixture
def fake_command(tmp_path, monkeypatch):
    """Drop a command module into an extra `rqharness.commands` path entry."""
    import rqharness.commands as commands

    pkg = tmp_path / "extra"
    pkg.mkdir()
    (pkg / "hello.py").write_text(
        textwrap.dedent(
            '''
            from rqharness import cli, outcomes

            def register(subparsers):
                p = subparsers.add_parser("hello", help="say hello")
                p.add_argument("who")
                p.set_defaults(handler=run)

            def run(args):
                if args.who == "nobody":
                    raise outcomes.Rejected([outcomes.issue("who", "required", "no one to greet")])
                return cli.ok({"greeting": f"hello {args.who}"}, text=f"hello {args.who}")
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(commands, "__path__", [*commands.__path__, str(pkg)])
    sys.modules.pop("rqharness.commands.hello", None)
    yield
    sys.modules.pop("rqharness.commands.hello", None)


def test_commands_discovered_from_package(fake_command, capsys):
    from rqharness import cli

    assert "hello" in cli.discover_commands()
    assert cli.main(["hello", "world"]) == 0
    assert capsys.readouterr().out.strip() == "hello world"


def test_json_envelope_on_success_and_rejection(fake_command, capsys):
    from rqharness import cli

    assert cli.main(["hello", "world", "--json"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env == {"schema_version": "1", "ok": True, "data": {"greeting": "hello world"}, "issues": []}

    assert cli.main(["hello", "nobody", "--json"]) == cli.EXIT_REJECTED
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False and env["data"] is None
    assert env["issues"] == [{"path": "who", "rule": "required", "message": "no one to greet"}]


def test_usage_error_exits_2_with_envelope(capsys):
    from rqharness import cli

    assert cli.main(["no-such-command", "--json"]) == cli.EXIT_USAGE
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False and env["issues"][0]["rule"] == "usage"


def test_exit_codes_match_spec():
    from rqharness import cli

    assert (cli.EXIT_OK, cli.EXIT_REJECTED, cli.EXIT_USAGE, cli.EXIT_TRANSITION, cli.EXIT_NARRATIVE, cli.EXIT_MISSING) == (
        0, 1, 2, 3, 4, 5,
    )


def _missing_workspace_issue(root: Path) -> dict:
    return {"path": "workspace", "rule": "missing", "message": f"no workspace at {root}; run `rqh init`"}


def test_require_workspace_names_the_missing_root_and_rqh_init(tmp_path, monkeypatch):
    from rqharness import cli, outcomes, workspace

    root = tmp_path / "ws"
    monkeypatch.setenv(cli.WORKSPACE_ENV, str(root))
    with pytest.raises(outcomes.NotFound) as exc:
        cli.require_workspace()
    assert exc.value.issues == [_missing_workspace_issue(root)]

    other = tmp_path / "other"
    with pytest.raises(outcomes.NotFound) as exc:
        workspace.require_workspace(other)
    assert exc.value.issues == [_missing_workspace_issue(other)]

    root.mkdir()
    assert cli.require_workspace() == root


def test_every_missing_workspace_error_comes_from_require_workspace(tmp_path, monkeypatch, capsys):
    """resolve_run (by id and by path), chain.next_step and `rqh library` share one builder of the error."""
    from rqharness import chain, cli, outcomes, workspace

    monkeypatch.setenv(cli.WORKSPACE_ENV, str(tmp_path / "ws"))
    seen: list[Path] = []
    real = workspace.require_workspace

    def spy(root):
        seen.append(root)
        return real(root)

    monkeypatch.setattr(workspace, "require_workspace", spy)
    with pytest.raises(outcomes.NotFound):
        cli.resolve_run("r1")
    (tmp_path / "copied").mkdir()
    with pytest.raises(outcomes.NotFound) as exc:
        cli.resolve_run(str(tmp_path / "copied"))
    assert exc.value.issues == [_missing_workspace_issue(tmp_path / "ws")]
    elsewhere = tmp_path / "elsewhere"
    with pytest.raises(outcomes.NotFound):
        chain.next_step(workspace.Run(elsewhere, elsewhere / "runs" / "r1"))
    assert cli.main(["library", "list", "--json"]) == cli.EXIT_MISSING
    env = json.loads(capsys.readouterr().out)
    assert env["issues"] == [_missing_workspace_issue(tmp_path / "ws")]
    assert seen == [tmp_path / "ws", tmp_path / "ws", elsewhere, tmp_path / "ws"]


def test_resolve_run_missing_run_exits_5_naming_the_workspace(tmp_path, monkeypatch):
    from rqharness import cli, outcomes

    root = tmp_path / "ws"
    (root / "runs").mkdir(parents=True)
    monkeypatch.setenv(cli.WORKSPACE_ENV, str(root))
    with pytest.raises(outcomes.NotFound) as exc:
        cli.resolve_run("r1")
    assert cli.EXIT_CODES[type(exc.value)] == cli.EXIT_MISSING
    assert exc.value.issues == [
        {"path": "run", "rule": "missing", "message": f"no run named 'r1' in {root}"}
    ]
    for not_a_name in ("../r1", "a/b"):  # neither an existing directory nor a run name
        with pytest.raises(outcomes.NotFound):
            cli.resolve_run(not_a_name)
    (root / "runs" / "r1").mkdir()
    assert cli.resolve_run("r1").dir == root / "runs" / "r1"


def test_resolve_run_returns_a_run_carrying_its_workspace_by_id_and_by_path(tmp_path, monkeypatch):
    from rqharness import cli, workspace

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    root = tmp_path / ".riskquant"
    (root / "runs" / "r1").mkdir(parents=True)
    by_id = cli.resolve_run("r1")
    assert by_id == workspace.Run(root, root / "runs" / "r1")
    assert cli.resolve_run(str(Path(".riskquant") / "runs" / "r1")) == by_id  # one run, one Run, any spelling
    assert workspace.Run.named(root, "r1") == by_id


@pytest.mark.parametrize("where", [
    "copies/r1",                    # a copied run with no workspace around it
    "other/.riskquant/runs/r1",     # a run of another workspace than the one in use
    ".riskquant/runs/r1/v1",        # a directory inside a run is not a run
    ".riskquant/runs",              # nor is the runs folder itself
])
def test_resolve_run_refuses_a_directory_outside_the_workspace_runs_with_exit_2(where, tmp_path, monkeypatch):
    from rqharness import cli, outcomes

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    (tmp_path / ".riskquant" / "runs" / "r1" / "v1").mkdir(parents=True)
    (tmp_path / where).mkdir(parents=True, exist_ok=True)
    with pytest.raises(outcomes.Usage) as exc:
        cli.resolve_run(str(tmp_path / where))
    assert cli.EXIT_CODES[type(exc.value)] == cli.EXIT_USAGE
    [only] = exc.value.issues
    assert (only["path"], only["rule"]) == ("run", "outside_workspace")
    assert str(tmp_path / ".riskquant" / "runs") in only["message"]
    assert cli.WORKSPACE_ENV in only["message"]


def test_a_run_value_holds_only_a_directory_directly_inside_its_workspace_runs(tmp_path):
    from rqharness import workspace

    ws = tmp_path / "ws"
    assert workspace.Run(ws, ws / "runs" / "r1").dir == ws / "runs" / "r1"
    for outside in (tmp_path / "r1", ws / "r1", ws / "runs" / "r1" / "v1", ws / "runs", ws / "runs" / ".."):
        with pytest.raises(ValueError):
            workspace.Run(ws, outside)


def test_workspace_has_no_run_dir_helper():
    """resolve_run is the one place a run id becomes a directory."""
    from rqharness import workspace

    assert not hasattr(workspace, "run_dir")


def test_ok_outcome_carries_no_issues_and_writes_nothing_to_stderr(fake_command, capsys):
    """Pins the rendering the removed ok-with-issues branch never reached."""
    from rqharness import cli

    assert cli.ok({"a": 1}, text="done").issues == []
    assert cli.main(["hello", "world"]) == 0
    out = capsys.readouterr()
    assert out.out.strip() == "hello world" and out.err == ""


def test_license_and_notice_present():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text and "Version 2.0, January 2004" in license_text
    assert "END OF TERMS AND CONDITIONS" in license_text
    assert (ROOT / "NOTICE").read_text(encoding="utf-8").strip()


def test_ci_matrix_covers_three_operating_systems():
    import yaml

    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = next(iter(ci["jobs"].values()))
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "macos-latest", "windows-latest"}
    steps = " ".join(str(s.get("run", "")) for s in job["steps"])
    assert "pytest" in steps
