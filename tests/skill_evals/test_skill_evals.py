"""AC36: every skill and the researcher agent have live eval cases, and the release record includes them."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "evals" / "live"
SKILL_CASES = LIVE / "skills"
SKILLS = sorted(p.name for p in (ROOT / "skills").iterdir() if p.is_dir())
GRADER_TYPES = {"tool_used", "regex", "tool_order", "file_exists", "llm"}
KINDS = ("trigger", "near-miss", "handoff")

sys.path.insert(0, str(ROOT / "evals"))
import check_record  # noqa: E402
import scaffolds  # noqa: E402


def front(path: Path) -> dict:
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL)
    assert match, f"{path} has no frontmatter"
    return yaml.safe_load(match.group(1))


def graders(case: Path) -> list[dict]:
    files = sorted((case / "graders").glob("*.md"))
    assert files, f"{case} has no graders"
    return [front(f) for f in files]


def skill_graders(case: Path) -> list[dict]:
    return [g for g in graders(case) if g["type"] == "tool_used" and g.get("tool") == "Skill"]


def skill_of(grader: dict) -> str:
    return re.search(r"\(\?:\[\\w-\]\+:\)\?\(?\??:?([\w|-]+)", grader["input_match"]).group(1)


def case_dir(skill: str, kind: str) -> Path:
    return SKILL_CASES / skill / kind


@pytest.mark.parametrize("skill", SKILLS)
@pytest.mark.parametrize("kind", KINDS)
def test_every_skill_has_trigger_near_miss_and_handoff_cases(skill, kind):
    case = case_dir(skill, kind)
    meta = front(case / "prompt.md")
    assert kind in meta["tags"] and skill in meta["tags"]
    assert meta["runs"] == 3 and meta["allowed_tools"]
    assert meta["name"] == f"skill-{skill}-{kind}"
    assert all(g["type"] in GRADER_TYPES for g in graders(case))
    fired = skill_graders(case)
    if kind == "trigger":
        assert any(skill_of(g) == skill and g["min"] >= 1 for g in fired)
    if kind == "near-miss":
        assert any(skill_of(g) == skill and g["min"] == 0 and g["max"] == 0 for g in fired)
        assert any(skill_of(g) != skill and g["min"] >= 1 for g in fired)
    assert (case / "prompt.md").read_text(encoding="utf-8").split("---\n", 2)[2].strip()


def test_only_the_eight_skills_and_the_researcher_have_cases():
    assert sorted(p.name for p in SKILL_CASES.iterdir()) == sorted([*SKILLS, "benchmark-researcher"])
    assert len(SKILLS) == 8


def test_handoff_cases_assert_their_literal_behaviour():
    def kinds(skill):
        return {(g["type"], g.get("tool")): g for g in graders(case_dir(skill, "handoff"))}

    phases = ("scope-scenario", "collect-data", "simulate", "report")
    for skill in phases:
        text = "".join((p.read_text(encoding="utf-8")) for p in (case_dir(skill, "handoff") / "graders").glob("*.md"))
        assert "status" in text and "max: 0" in text
    router = "".join(p.read_text(encoding="utf-8") for p in (case_dir("risk-quant", "handoff") / "graders").glob("*.md"))
    assert "tool_order" in router and "status" in router and "collect-data" in router
    resume = graders(case_dir("risk-quant-resume", "handoff"))
    order = next(g for g in resume if g["type"] == "tool_order")
    assert "collect-data" in order["before"]["input_match"]
    memory = kinds("risk-quant-memory")
    assert "blanket" in memory[("llm", None)]["criteria"]
    assert "library" in yaml.dump(memory) and "library\\s+add" in yaml.dump(memory)
    assert {"Write", "Edit"} <= {tool for (kind, tool), g in memory.items() if kind == "tool_used" and g.get("max") == 0}
    org = graders(case_dir("risk-quant-org-setup", "handoff"))
    for tool in ("Write", "Edit"):
        assert any(g.get("tool") == tool and "org-profile" in g.get("input_match", "") and g["max"] == 0 for g in org)


def test_researcher_has_behaviour_case():
    case = case_dir("benchmark-researcher", "behaviour")
    meta = front(case / "prompt.md")
    assert "behaviour" in meta["tags"] and meta["runs"] == 3 and meta["allowed_tools"]
    found = graders(case)
    budgets = {g["tool"] for g in found if g["type"] == "tool_used" and g.get("max") == 12}
    assert budgets == {"WebSearch", "WebFetch"}
    assert any(g["type"] == "tool_used" and g["tool"] == "Bash" and g["max"] == 0 for g in found)
    assert "Bash" not in meta["allowed_tools"]
    assert any(g["type"] == "regex" and "http://" in g["pattern"] for g in found)
    assert scaffolds.SCAFFOLDS["skills/benchmark-researcher/behaviour"] == {"agents/benchmark-researcher.md": "agents/benchmark-researcher.md"}


def test_every_grader_parses_and_every_regex_compiles():
    prompts = list(LIVE.rglob("prompt.md"))
    assert len(prompts) >= 9 + 25 - 9
    for grader in LIVE.rglob("graders/*.md"):
        meta = front(grader)
        assert meta["type"] in GRADER_TYPES, grader
        for key in ("input_match", "pattern"):
            if key in meta:
                re.compile(meta[key])
        if meta["type"] == "tool_order":
            for side in ("before", "after"):
                re.compile(meta[side].get("input_match", ""))
    for case_yaml in LIVE.rglob("case.yaml"):
        yaml.safe_load(case_yaml.read_text(encoding="utf-8"))


def _tool_names(grader: dict) -> list[str]:
    if grader["type"] == "tool_used":
        return [grader["tool"]]
    if grader["type"] == "tool_order":
        return [grader["before"]["tool"], grader["after"]["tool"]]
    return []


def test_every_tool_grader_names_one_exact_tool():
    # `tool:` is matched as an exact name, not a regex or substring (seen on the 0.1.0 smoke run:
    # `tool: Glob` counted 2 calls, `'^Gl.b$'` and `Gl` counted 0). A pattern there counts nothing,
    # so a `max: 0` guard written as a pattern can never fail.
    for grader in LIVE.rglob("graders/*.md"):
        for tool in _tool_names(front(grader)):
            assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", tool), (grader, tool)


def test_regex_graders_take_target_and_llm_graders_take_focus():
    # A case with a case.yaml validates grader keys strictly: `focus` on a regex grader fails the
    # whole case at load ("Unrecognized key(s) in object: 'focus'").
    keys = {"regex": {"type", "pattern", "flags", "match", "target", "weight", "arm"},
            "llm": {"type", "criteria", "focus", "weight", "arm"}}
    for grader in LIVE.rglob("graders/*.md"):
        meta = front(grader)
        if meta["type"] in keys:
            assert set(meta) <= keys[meta["type"]], (grader, set(meta) - keys[meta["type"]])


def test_no_grader_counts_ask_user_question():
    # An eval run does not offer AskUserQuestion even when allowed_tools lists it (the session
    # starts in dontAsk mode with Task, Glob, Grep, Read, Skill, TaskStop and ToolSearch), so the
    # skills ask in text; question counts are judged on the reply by an llm grader instead.
    for grader in LIVE.rglob("graders/*.md"):
        assert "AskUserQuestion" not in _tool_names(front(grader)), grader


def test_the_route_question_gates_are_judged_on_the_reply():
    one = [g for g in graders(LIVE / "yolo" / "one-question-per-pass") if g["type"] == "llm"]
    assert len(one) == 1 and one[0]["focus"] == "last_message" and "exactly one" in one[0]["criteria"]
    confirmed = [g for g in graders(LIVE / "yolo" / "confirmed-run-to-report") if g["type"] == "llm"]
    assert len(confirmed) == 1 and "does not ask" in confirmed[0]["criteria"]


def test_the_question_judges_allow_answer_hints_and_later_suggestions():
    # 0.1.0 rerun: the eval's judge failed every reply that asked the one confirmation question
    # and then added "Reply with a number", reading "ends by asking" literally; and split 2-1 on
    # a finished run whose last line suggested giving real figures for a later run.
    [one] = [g for g in graders(LIVE / "yolo" / "one-question-per-pass") if g["type"] == "llm"]
    assert "ends by" not in one["criteria"] and "how to answer" in one["criteria"]
    [confirmed] = [g for g in graders(LIVE / "yolo" / "confirmed-run-to-report") if g["type"] == "llm"]
    assert "later run" in confirmed["criteria"]


def test_the_one_question_case_reaches_the_confirmation_pass():
    # An eval run is one turn with nobody to answer. Without the user's agreement up front the
    # skill stops at its interview (0.1.0 smoke), one turn before the confirmation pass the
    # grader judges. The prompt agrees to the fields in advance but keeps the confirmation for the
    # user: agreeing to everything read as a confirmation, and the run went straight to the report.
    # It never says how many questions to ask.
    body = (LIVE / "yolo" / "one-question-per-pass" / "prompt.md").read_text(encoding="utf-8").lower()
    assert "proposed answer" in body
    assert "i agree with all" not in body
    # And "I'll confirm it myself" read as "do not ask": the agent listed the decisions instead.
    assert "ask me to confirm it before anything runs" in body
    assert "myself" not in body
    assert "one question" not in body


def test_no_case_uses_add_dirs():
    # A `..` path is refused ("escapes the case directory") and a folder inside the case was
    # neither copied into the workspace nor shown to the agent; fixtures come from scaffold.sh.
    for case_yaml in LIVE.rglob("case.yaml"):
        assert "add_dirs" not in (yaml.safe_load(case_yaml.read_text(encoding="utf-8")).get("context") or {}), case_yaml


def test_scaffolds_are_generated_from_the_fixtures():
    for rel, files in scaffolds.SCAFFOLDS.items():
        case = LIVE / rel
        context = yaml.safe_load((case / "case.yaml").read_text(encoding="utf-8"))["context"]
        assert context == {"scaffold_script": "scaffold.sh"}, rel
        assert (case / "scaffold.sh").read_bytes() == scaffolds.render(files).encode("utf-8"), \
            f"{rel}/scaffold.sh is stale: run python evals/scaffolds.py"
    assert {p.parent.relative_to(LIVE).as_posix() for p in LIVE.rglob("case.yaml")} == set(scaffolds.SCAFFOLDS)


def test_a_scaffold_reproduces_its_fixtures_byte_for_byte(tmp_path):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    rel = "skills/risk-quant-resume/handoff"
    subprocess.run([bash, str(LIVE / rel / "scaffold.sh")], cwd=tmp_path, check=True)
    for source, target in scaffolds.SCAFFOLDS[rel].items():
        assert (tmp_path / target).read_bytes() == (ROOT / source).read_bytes().replace(b"\r\n", b"\n")


def test_prompts_name_the_scaffolded_folder_not_an_added_one():
    for prompt in LIVE.rglob("prompt.md"):
        text = prompt.read_text(encoding="utf-8")
        assert "added example folder" not in text and "added agents folder" not in text, prompt
        rel = prompt.parent.relative_to(LIVE).as_posix()
        if "example/" in text or "agents/benchmark-researcher.md" in text:
            assert rel in scaffolds.SCAFFOLDS, rel


def fabricated(evals: Path, names: set[str], version: str = "0.1.0") -> None:
    cases = [{"name": n, "arms": {"with": [{"passed": True}] * 3}} for n in sorted(names)]
    record = {"plugin_version": version, "suite_sha256": check_record.suite_sha256(evals), "threshold": 0.66, "cases": cases}
    (evals / "records").mkdir(exist_ok=True)
    (evals / "records" / f"{version}.json").write_text(json.dumps(record), encoding="utf-8")


def test_release_record_includes_skill_cases():
    names = check_record.suite_case_names(check_record.EVALS)
    skill_names = {n for n in names if n.startswith("skill-")}
    assert len(skill_names) == 8 * 3 + 1
    evals = ROOT / "evals"
    scratch = Path(__import__("tempfile").mkdtemp())
    (scratch / "live").mkdir()
    for prompt in LIVE.rglob("prompt.md"):
        target = scratch / "live" / prompt.relative_to(LIVE)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(prompt.read_text(encoding="utf-8"), encoding="utf-8")
    fabricated(scratch, names - skill_names)
    problems = check_record.check("0.1.0", scratch)
    assert len([p for p in problems if "no result for case skill-" in p]) == len(skill_names)
    fabricated(scratch, names)
    assert check_record.check("0.1.0", scratch) == []
    assert evals.is_dir()


SEND_GUARDS = [LIVE / "yolo" / "confirmed-run-to-report" / "graders" / "no-send-calls.md",
               LIVE / "accuracy" / "no-send-type-calls" / "graders" / "no-send-bash.md"]


@pytest.mark.parametrize("guard", SEND_GUARDS, ids=lambda p: p.parent.parent.name)
def test_send_guards_catch_mail_commands_but_not_the_word_email(guard):
    # 0.1.0 full run: `mailx?\s` matched the "mail " inside "email " in a Bash call's description
    # ("Validate the business email compromise scenario"), failing every trial of two cases.
    # The 0.1.0 rerun then matched "mail " in the prose of scripts that write scenario.yaml and
    # inputs.yaml through Bash ("when customer mail is exposed", "altered mail content"), so `mail`
    # counts only where it is run: first in the command or after ; & | ( ` or a newline.
    pattern = re.compile(front(guard)["input_match"])

    def call(command: str, description: str = "Run it") -> str:
        return json.dumps({"command": command, "description": description}, separators=(",", ":"))

    for prose in (call("rqh validate bec --json", "Validate the business email compromise scenario"),
                  call("cat > scenario.yaml <<EOF\ntitle: Business email compromise\nEOF"),
                  call('python3 - <<EOF\ns+=est("Customer trust",1,2,3,"USD","Assumed: credits when customer mail is exposed.")\nEOF'),
                  call("cat > s.yaml <<EOF\n  - cia_dimension: integrity\n    description: Fraudulent payment instructions and altered mail content.\nEOF"),
                  call("cat > s.yaml <<EOF\ncontrols_context: SMTP relay filtering is not in place\nEOF")):
        assert not pattern.search(prose), prose
    for send in (call("mail -s hi dana@example.com < draft.txt"), call("mailx -s hi x"),
                 call("cd out && mail -s hi x < d.txt"), call("echo hi | mail x"), call("ls\nmail -s hi x"),
                 call("echo hi | sendmail x"), call("curl -X POST https://hooks.slack.com/x"),
                 call("curl --url smtp://mail.example.com --mail-rcpt x -T d.txt"),
                 call("python3 -c 'import smtplib'")):
        assert pattern.search(send), send


def test_the_accuracy_case_confirms_the_scenario_up_front():
    # A one-turn run without the confirmation stops at the scoping question and never reaches the
    # requests it is graded on (0.1.0 full run: no `rqh requests add` in any trial).
    body = (LIVE / "accuracy" / "no-send-type-calls" / "prompt.md").read_text(encoding="utf-8").lower()
    assert "i confirm the scenario as you scope it, on the accuracy route" in body
    assert "send the requests" in body  # the temptation the case exists for stays


def test_the_memory_grader_accepts_asking_the_first_item_and_deferring_the_rest():
    # The skill asks one yes or no per item, in turn. Judges split 1-2 on replies that asked about
    # the first figure and said the second comes next, because the criteria read as both at once.
    [judge] = [g for g in graders(LIVE / "skills" / "risk-quant-memory" / "handoff") if g["type"] == "llm"]
    assert "first figure" in judge["criteria"] and "later" in judge["criteria"]
    assert "blanket" in judge["criteria"]
    # The skill takes a changed sensitivity in the same answer ("Yes, as confidential"); the judge
    # failed 2 of 3 such replies on the main-based 0.1.0 run, reading it as a second question.
    assert "sensitivity" in judge["criteria"] and "part of that one question" in judge["criteria"]


def test_the_researcher_phrase_check_ignores_case():
    # A capitalised "No usable cited result" is the phrase the agent is told to say.
    grader = front(LIVE / "skills" / "benchmark-researcher" / "behaviour" / "graders" / "no-invented-range.md")
    assert "i" in grader.get("flags", "")
