"""Slice 9: requests, candidates and the next step (AC14, AC15, AC34)."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from rqharness import chain, cli, finalize, requests as rq, runstate, workspace
from rqharness.outcomes import NotFound, Rejected

SAMPLE = Path(__file__).parent.parent / "validate" / "fixtures" / "sample-run"
RUN_ID = "credential-phishing-bec"
VALUE = {"min": 10000, "mode": 30000, "max": 80000, "unit": "USD"}
STATUSES = ("drafted", "sent", "answered", "unavailable", "withdrawn")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    return tmp_path / ".riskquant"


@pytest.fixture
def run_dir(ws):
    assert cli.main(["init"]) == 0
    d = ws / "runs" / RUN_ID
    d.mkdir(parents=True)
    for name in ("scenario.yaml", "inputs.yaml"):
        shutil.copy(SAMPLE / name, d / name)
    assert cli.main(["run", "confirm", RUN_ID, "--route", "accuracy", "--n", "2000", "--seed", "7"]) == 0
    return d


def run_of(run_dir: Path) -> workspace.Run:
    """The Run a command would resolve for this directory."""
    return cli.resolve_run(str(run_dir))


def add_req(run_dir, parameter="primary_loss.response", role="IR lead", person=None):
    return rq.add_request(run_dir, parameter_path=parameter, ask="Typical response cost?",
                          owner_role=role, person=person, draft_message="Hi, could you estimate this?")


def add_cand(run_dir, kind="measured", origin="connector:siem", link=None, parameter="primary_loss.response"):
    return rq.add_candidate(run_dir, parameter_path=parameter, value=VALUE,
                            evidence_kind=kind, origin=origin, link=link)


def read(run_dir, name):
    return yaml.safe_load((run_dir / name).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- AC14 --------------------------------------------------------------------

PATHS = {"drafted": [], "sent": ["sent"], "answered": ["sent", "answered"],
         "unavailable": ["sent", "unavailable"], "withdrawn": ["withdrawn"]}


@pytest.mark.parametrize("src,dst", [(a, b) for a in STATUSES for b in STATUSES if a != b])
def test_request_and_candidate_transitions(run_dir, src, dst):
    rid = add_req(run_dir).item["id"]
    for step in PATHS[src]:
        rq.transition_request(run_dir, rid, step, answer={"note": "ok"} if step == "answered" else None)
    before = digest(run_dir / "requests.yaml")
    code = cli.main(["requests", "update", RUN_ID, rid, "--status", dst, *(["--note", "n"] if dst == "answered" else [])])
    if dst in rq.REQUEST_TRANSITIONS.get(src, set()):
        assert code == 0
        assert next(r for r in read(run_dir, "requests.yaml")["requests"])["status"] == dst
    else:
        assert code == 3
        assert digest(run_dir / "requests.yaml") == before


@pytest.mark.parametrize("src", ["pending", "confirmed", "rejected"])
@pytest.mark.parametrize("action", ["confirm", "reject"])
def test_candidate_transitions(run_dir, src, action):
    cid = add_cand(run_dir).item["id"]
    if src == "confirmed":
        rq.confirm_candidate(run_of(run_dir), cid)
    elif src == "rejected":
        rq.reject_candidate(run_dir, cid)
    before = digest(run_dir / "requests.yaml")
    code = cli.main(["candidates", action, RUN_ID, cid])
    legal = src == "pending" or (src, action) in (("confirmed", "confirm"), ("rejected", "reject"))
    assert code == (0 if legal else 3)
    if not legal:
        assert digest(run_dir / "requests.yaml") == before


def test_add_request_duplicate(run_dir):
    first = add_req(run_dir)
    assert isinstance(first, rq.Added) and first.item["id"] == "req-1" and first.item["status"] == "drafted"
    assert isinstance(add_req(run_dir), rq.Duplicate)
    assert add_req(run_dir, role="CFO").item["id"] == "req-2"
    assert add_req(run_dir, person="Ada").item["id"] == "req-3"
    assert len(rq.open_requests(run_dir)) == 3


def test_add_request_cli_duplicate_exit_0(run_dir, capsys):
    args = ["requests", "add", RUN_ID, "--parameter", "primary_loss.response", "--owner-role", "IR lead",
            "--ask", "Cost?", "--draft", "Hello there", "--json"]
    assert cli.main(args) == 0
    capsys.readouterr()
    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out)["data"]["result"] == "duplicate"


def test_add_request_rejects_unknown_parameter(run_dir):
    with pytest.raises(Rejected):
        add_req(run_dir, parameter="primary_loss.bogus")
    assert not (run_dir / "requests.yaml").exists()


def test_last_close_leaves_awaiting_data(run_dir):
    a = add_req(run_dir).item["id"]
    b = add_req(run_dir, role="CFO").item["id"]
    assert cli.main(["run", "pause", RUN_ID]) == 0
    rq.transition_request(run_dir, a, "sent")
    rq.transition_request(run_dir, a, "unavailable")
    assert runstate.status_of(run_dir) == "awaiting_data"
    rq.transition_request(run_dir, b, "withdrawn")
    assert runstate.status_of(run_dir) == "collecting"


@pytest.mark.parametrize("status", ["collecting", "finalized"])
def test_last_close_outside_awaiting_data_leaves_run_yaml_alone(run_dir, status):
    rid = add_req(run_dir).item["id"]
    if status == "finalized":
        runstate.apply(run_dir, "finalize")
    before = (run_dir / "run.yaml").read_bytes()
    assert rq.transition_request(run_dir, rid, "withdrawn").changed
    assert (run_dir / "run.yaml").read_bytes() == before


def test_answer_with_value_creates_pending_candidate(run_dir):
    rid = add_req(run_dir).item["id"]
    rq.transition_request(run_dir, rid, "sent")
    with pytest.raises(Rejected):
        rq.transition_request(run_dir, rid, "answered", answer={"value": VALUE})
    res = rq.transition_request(run_dir, rid, "answered",
                                answer={"value": VALUE, "evidence_kind": "judgement", "note": "gut"})
    assert isinstance(res, rq.Updated)
    cand = rq.pending_candidates(run_dir)[0]
    assert cand["origin"] == f"request:{rid}" and cand["evidence_kind"] == "judgement"
    assert cand["status"] == "pending"


def test_status_lists_open_items(run_dir, capsys):
    add_req(run_dir)
    add_cand(run_dir)
    capsys.readouterr()
    assert cli.main(["status", RUN_ID, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [r["id"] for r in data["open_requests"]] == ["req-1"]
    assert [c["id"] for c in data["pending_candidates"]] == ["cand-1"]
    assert "primary_loss.replacement" in data["fallback_parameters"]
    assert "frequency.tef" not in data["fallback_parameters"]
    assert data["scenario_id"] == RUN_ID and data["n"] == 2000 and data["seed"] == 7


# --- AC15 --------------------------------------------------------------------


def test_candidate_never_in_inputs(run_dir):
    before = digest(run_dir / "inputs.yaml")
    add_cand(run_dir, link="https://siem.example/q/1")
    rid = add_req(run_dir).item["id"]
    rq.transition_request(run_dir, rid, "sent")
    rq.transition_request(run_dir, rid, "answered", answer={"value": VALUE, "evidence_kind": "judgement"})
    assert digest(run_dir / "inputs.yaml") == before
    rq.reject_candidate(run_dir, "cand-1")
    assert digest(run_dir / "inputs.yaml") == before


def test_candidate_dedup(run_dir):
    assert isinstance(add_cand(run_dir, link="https://a.example/1"), rq.Added)
    assert isinstance(add_cand(run_dir, origin="connector:other", link="https://a.example/1"), rq.Duplicate)
    assert isinstance(add_cand(run_dir), rq.Added)
    assert isinstance(add_cand(run_dir), rq.Duplicate)


@pytest.mark.parametrize("kind,tier,src_kind", [("measured", "internal_data", "internal_system"),
                                                ("judgement", "sme_estimate", "person")])
def test_confirm_writes_value_and_source(run_dir, kind, tier, src_kind):
    cid = add_cand(run_dir, kind=kind, link="https://siem.example/q/1").item["id"]
    assert isinstance(rq.confirm_candidate(run_of(run_dir), cid), rq.Confirmed)
    inputs = read(run_dir, "inputs.yaml")
    est = inputs["parameters"]["primary_loss"]["response"]
    assert {k: est[k] for k in ("min", "mode", "max", "unit")} == VALUE
    assert est["label"] == "Incident response per event"
    assert est["provenance"] == {"tier": tier, "source_ids": [cid]}
    src = next(s for s in inputs["sources"] if s["id"] == cid)
    assert src["kind"] == src_kind and src["url"] == "https://siem.example/q/1"
    assert cli.main(["validate", str(run_dir)]) == 0
    assert read(run_dir, "requests.yaml")["candidates"][0]["status"] == "confirmed"


def test_confirm_request_origin_uses_person_source(run_dir):
    rid = add_req(run_dir).item["id"]
    rq.transition_request(run_dir, rid, "sent")
    rq.transition_request(run_dir, rid, "answered", answer={"value": VALUE, "evidence_kind": "measured"})
    rq.confirm_candidate(run_of(run_dir), "cand-1")
    src = next(s for s in read(run_dir, "inputs.yaml")["sources"] if s["id"] == "cand-1")
    assert src["kind"] == "person" and src["owner_role"] == "IR lead" and "url" not in src
    assert src["title"] == f"Answer to {rid} from IR lead"


def test_confirm_crash_between_writes_is_safe(run_dir, monkeypatch):
    cid = add_cand(run_dir).item["id"]
    real = workspace.write_yaml

    def boom(path, data):
        if Path(path).name == "requests.yaml":
            raise OSError("crash")
        real(path, data)

    monkeypatch.setattr(workspace, "write_yaml", boom)
    with pytest.raises(OSError):
        rq.confirm_candidate(run_of(run_dir), cid)
    monkeypatch.setattr(workspace, "write_yaml", real)
    after_crash = digest(run_dir / "inputs.yaml")
    assert isinstance(rq.confirm_candidate(run_of(run_dir), cid), rq.Confirmed)
    assert digest(run_dir / "inputs.yaml") == after_crash
    assert read(run_dir, "requests.yaml")["candidates"][0]["status"] == "confirmed"
    assert isinstance(rq.confirm_candidate(run_of(run_dir), cid), rq.Confirmed)


def test_confirm_rejected_when_estimate_absent_and_not_found(run_dir):
    cid = add_cand(run_dir, parameter="primary_loss.reputation").item["id"]
    before = digest(run_dir / "inputs.yaml")
    with pytest.raises(Rejected):
        rq.confirm_candidate(run_of(run_dir), cid)
    assert digest(run_dir / "inputs.yaml") == before
    assert cli.main(["candidates", "confirm", RUN_ID, cid]) == 1
    assert cli.main(["candidates", "confirm", RUN_ID, "cand-99"]) == 5
    with pytest.raises(NotFound):
        rq.confirm_candidate(run_of(run_dir), "cand-99")


# --- AC34 --------------------------------------------------------------------


def status_json(capsys, ref=RUN_ID):
    capsys.readouterr()
    code = cli.main(["status", ref, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_next_skill_scoping_without_run_yaml(ws, capsys):
    assert cli.main(["init"]) == 0
    d = ws / "runs" / RUN_ID
    d.mkdir(parents=True)
    code, env = status_json(capsys)
    assert code == 0 and env["data"]["next_skill"] == "scope-scenario" and env["data"]["status"] == "scoping"
    shutil.copy(SAMPLE / "scenario.yaml", d / "scenario.yaml")
    assert status_json(capsys)[1]["data"]["next_skill"] == "scope-scenario"


def test_next_skill_per_state(run_dir, capsys):
    d = run_dir
    data = status_json(capsys)[1]["data"]
    assert (data["next_skill"], data["waiting_on"], data["latest_version"]) == ("simulate", [], None)
    assert data["reason"]

    cid = add_cand(d).item["id"]
    assert status_json(capsys)[1]["data"]["next_skill"] == "collect-data"
    rq.reject_candidate(d, cid)
    assert status_json(capsys)[1]["data"]["next_skill"] == "simulate"

    good = (d / "inputs.yaml").read_text(encoding="utf-8")
    (d / "inputs.yaml").write_text(good.replace("min: 150", "min: 1500"), encoding="utf-8")
    assert status_json(capsys)[1]["data"]["next_skill"] == "collect-data"
    (d / "inputs.yaml").unlink()
    assert status_json(capsys)[1]["data"]["next_skill"] == "collect-data"
    (d / "inputs.yaml").write_text(good, encoding="utf-8")

    r1 = add_req(d).item["id"]
    r2 = add_req(d, role="CFO").item["id"]
    assert cli.main(["run", "pause", RUN_ID]) == 0
    data = status_json(capsys)[1]["data"]
    assert data["next_skill"] is None and data["waiting_on"] == [r1, r2]
    assert cli.main(["run", "resume", RUN_ID]) == 0

    assert finalize.finalize(run_of(d), n=500).version == 1
    data = status_json(capsys)[1]["data"]
    assert (data["next_skill"], data["latest_version"], data["status"]) == ("report", 1, "finalized")
    (d / "v1" / "report.html").write_text("<html></html>", encoding="utf-8")
    data = status_json(capsys)[1]["data"]
    assert data["next_skill"] is None and data["latest_version"] == 1 and "reopen" in data["reason"]


def test_missing_workspace_exit_5(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    code, env = status_json(capsys, "nope")
    assert code == 5 and not env["ok"]
    with pytest.raises(NotFound):
        ws = tmp_path / ".riskquant"
        chain.next_step(workspace.Run(ws, ws / "runs" / "nope"))


def test_status_writes_nothing(run_dir, capsys):
    add_req(run_dir)

    def snapshot():
        return {str(p): (digest(p), p.stat().st_mtime_ns) for p in run_dir.parents[1].rglob("*") if p.is_file()}

    before = snapshot()
    for argv in (["status", RUN_ID], ["status", RUN_ID, "--json"]):
        assert cli.main(argv) == 0
    assert snapshot() == before


def test_status_routes_malformed_inputs_to_collect_data_with_an_envelope(run_dir, capsys):
    (run_dir / "inputs.yaml").write_text("parameters: {frequency: [unclosed\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["status", RUN_ID, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["next_skill"] == "collect-data" and data["fallback_parameters"] == []


def test_confirm_rejects_malformed_inputs_without_a_traceback(run_dir):
    add_cand(run_dir)
    (run_dir / "inputs.yaml").write_text("parameters: {frequency: [unclosed\n", encoding="utf-8")
    with pytest.raises(Rejected) as exc:
        rq.confirm_candidate(run_of(run_dir), "cand-1")
    assert exc.value.issues[0]["rule"] == "yaml"


def test_add_reads_ask_and_draft_files_so_shell_metacharacters_stay_text(run_dir, capsys):
    ask = run_dir / "request-ask.txt"
    draft = run_dir / "request-draft.txt"
    ask.write_text("Cost of `whoami` incidents, $(date) style", encoding="utf-8")
    draft.write_text("Hi -- could you share $(cat secrets)?", encoding="utf-8")
    capsys.readouterr()
    code = cli.main(["requests", "add", RUN_ID, "--parameter", "primary_loss.response", "--owner-role", "IR lead",
                     "--ask-file", str(ask), "--draft-file", str(draft), "--json"])
    assert code == 0
    item = json.loads(capsys.readouterr().out)["data"]["request"]
    assert item["ask"] == "Cost of `whoami` incidents, $(date) style"
    assert item["draft_message"] == "Hi -- could you share $(cat secrets)?"



@pytest.mark.parametrize("where", ["missing", "outside"])
def test_ask_file_must_exist_inside_the_run_directory(where, run_dir, tmp_path, capsys):
    target = run_dir / "nope.txt" if where == "missing" else tmp_path / "outside.txt"
    if where == "outside":
        target.write_text("private text", encoding="utf-8")
    capsys.readouterr()
    code = cli.main(["requests", "add", RUN_ID, "--parameter", "primary_loss.response", "--owner-role", "IR lead",
                     "--ask-file", str(target), "--draft", "Hi", "--json"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["issues"][0]["path"] == "argv.ask-file"
    assert rq.open_requests(run_dir) == []  # nothing was stored, not even the path as text


# --- one request file keeps every connector-derived value off the command line ---

HOSTILE_NAME = """Dana O'Brien $(rm -rf ~) `id`; echo pwned && "quoted" \\ end"""
HOSTILE_ROLE = "IR lead'; curl x | sh #"


def add_with_request_file(path, *extra):
    return cli.main(["requests", "add", RUN_ID, "--parameter", "primary_loss.response",
                     "--request-file", str(path), *extra, "--json"])


@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_request_file_stores_role_person_ask_and_draft_verbatim(suffix, run_dir, capsys):
    fields = {"owner_role": HOSTILE_ROLE, "person": HOSTILE_NAME,
              "ask": "Cost of `whoami` incidents; $(date)", "draft": "Hi \"Dana\" && thanks"}
    path = run_dir / f"request-primary_loss.response{suffix}"
    path.write_text(json.dumps(fields) if suffix == ".json" else yaml.safe_dump(fields), encoding="utf-8")
    capsys.readouterr()
    assert add_with_request_file(path, "--due", "2026-12-01") == 0
    item = json.loads(capsys.readouterr().out)["data"]["request"]
    assert item["target"] == {"owner_role": HOSTILE_ROLE, "person": HOSTILE_NAME}
    assert item["ask"] == fields["ask"] and item["draft_message"] == fields["draft"]
    assert item["due_at"] == "2026-12-01"
    stored = rq.load(run_dir)["requests"][0]
    assert stored["target"]["person"] == HOSTILE_NAME  # survives the requests.yaml round trip


def test_request_file_in_the_skills_literal_block_form_needs_no_escaping(run_dir, capsys):
    # the form accuracy.md tells the skill to write: `key: |2-` and the value indented two spaces below it
    block = lambda key, value: f"{key}: |2-\n" + "".join(f"  {line}\n" for line in value.splitlines())
    draft = "  - starts indented, not a list\nHi Dana,\ncould you share: the cost? # not a comment"
    path = run_dir / "request-primary_loss.response.yaml"
    path.write_text(block("owner_role", HOSTILE_ROLE) + block("person", HOSTILE_NAME) + block("ask", "Cost: {per event}")
                    + block("draft", draft), encoding="utf-8")
    capsys.readouterr()
    assert add_with_request_file(path) == 0
    item = json.loads(capsys.readouterr().out)["data"]["request"]
    assert item["target"] == {"owner_role": HOSTILE_ROLE, "person": HOSTILE_NAME}
    assert item["ask"] == "Cost: {per event}" and item["draft_message"] == draft


def test_request_file_person_is_optional(run_dir, capsys):
    path = run_dir / "request.yaml"
    path.write_text("owner_role: IR lead\nask: Cost?\ndraft: Hi\n", encoding="utf-8")
    capsys.readouterr()
    assert add_with_request_file(path) == 0
    assert json.loads(capsys.readouterr().out)["data"]["request"]["target"] == {"owner_role": "IR lead"}


@pytest.mark.parametrize("content, where", [
    ("owner_role: IR lead\nask: Cost?\ndraft: Hi\n", "outside"),
    ("owner_role: IR lead\nask: Cost?\ndraft: Hi\n", "missing"),
    ("owner_role: IR lead\nask: Cost?\ndraft: Hi\nparameter: frequency.tef\n", "inside"),  # unknown key
    ("owner_role: IR lead\nask: Cost?\ndraft: Hi\n1: one\nfoo: two\n", "inside"),  # unknown keys of mixed types
    ("owner_role: IR lead\ndraft: Hi\n", "inside"),  # no ask
    ("owner_role: IR lead\nask: null\ndraft: Hi\n", "inside"),  # an empty ask
    ("- owner_role: IR lead\n", "inside"),  # not a mapping
    ("owner_role: [unclosed\n", "inside"),  # not YAML
])
def test_request_file_refuses_a_bad_file_with_exit_2(content, where, run_dir, tmp_path, capsys):
    path = (tmp_path if where == "outside" else run_dir) / "request.yaml"
    if where != "missing":
        path.write_text(content, encoding="utf-8")
    capsys.readouterr()
    assert add_with_request_file(path) == 2
    assert json.loads(capsys.readouterr().out)["issues"][0]["path"] == "argv.request-file"
    assert rq.open_requests(run_dir) == []


@pytest.mark.parametrize("flag", [["--owner-role", "IR lead"], ["--person", "Dana"], ["--ask", "Cost?"],
                                  ["--draft", "Hi"]])
def test_request_file_excludes_the_per_field_flags(flag, run_dir, capsys):
    path = run_dir / "request.yaml"
    path.write_text("owner_role: IR lead\nask: Cost?\ndraft: Hi\n", encoding="utf-8")
    capsys.readouterr()
    assert add_with_request_file(path, *flag) == 2
    issue = json.loads(capsys.readouterr().out)["issues"][0]
    assert (issue["path"], issue["rule"]) == ("argv", "usage") and flag[0] in issue["message"]
    assert rq.open_requests(run_dir) == []


@pytest.mark.parametrize("drop", ["--owner-role", "--ask", "--draft"])
def test_the_flag_form_still_needs_role_ask_and_draft(drop, run_dir, capsys):
    given = {"--owner-role": "IR lead", "--ask": "Cost?", "--draft": "Hi"}
    del given[drop]
    argv = ["requests", "add", RUN_ID, "--parameter", "primary_loss.response",
            *(x for kv in given.items() for x in kv), "--json"]
    capsys.readouterr()
    assert cli.main(argv) == 2
    assert drop.lstrip("-") in json.loads(capsys.readouterr().out)["issues"][0]["message"]


def test_draft_is_literal_text_and_never_reads_a_file(run_dir, tmp_path, capsys):
    secret = tmp_path / "secret.txt"
    secret.write_text("private file content", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["requests", "add", RUN_ID, "--parameter", "primary_loss.response", "--owner-role", "IR lead",
                     "--ask", "Cost?", "--draft", str(secret), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["request"]["draft_message"] == str(secret)


# --- pre-release audit: finalized runs, interrupted writes and repeats (F-C1, F-C3, F-C5) ---


def sent_request(run_dir, **kw):
    rid = add_req(run_dir, **kw).item["id"]
    rq.transition_request(run_dir, rid, "sent")
    return rid


def files_of(run_dir):
    return {name: digest(run_dir / name) for name in ("run.yaml", "requests.yaml", "inputs.yaml")
            if (run_dir / name).exists()}


VALUE_FLAGS = ["--min", "1", "--mode", "2", "--max", "3", "--unit", "USD", "--evidence", "measured"]
FROZEN_WRITES = {
    "requests add": lambda rid, cid: ["requests", "add", RUN_ID, "--parameter", "primary_loss.replacement",
                                      "--owner-role", "CFO", "--ask", "Cost?", "--draft", "Hi"],
    "requests update sent": lambda rid, cid: ["requests", "update", RUN_ID, "req-2", "--status", "sent"],
    "requests update answered": lambda rid, cid: ["requests", "update", RUN_ID, rid, "--status", "answered",
                                                  *VALUE_FLAGS],
    "requests update unavailable": lambda rid, cid: ["requests", "update", RUN_ID, rid, "--status", "unavailable"],
    "candidates add": lambda rid, cid: ["candidates", "add", RUN_ID, "--parameter", "primary_loss.response",
                                        *VALUE_FLAGS, "--origin", "connector:other"],
    "candidates confirm": lambda rid, cid: ["candidates", "confirm", RUN_ID, cid],
    "candidates reject": lambda rid, cid: ["candidates", "reject", RUN_ID, cid],
}


@pytest.mark.parametrize("write", FROZEN_WRITES)
def test_a_finalized_run_refuses_request_and_candidate_writes_with_exit_3(run_dir, write, capsys):
    """F-C1: a finalized run's requests, candidates and inputs are frozen until `rqh run reopen`."""
    rid = sent_request(run_dir)
    add_req(run_dir, role="CFO")
    cid = add_cand(run_dir).item["id"]
    assert finalize.finalize(run_of(run_dir), n=500).version == 1
    before = files_of(run_dir)
    capsys.readouterr()
    assert cli.main([*FROZEN_WRITES[write](rid, cid), "--json"]) == 3
    issue = json.loads(capsys.readouterr().out)["issues"][0]
    assert issue["path"] == "run.status" and "rqh run reopen" in issue["message"]
    assert files_of(run_dir) == before
    assert cli.main(["run", "reopen", RUN_ID]) == 0
    assert cli.main(FROZEN_WRITES[write](rid, cid)) == 0  # the same write is accepted once reopened


def test_a_finalized_run_still_lets_a_request_be_withdrawn(run_dir):
    rid = sent_request(run_dir)
    assert finalize.finalize(run_of(run_dir), n=500).version == 1
    assert cli.main(["requests", "update", RUN_ID, rid, "--status", "withdrawn"]) == 0
    assert read(run_dir, "requests.yaml")["requests"][0]["status"] == "withdrawn"


def test_a_retried_update_after_an_interrupted_auto_resume_resumes_the_run(run_dir, monkeypatch, capsys):
    """F-C3 (1): the request was saved but the auto-resume never ran; the retry finishes it."""
    rid = sent_request(run_dir)
    assert cli.main(["run", "pause", RUN_ID]) == 0
    real_apply = runstate.apply

    def interrupted(run_dir_, trigger, **changes):
        if trigger == "auto_resume":
            raise KeyboardInterrupt
        return real_apply(run_dir_, trigger, **changes)

    monkeypatch.setattr(runstate, "apply", interrupted)
    with pytest.raises(KeyboardInterrupt):
        rq.transition_request(run_dir, rid, "unavailable")
    monkeypatch.setattr(runstate, "apply", real_apply)
    assert runstate.status_of(run_dir) == "awaiting_data" and rq.open_requests(run_dir) == []
    data = status_json(capsys)[1]["data"]
    assert data["next_skill"] is None and "rqh run resume" in data["reason"]
    assert cli.main(["requests", "update", RUN_ID, rid, "--status", "unavailable"]) == 0
    assert runstate.status_of(run_dir) == "collecting"


def test_status_of_a_finalized_run_without_a_version_names_the_way_out(run_dir, capsys):
    """F-C3 (3): never "Version None"; the run is reopened and finalized again."""
    workspace.write_yaml(run_dir / "run.yaml", {**read(run_dir, "run.yaml"), "status": "finalized"})
    data = status_json(capsys)[1]["data"]
    assert data["next_skill"] is None and data["latest_version"] is None
    assert "None" not in data["reason"] and "rqh run reopen" in data["reason"]


def test_a_second_answer_with_a_different_payload_is_refused_not_dropped(run_dir, capsys):
    """F-C3 (4): an answer is recorded once; a different one is exit 3, the same one a no-op."""
    rid = sent_request(run_dir)
    first = ["requests", "update", RUN_ID, rid, "--status", "answered", "--note", "first"]
    assert cli.main(first) == 0
    before = files_of(run_dir)
    assert cli.main(first) == 0
    assert files_of(run_dir) == before
    for extra in (["--note", "second"], VALUE_FLAGS):
        capsys.readouterr()
        assert cli.main(["requests", "update", RUN_ID, rid, "--status", "answered", *extra, "--json"]) == 3
        assert json.loads(capsys.readouterr().out)["issues"][0]["rule"] == "answer_recorded"
        assert files_of(run_dir) == before
    assert read(run_dir, "requests.yaml")["requests"][0]["answer"]["note"] == "first"
    assert rq.pending_candidates(run_dir) == []


def test_confirming_a_second_candidate_for_a_confirmed_parameter_is_refused(run_dir, capsys):
    """F-C3 (5): the first confirmed candidate never goes stale with an orphan source row."""
    first = add_cand(run_dir).item["id"]
    second = add_cand(run_dir, origin="connector:other").item["id"]
    assert cli.main(["candidates", "confirm", RUN_ID, first]) == 0
    before = files_of(run_dir)
    capsys.readouterr()
    assert cli.main(["candidates", "confirm", RUN_ID, second, "--json"]) == 3
    issue = json.loads(capsys.readouterr().out)["issues"][0]
    assert issue["rule"] == "already_confirmed" and first in issue["message"]
    assert files_of(run_dir) == before
    assert [s["id"] for s in read(run_dir, "inputs.yaml")["sources"] if s["id"].startswith("cand-")] == [first]
    assert cli.main(["candidates", "reject", RUN_ID, second]) == 0  # the way out the message names
    assert cli.main(["candidates", "confirm", RUN_ID, first]) == 0  # a repeat of the first stays a no-op


@pytest.mark.parametrize("text", ["schema_version: '1'\nscenario_id: x\nrequests: []\n",  # no candidates
                                  "requests: [unclosed\n",  # not YAML
                                  "- a list\n"])
def test_status_rejects_a_malformed_requests_file_with_exit_1(run_dir, text, capsys):
    """F-C5: an envelope with issues at requests.*, never a traceback."""
    (run_dir / "requests.yaml").write_text(text, encoding="utf-8")
    code, env = status_json(capsys)
    assert code == 1 and not env["ok"]
    assert env["issues"] and all(i["path"].startswith("requests") for i in env["issues"])


@pytest.mark.parametrize("closed", ["withdrawn", "unavailable", "answered"])
def test_a_closed_request_is_not_a_duplicate_of_a_new_ask(run_dir, closed):
    """F-C5: the duplicate check matches open requests only, so the same owner can be asked again."""
    rid = sent_request(run_dir)
    rq.transition_request(run_dir, rid, closed, answer={"note": "n"} if closed == "answered" else None)
    again = add_req(run_dir)
    assert isinstance(again, rq.Added) and again.item["id"] == "req-2"
    assert isinstance(add_req(run_dir), rq.Duplicate)  # the open one still de-duplicates


# A requests.yaml as 0.1.0 wrote it: the answer's value and its candidate's value share one anchor.
ALIASED_REQUESTS = """schema_version: '1'
scenario_id: credential-phishing-bec
requests:
- id: req-1
  parameter_path: primary_loss.response
  ask: Cost?
  target: {owner_role: IR lead}
  draft_message: Hi
  status: answered
  created_at: '2026-01-01T00:00:00Z'
  answer:
    value: &id001 {min: 1, mode: 2, max: 3, unit: USD}
    received_at: '2026-01-02T00:00:00Z'
- id: req-2
  parameter_path: primary_loss.replacement
  ask: Cost?
  target: {owner_role: CFO}
  draft_message: Hi
  status: sent
  created_at: '2026-01-01T00:00:00Z'
candidates:
- id: cand-1
  parameter_path: primary_loss.response
  value: *id001
  evidence_kind: measured
  origin: request:req-1
  status: pending
  created_at: '2026-01-02T00:00:00Z'
"""
MALFORMED_REQUESTS = ["schema_version: '1'\nscenario_id: x\nrequests: []\n",  # no candidates
                      "requests: [unclosed\n",  # not YAML
                      "- a list\n",
                      ALIASED_REQUESTS]  # a 0.1.0 file with aliases


@pytest.mark.parametrize("text", MALFORMED_REQUESTS)
def test_pause_rejects_a_malformed_requests_file_with_exit_1(run_dir, text, capsys):
    """Review 1: the pause guard reads requests.yaml through the validating, alias-refusing loader."""
    (run_dir / "requests.yaml").write_text(text, encoding="utf-8")
    before = files_of(run_dir)
    capsys.readouterr()
    assert cli.main(["run", "pause", RUN_ID, "--json"]) == 1
    env = json.loads(capsys.readouterr().out)
    assert env["issues"] and all(i["path"].split(".")[0] == "requests" for i in env["issues"])
    assert files_of(run_dir) == before


def test_an_aliased_requests_file_names_the_way_out(run_dir, capsys):
    """Review 10: a 0.1.0 file with aliases is refused with a hint on how to re-save it."""
    (run_dir / "requests.yaml").write_text(ALIASED_REQUESTS, encoding="utf-8")
    code, env = status_json(capsys)
    assert code == 1 and [(i["path"], i["rule"]) for i in env["issues"]] == [("requests.document", "yaml")]
    message = env["issues"][0]["message"]
    assert "*idNNN" in message and "&idNNN" in message



@pytest.mark.parametrize("command, flag, text", [
    (["requests", "add", RUN_ID, "--parameter", "primary_loss.response", "--request-file"], "request-file",
     "owner_role: &r IR lead\nask: *r\ndraft: Hi\n"),
    (["requests", "update", RUN_ID, "req-1", "--status", "sent", "--answer-file"], "answer-file",
     "note: &n hello\nunit: *n\n"),
    (["candidates", "add", RUN_ID, "--parameter", "primary_loss.response", "--candidate-file"], "candidate-file",
     "min: &v 1\nmode: *v\nmax: 3\nunit: USD\nevidence: measured\norigin: connector:siem\n"),
])
def test_an_input_file_with_yaml_aliases_is_refused_with_exit_2(run_dir, command, flag, text, capsys):
    """Review 1: every input file goes through the alias-refusing parser, never yaml.safe_load."""
    add_req(run_dir)
    path = run_dir / "input.yaml"
    path.write_text(text, encoding="utf-8")
    before = files_of(run_dir)
    capsys.readouterr()
    assert cli.main([*command, str(path), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["issues"][0]["path"] == f"argv.{flag}"
    assert files_of(run_dir) == before


def test_a_repeated_answer_with_another_evidence_kind_is_refused_not_dropped(run_dir, capsys):
    """Review 5: the same value with a different evidence kind is exit 3, the identical repeat a no-op."""
    rid = sent_request(run_dir)
    first = ["requests", "update", RUN_ID, rid, "--status", "answered", *VALUE_FLAGS]
    assert cli.main(first) == 0
    before = files_of(run_dir)
    assert cli.main(first) == 0
    assert files_of(run_dir) == before
    judgement = [*VALUE_FLAGS[:-1], "judgement"]
    capsys.readouterr()
    assert cli.main(["requests", "update", RUN_ID, rid, "--status", "answered", *judgement, "--json"]) == 3
    assert json.loads(capsys.readouterr().out)["issues"][0]["rule"] == "answer_recorded"
    assert files_of(run_dir) == before
    assert [c["evidence_kind"] for c in rq.pending_candidates(run_dir)] == ["measured"]


@pytest.mark.parametrize("repeat", [False, True])
def test_an_answer_on_a_request_that_is_not_answered_is_exit_1_whether_or_not_it_repeats(run_dir, repeat, capsys):
    """Review 6: `--status sent --note x` is answer_status on a drafted and on a sent request alike."""
    rid = sent_request(run_dir) if repeat else add_req(run_dir).item["id"]
    before = files_of(run_dir)
    capsys.readouterr()
    assert cli.main(["requests", "update", RUN_ID, rid, "--status", "sent", "--note", "x", "--json"]) == 1
    issue = json.loads(capsys.readouterr().out)["issues"][0]
    assert (issue["path"], issue["rule"]) == (f"requests.{rid}.answer", "answer_status")
    assert files_of(run_dir) == before


def test_a_repeated_request_update_reports_unchanged(run_dir, capsys):
    """The envelope tells a write from a no-op: the identical repeat is `unchanged`, not `updated`."""
    rid = add_req(run_dir).item["id"]
    command = ["requests", "update", RUN_ID, rid, "--status", "sent", "--json"]
    capsys.readouterr()
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out)["data"]["result"] == "updated"
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out)["data"]["result"] == "unchanged"


def test_rejecting_a_rejected_candidate_reports_unchanged(run_dir, capsys):
    cid = add_cand(run_dir).item["id"]
    command = ["candidates", "reject", RUN_ID, cid, "--json"]
    capsys.readouterr()
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out)["data"]["result"] == "updated"
    assert cli.main(command) == 0
    assert json.loads(capsys.readouterr().out)["data"]["result"] == "unchanged"
