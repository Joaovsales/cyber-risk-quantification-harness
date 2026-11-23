"""Slice 7: workspace init (AC11) and the run lifecycle (AC12)."""

from __future__ import annotations

import itertools
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from rqharness import cli, outcomes, runstate, workspace
from rqharness.schemas import validate_document

SAMPLE = Path(__file__).parent.parent / "validate" / "fixtures" / "sample-run" / "scenario.yaml"
RUN_ID = "credential-phishing-bec"
STATUSES = ["scoping", "collecting", "awaiting_data", "finalized"]
TRIGGERS = ["confirm", "rescope", "pause", "resume", "auto_resume", "finalize", "reopen"]
LISTED = [
    ("scoping", "confirm", "collecting"),
    ("collecting", "rescope", "scoping"),
    ("collecting", "pause", "awaiting_data"),
    ("awaiting_data", "resume", "collecting"),
    ("awaiting_data", "auto_resume", "collecting"),
    ("collecting", "finalize", "finalized"),
    ("awaiting_data", "finalize", "finalized"),
    ("finalized", "reopen", "collecting"),
]
CLI_TRIGGERS = ["pause", "resume", "reopen", "rescope"]


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    return tmp_path / ".riskquant"


def rqh(*argv, capsys):
    capsys.readouterr()  # drop output of earlier setup commands
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else None)


@pytest.fixture
def run_dir(ws):
    assert cli.main(["init"]) == 0
    d = ws / "runs" / RUN_ID
    d.mkdir(parents=True)
    shutil.copy(SAMPLE, d / "scenario.yaml")
    return d


def snapshot(root: Path):
    return {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}


def state(status: str, **extra) -> dict:
    return {"schema_version": "1", "scenario_id": RUN_ID, "route": "yolo", "n": 50000, "seed": 7,
            "status": status, "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z", **extra}


def put_requests(run_dir: Path, *statuses: str):
    """A requests.yaml that validates: the pause guard reads it as requests.load does."""
    reqs = [{"id": f"req-{i + 1}", "parameter_path": "primary_loss.response", "ask": "Cost?",
             "target": {"owner_role": "IR lead"}, "draft_message": "Hi", "status": s,
             "created_at": "2026-01-01T00:00:00Z"} for i, s in enumerate(statuses)]
    workspace.write_yaml(run_dir / "requests.yaml", {"schema_version": "1", "scenario_id": RUN_ID,
                                                     "requests": reqs, "candidates": []})


# --- AC11 --------------------------------------------------------------------


def test_init_writes_gitignore_star(ws, capsys):
    code, env = rqh("init", capsys=capsys)
    assert code == 0 and env["data"] == {"workspace": str(ws), "created": True, "gitignore": "present"}
    assert (ws / ".gitignore").read_bytes() == b"*\n"
    assert (ws / "runs").is_dir() and (ws / "library").is_dir()


def test_init_idempotent(ws, capsys):
    cli.main(["init"])
    before = snapshot(ws)
    dirs = sorted(p.name for p in ws.iterdir())
    code, env = rqh("init", capsys=capsys)
    assert code == 0 and env["data"]["created"] is False
    assert snapshot(ws) == before and sorted(p.name for p in ws.iterdir()) == dirs


def test_init_respects_deleted_gitignore(ws, capsys):
    cli.main(["init"])
    (ws / ".gitignore").unlink()
    code, env = rqh("init", capsys=capsys)
    assert code == 0 and env["data"]["gitignore"] == "absent"
    assert not (ws / ".gitignore").exists()


def test_init_honours_env_workspace(tmp_path, monkeypatch):
    target = tmp_path / "elsewhere"
    monkeypatch.setenv("RQH_WORKSPACE", str(target))
    assert cli.main(["init"]) == 0
    assert (target / ".gitignore").read_text() == "*\n"


def test_atomic_write_leaves_no_temp_files_and_uses_lf(tmp_path):
    target = tmp_path / "a" / "x.yaml"
    target.parent.mkdir()
    workspace.write_yaml(target, {"b": 1, "a": [1, 2]})
    workspace.atomic_write_text(target, "one\ntwo\n")
    assert target.read_bytes() == b"one\ntwo\n"
    assert [p.name for p in target.parent.iterdir()] == ["x.yaml"]
    assert workspace.read_yaml(tmp_path / "missing.yaml") is None


def test_write_yaml_keeps_key_order(tmp_path):
    workspace.write_yaml(tmp_path / "y.yaml", {"z": 1, "a": 2})
    assert (tmp_path / "y.yaml").read_text().splitlines() == ["z: 1", "a: 2"]
    assert workspace.read_yaml(tmp_path / "y.yaml") == {"z": 1, "a": 2}


def test_utc_now_format():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", workspace.utc_now())


# --- AC12 --------------------------------------------------------------------


@pytest.mark.parametrize("frm,trigger,to", LISTED)
def test_every_listed_transition_allowed(run_dir, frm, trigger, to):
    if frm != "scoping":
        workspace.write_yaml(run_dir / "run.yaml", state(frm))
    if (frm, trigger) == ("collecting", "pause"):
        put_requests(run_dir, "drafted")
    changes = {"scenario_id": RUN_ID, "route": "yolo", "n": 50000, "seed": 3} if trigger == "confirm" else {}
    result = runstate.apply(run_dir, trigger, **changes)
    assert result["status"] == to and runstate.status_of(run_dir) == to
    assert validate_document("run", workspace.read_yaml(run_dir / "run.yaml")) == []


def _illegal():
    legal = {(f, t) for f, t, _ in LISTED}
    return [(s, t) for s, t in itertools.product(STATUSES, TRIGGERS) if (s, t) not in legal]


@pytest.mark.parametrize("frm,trigger", _illegal())
def test_unlisted_transition_exit_3(run_dir, frm, trigger):
    workspace.write_yaml(run_dir / "run.yaml", state(frm))
    before = (run_dir / "run.yaml").read_bytes()
    with pytest.raises(outcomes.IllegalTransition) as exc:
        runstate.apply(run_dir, trigger)
    assert exc.value.issues[0]["path"] == "run.status"
    assert exc.value.issues[0]["rule"] == "illegal_transition"
    assert (run_dir / "run.yaml").read_bytes() == before


@pytest.mark.parametrize("frm,trigger", [(s, t) for s, t in _illegal() if t in CLI_TRIGGERS])
def test_cli_unlisted_transition_exit_3(run_dir, frm, trigger, capsys):
    workspace.write_yaml(run_dir / "run.yaml", state(frm))
    put_requests(run_dir, "sent")
    before = (run_dir / "run.yaml").read_bytes()
    code, env = rqh("run", trigger, RUN_ID, capsys=capsys)
    assert code == 3 and env["issues"][0]["rule"] == "illegal_transition"
    assert (run_dir / "run.yaml").read_bytes() == before


@pytest.mark.parametrize("frm,trigger,to", [r for r in LISTED if r[1] in CLI_TRIGGERS])
def test_cli_listed_transition(run_dir, frm, trigger, to, capsys):
    workspace.write_yaml(run_dir / "run.yaml", state(frm))
    put_requests(run_dir, "drafted")
    code, env = rqh("run", trigger, RUN_ID, capsys=capsys)
    assert code == 0 and env["data"]["status"] == to


def test_status_of_without_run_yaml_is_scoping(run_dir):
    assert runstate.status_of(run_dir) == "scoping" and runstate.read_state(run_dir) is None


def test_invalid_run_yaml_is_exit_1(run_dir):
    workspace.write_yaml(run_dir / "run.yaml", {"schema_version": "1"})
    with pytest.raises(outcomes.Rejected):
        runstate.read_state(run_dir)


def test_updated_at_written(run_dir, monkeypatch):
    workspace.write_yaml(run_dir / "run.yaml", state("collecting"))
    monkeypatch.setattr(workspace, "utc_now", lambda: "2030-05-06T07:08:09Z")
    assert runstate.apply(run_dir, "finalize")["updated_at"] == "2030-05-06T07:08:09Z"


# --- pause guard -------------------------------------------------------------


@pytest.mark.parametrize("statuses", [None, [], ["answered", "unavailable", "withdrawn"]])
def test_pause_guard_refuses(run_dir, statuses):
    workspace.write_yaml(run_dir / "run.yaml", state("collecting"))
    if statuses is not None:
        put_requests(run_dir, *statuses)
    with pytest.raises(outcomes.IllegalTransition) as exc:
        runstate.apply(run_dir, "pause")
    assert exc.value.issues[0]["rule"] == "pause_guard"
    assert runstate.status_of(run_dir) == "collecting"


@pytest.mark.parametrize("statuses", [["drafted"], ["sent"], ["answered", "sent"]])
def test_pause_guard_allows(run_dir, statuses):
    workspace.write_yaml(run_dir / "run.yaml", state("collecting"))
    put_requests(run_dir, *statuses)
    assert runstate.apply(run_dir, "pause")["status"] == "awaiting_data"


# --- confirm / route ---------------------------------------------------------


def test_confirm_defaults(run_dir, capsys):
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", capsys=capsys)
    assert code == 0
    saved = workspace.read_yaml(run_dir / "run.yaml")
    assert saved == env["data"]
    assert saved["n"] == 50000 and 0 <= saved["seed"] < 2**63 and saved["route_overrides"] == {}
    assert saved["status"] == "collecting" and saved["scenario_id"] == RUN_ID
    assert validate_document("run", saved) == []


def test_confirm_explicit_n_and_seed(run_dir, capsys):
    code, env = rqh("run", "confirm", RUN_ID, "--route", "accuracy", "--n", "1000", "--seed", "42", capsys=capsys)
    assert code == 0 and (env["data"]["n"], env["data"]["seed"], env["data"]["route"]) == (1000, 42, "accuracy")


def test_confirm_random_seed_differs(run_dir, ws):
    seeds = set()
    for i in range(2):
        d = ws / "runs" / f"run-{i}"
        d.mkdir()
        shutil.copy(SAMPLE, d / "scenario.yaml")
        assert cli.main(["run", "confirm", f"run-{i}", "--route", "yolo"]) == 0
        seeds.add(workspace.read_yaml(d / "run.yaml")["seed"])
    assert len(seeds) == 2


def test_confirm_idempotent_same_route(run_dir):
    cli.main(["run", "confirm", RUN_ID, "--route", "yolo"])
    before = (run_dir / "run.yaml").read_bytes()
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo"]) == 0
    assert (run_dir / "run.yaml").read_bytes() == before


def test_confirm_other_route_while_collecting_is_exit_3(run_dir):
    cli.main(["run", "confirm", RUN_ID, "--route", "yolo"])
    before = (run_dir / "run.yaml").read_bytes()
    assert cli.main(["run", "confirm", RUN_ID, "--route", "accuracy"]) == 3
    assert (run_dir / "run.yaml").read_bytes() == before


def test_confirm_after_rescope_keeps_n_and_seed_unless_given(run_dir):
    cli.main(["run", "confirm", RUN_ID, "--route", "yolo", "--n", "777", "--seed", "9"])
    cli.main(["run", "rescope", RUN_ID])
    assert cli.main(["run", "confirm", RUN_ID, "--route", "accuracy"]) == 0
    saved = workspace.read_yaml(run_dir / "run.yaml")
    assert (saved["n"], saved["seed"], saved["route"], saved["status"]) == (777, 9, "accuracy", "collecting")
    assert cli.main(["run", "rescope", RUN_ID]) == 0
    assert cli.main(["run", "confirm", RUN_ID, "--route", "accuracy", "--n", "5", "--seed", "1"]) == 0
    saved = workspace.read_yaml(run_dir / "run.yaml")
    assert (saved["n"], saved["seed"]) == (5, 1)


@pytest.mark.parametrize("edit", [b"edited", b"not: [valid"], ids=["valid", "invalid"])
def test_a_write_after_validation_never_reaches_run_yaml(run_dir, monkeypatch, edit):
    """Confirm records the scenario it validated, never a second read of scenario.yaml."""
    from rqharness.commands import run as run_command
    validated = (run_dir / "scenario.yaml").read_bytes()
    edited = validated.replace(RUN_ID.encode(), b"edited-scenario") if edit == b"edited" else edit
    real_validate = run_command.validate_run

    def write_after_validation(run):
        report = real_validate(run)
        (run_dir / "scenario.yaml").write_bytes(edited)
        return report

    monkeypatch.setattr(run_command, "validate_run", write_after_validation)
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo"]) == 0
    assert (run_dir / "scenario.yaml").read_bytes() == edited
    assert workspace.read_yaml(run_dir / "run.yaml")["scenario_id"] == RUN_ID


def test_confirm_reads_and_parses_the_scenario_once(run_dir, document_io):
    """One read and one parse of scenario.yaml per `rqh run confirm`."""
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo"]) == 0
    assert (document_io.reads["scenario.yaml"], document_io.parses["scenario.yaml"]) == (1, 1)


def test_confirm_requires_valid_scenario(run_dir, capsys):
    (run_dir / "scenario.yaml").write_text("title: x\n")
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", capsys=capsys)
    assert code == 1 and env["issues"] and all(i["path"].startswith("scenario") for i in env["issues"])
    assert not (run_dir / "run.yaml").exists()


def test_confirm_missing_scenario_is_exit_1(run_dir):
    (run_dir / "scenario.yaml").unlink()
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo"]) == 1


def test_missing_run_is_exit_5(ws):
    cli.main(["init"])
    for argv in (["confirm", "nope", "--route", "yolo"], ["pause", "nope"], ["route", "nope", "frequency.lef", "yolo"]):
        assert cli.main(["run", *argv]) == 5


def test_route_override(run_dir, capsys):
    cli.main(["run", "confirm", RUN_ID, "--route", "yolo"])
    code, env = rqh("run", "route", RUN_ID, "primary_loss.response", "accuracy", capsys=capsys)
    assert code == 0 and env["data"]["route_overrides"] == {"primary_loss.response": "accuracy"}
    assert workspace.read_yaml(run_dir / "run.yaml")["route_overrides"] == {"primary_loss.response": "accuracy"}
    assert cli.main(["run", "route", RUN_ID, "primary_loss.response", "yolo"]) == 0
    assert workspace.read_yaml(run_dir / "run.yaml")["route_overrides"] == {"primary_loss.response": "yolo"}


def test_route_unknown_path_exit_1(run_dir):
    cli.main(["run", "confirm", RUN_ID, "--route", "yolo"])
    assert cli.main(["run", "route", RUN_ID, "frequency.bogus", "yolo"]) == 1


def test_route_allowed_when_awaiting_data(run_dir):
    workspace.write_yaml(run_dir / "run.yaml", state("awaiting_data"))
    assert cli.main(["run", "route", RUN_ID, "frequency.lef", "accuracy"]) == 0


@pytest.mark.parametrize("frm", ["scoping", "finalized"])
def test_route_refused_outside_collecting(run_dir, frm):
    workspace.write_yaml(run_dir / "run.yaml", state(frm))
    before = (run_dir / "run.yaml").read_bytes()
    assert cli.main(["run", "route", RUN_ID, "frequency.lef", "accuracy"]) == 3
    assert (run_dir / "run.yaml").read_bytes() == before


def test_route_without_run_yaml_exit_3(run_dir):
    assert cli.main(["run", "route", RUN_ID, "frequency.lef", "accuracy"]) == 3


@pytest.mark.parametrize("frm", [None, "scoping", "finalized"])
def test_route_refusal_envelope_is_pinned(run_dir, frm, capsys):
    if frm:
        workspace.write_yaml(run_dir / "run.yaml", state(frm))
    code, env = rqh("run", "route", RUN_ID, "frequency.lef", "accuracy", capsys=capsys)
    assert code == 3 and env["issues"] == [{
        "path": "run.status", "rule": "illegal_transition",
        "message": f"cannot route an estimate while the run is {frm or 'scoping'}"}]
    assert (run_dir / "run.yaml").exists() == bool(frm)


# --- runstate.update / runstate.can -----------------------------------------


def test_write_state_is_private():
    assert not hasattr(runstate, "write_state")


def test_update_rejects_a_status_key(run_dir):
    workspace.write_yaml(run_dir / "run.yaml", state("collecting"))
    before = (run_dir / "run.yaml").read_bytes()
    with pytest.raises(ValueError, match="status"):
        runstate.update(run_dir, allowed=("collecting",), action="edit", status="finalized")
    assert (run_dir / "run.yaml").read_bytes() == before


@pytest.mark.parametrize("frm", STATUSES)
def test_update_keeps_status_inside_allowed(run_dir, frm, monkeypatch):
    workspace.write_yaml(run_dir / "run.yaml", state(frm))
    monkeypatch.setattr(workspace, "utc_now", lambda: "2030-05-06T07:08:09Z")
    saved = runstate.update(run_dir, allowed=(frm,), action="edit", n=123)
    assert saved == state(frm, n=123, updated_at="2030-05-06T07:08:09Z") == workspace.read_yaml(run_dir / "run.yaml")


@pytest.mark.parametrize("frm", [None, *STATUSES])
def test_update_refuses_outside_allowed_with_exit_3(run_dir, frm):
    if frm:
        workspace.write_yaml(run_dir / "run.yaml", state(frm))
    others = tuple(s for s in STATUSES if s != (frm or "scoping"))
    before = snapshot(run_dir)
    with pytest.raises(outcomes.IllegalTransition) as exc:
        runstate.update(run_dir, allowed=others, action="tweak the seed", seed=1)
    assert exc.value.issues == [outcomes.issue(
        "run.status", "illegal_transition", f"cannot tweak the seed while the run is {frm or 'scoping'}")]
    assert snapshot(run_dir) == before


@pytest.mark.parametrize("frm,trigger", list(itertools.product([None, *STATUSES], TRIGGERS)))
@pytest.mark.parametrize("open_request", [False, True])
def test_can_and_check_agree_with_apply(run_dir, frm, trigger, open_request):
    if frm:
        workspace.write_yaml(run_dir / "run.yaml", state(frm))
    if open_request:
        put_requests(run_dir, "sent")
    before = snapshot(run_dir)
    allowed = runstate.can(run_dir, trigger)
    try:
        runstate.check(run_dir, trigger)
        checked = None
    except outcomes.IllegalTransition as exc:
        checked = exc.issues
    assert snapshot(run_dir) == before  # neither can() nor check() writes
    try:
        runstate.apply(run_dir, trigger, **({"scenario_id": RUN_ID, "route": "yolo", "n": 50000, "seed": 3}
                                            if trigger == "confirm" else {}))
        refused = None
    except outcomes.IllegalTransition as exc:
        refused = exc.issues
    assert allowed is (refused is None)
    assert checked == refused  # one refusal, word for word


def test_unknown_trigger_is_a_programming_error_not_a_refusal(run_dir):
    workspace.write_yaml(run_dir / "run.yaml", state("awaiting_data"))
    with pytest.raises(KeyError):
        runstate.can(run_dir, "auto-resume")
    with pytest.raises(KeyError):
        runstate.apply(run_dir, "auto-resume")


def test_no_module_outside_runstate_reads_the_status_table():
    src = Path(runstate.__file__).parent
    offenders = [str(p.relative_to(src)) for p in src.rglob("*.py") if p.name != "runstate.py"
                 and re.search(r"runstate\.(TRANSITIONS|_?write_state)|status_of\([^)]*\)\s*[=!]=",
                               p.read_text(encoding="utf-8"))]
    assert offenders == []


def test_route_keeps_status_and_other_fields(run_dir, monkeypatch):
    workspace.write_yaml(run_dir / "run.yaml", state("awaiting_data", route_overrides={"frequency.lef": "yolo"}))
    monkeypatch.setattr(workspace, "utc_now", lambda: "2030-05-06T07:08:09Z")
    assert cli.main(["run", "route", RUN_ID, "primary_loss.response", "accuracy"]) == 0
    saved = workspace.read_yaml(run_dir / "run.yaml")
    assert saved == state("awaiting_data", updated_at="2030-05-06T07:08:09Z", route_overrides={
        "frequency.lef": "yolo", "primary_loss.response": "accuracy"})


# --- pre-release audit (F-C5, F-B11) ------------------------------------------


@pytest.mark.parametrize("flags", [["--n", "1234"], ["--seed", "8"], ["--n", "1234", "--seed", "8"]])
def test_confirm_with_other_n_or_seed_on_a_confirmed_run_is_exit_3(run_dir, flags, capsys):
    """F-C5: the flags are never ignored; the refusal names the ways to change them."""
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo", "--n", "500", "--seed", "7"]) == 0
    before = (run_dir / "run.yaml").read_bytes()
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", *flags, capsys=capsys)
    assert code == 3 and env["issues"][0]["path"] == "run.status"
    assert "rqh run rescope" in env["issues"][0]["message"]
    assert (run_dir / "run.yaml").read_bytes() == before
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", "--n", "500", "--seed", "7", capsys=capsys)
    assert code == 0 and (run_dir / "run.yaml").read_bytes() == before  # the stored values are a repeat


BOMB = b"a: &a [x, x, x, x, x, x, x, x, x]\n" + b"".join(
    f"{c}: &{c} [{', '.join(['*' + p] * 9)}]\n".encode() for p, c in zip("abcdefgh", "bcdefghi"))


def test_parse_yaml_refuses_aliases_before_expanding_them():
    """F-B11: a billion-laughs document is a YAML error, not 9**9 nodes."""
    with pytest.raises(yaml.YAMLError, match="alias"):
        workspace.parse_yaml(BOMB)
    assert workspace.parse_yaml(b"a: &anchor 1\nb: 2\n") == {"a": 1, "b": 2}  # an anchor alone is harmless


def test_write_yaml_never_writes_an_alias(tmp_path):
    """F-B11: a value shared by two keys (an answer and its candidate) is written twice, so it reads back."""
    shared = {"min": 1, "mode": 2, "max": 3, "unit": "USD"}
    workspace.write_yaml(tmp_path / "doc.yaml", {"answer": shared, "candidate": shared})
    assert b"&" not in (tmp_path / "doc.yaml").read_bytes()
    assert workspace.read_yaml(tmp_path / "doc.yaml") == {"answer": shared, "candidate": shared}


def test_an_alias_in_a_library_entry_is_an_issue_not_a_hang(ws, capsys):
    """F-B11: a hostile entry in a shared library is reported by `rqh library validate`."""
    assert cli.main(["init"]) == 0
    (ws / "library" / "bomb.yaml").write_bytes(BOMB)
    code, env = rqh("library", "validate", capsys=capsys)
    assert code == 1 and any(i["rule"] == "yaml" and "alias" in i["message"] for i in env["issues"])


def test_run_yaml_with_an_alias_is_exit_1(run_dir, capsys):
    """F-B11: run.yaml is parsed the same way, and a refusal is an envelope, not a traceback."""
    (run_dir / "run.yaml").write_bytes(BOMB)
    code, env = rqh("status", RUN_ID, capsys=capsys)
    assert code == 1 and env["issues"][0]["path"] == "run.document" and "alias" in env["issues"][0]["message"]


def test_shipped_yaml_uses_no_aliases():
    """F-B11: refusing aliases costs nothing: no shipped document uses one."""
    package = Path(workspace.__file__).parent
    shipped = sorted(package.rglob("*.yaml")) + sorted(package.rglob("*.yml"))
    assert shipped
    for path in shipped:
        workspace.parse_yaml(path.read_bytes())
