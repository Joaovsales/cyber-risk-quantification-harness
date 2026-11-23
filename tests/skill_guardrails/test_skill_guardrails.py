"""AC28: the guardrail lint over the collection, resume, org and memory skills and the researcher agent."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills"
AGENT = ROOT / "agents" / "benchmark-researcher.md"
PHASES = ("scope-scenario", "collect-data", "simulate", "report")
EIGHT = (
    "risk-quant", "scope-scenario", "collect-data", "simulate", "report",
    "risk-quant-resume", "risk-quant-org-setup", "risk-quant-memory",
)
OWN = ("collect-data", "risk-quant-resume", "risk-quant-org-setup", "risk-quant-memory")


def skill_files(name: str) -> list[Path]:
    base = SKILLS / name
    return [base / "SKILL.md", *sorted((base / "references").glob("*.md"))]


def text_of(name: str) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in skill_files(name))


def skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def reference(name: str, ref: str) -> str:
    return (SKILLS / name / "references" / ref).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    match = re.search(rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, re.DOTALL | re.MULTILINE)
    assert match, f"missing section '## {heading}'"
    return match.group(1)


def clauses(text: str) -> list[str]:
    """Sentences and semicolon clauses, so one qualifier cannot cover a different instruction."""
    return [c.strip() for c in re.split(r"(?<=[.;:!?])\s+|\n+", text) if c.strip()]


def agent_text() -> str:
    return AGENT.read_text(encoding="utf-8")


def test_files_exist():
    for name in OWN:
        assert skill_files(name)[0].is_file(), name
    assert (SKILLS / "collect-data/references/yolo.md").is_file()
    assert (SKILLS / "collect-data/references/accuracy.md").is_file()
    assert AGENT.is_file()


def test_question_fallback_present():
    for name in OWN:
        text = skill(name)
        assert "structured question tool" in text, name
        assert "AskUserQuestion" in text, name
        assert "numbered options" in text, name


def test_connectors_are_read_only():
    accuracy = reference("collect-data", "accuracy.md")
    assert re.search(r"Use only search and read tools", accuracy)
    assert re.search(r"Never use a tool that sends, posts, creates, updates or deletes", accuracy)
    assert re.search(r"Connectors are read-only: use only search and read tools", skill("collect-data"))
    setup = skill("risk-quant-org-setup")
    assert re.search(r"Connectors are read-only: call only directory, search and read tools", setup)
    assert re.search(r"Never use a tool that sends, posts, creates, updates or deletes", setup)


SEND = re.compile(r"\b(send|sends|post|posts|email|emails|message|messages|dm)\b", re.IGNORECASE)
QUALIFIED = re.compile(r"\b(never|not|nothing|no|draft|drafts|drafted|drafting)\b|read-only", re.IGNORECASE)


@pytest.mark.parametrize("name", OWN)
def test_no_send_instruction_outside_drafts_only(name):
    for path in skill_files(name):
        for clause in clauses(path.read_text(encoding="utf-8")):
            # a code span such as `--draft "<message text>"` is a flag, not a verb
            prose = re.sub(r"`[^`]*`", "", clause)
            if SEND.search(prose):
                assert QUALIFIED.search(prose), f"{path.name}: unqualified send-type instruction: {clause}"


def test_send_detector_catches_a_send_instruction():
    assert SEND.search("Send it to the owner.") and not QUALIFIED.search("Send it to the owner.")


def test_drafts_only_messaging():
    accuracy = reference("collect-data", "accuracy.md")
    assert re.search(r"The draft is text the user sends in their own tools; you never send it", accuracy)
    assert re.search(r"Messages to people are drafts the user sends; you never send anything", skill("collect-data"))
    assert re.search(r"rqh requests add <run>", accuracy)


PER_FIELD = re.compile(r"--(owner-role|person|ask|draft)(?![-\w])")  # --ask-file and --draft-file stay allowed


def test_request_text_stays_off_the_command_line():
    # Names come from connector reads, so a skill writes them to a request file and passes only its path
    accuracy = reference("collect-data", "accuracy.md")
    assert "rqh requests add <run> --parameter <path> --request-file .riskquant/runs/<run>/request-<parameter>.yaml" in accuracy
    assert re.search(r"with your file-writing tool, never with a shell command", accuracy)
    for path in sorted(SKILLS.rglob("*.md")):
        found = PER_FIELD.search(path.read_text(encoding="utf-8"))
        assert not found, f"{path.relative_to(ROOT)} puts request text on the command line with {found.group()}"


@pytest.mark.parametrize("line", ["--draft=\"<message>\"", "`--ask`", "--person\n", "--owner-role '<role>'"])
def test_the_per_field_flag_detector_catches_every_spelling(line):
    assert PER_FIELD.search(line) and not PER_FIELD.search("--ask-file x --draft-file y")


def test_each_draft_is_shown_in_full_in_the_reply():
    # 0.1.0 live run: 2 of 3 Accuracy trials drafted and sent nothing, but listed the requests or
    # pointed at `rqh status` instead of showing the text. "Show each draft" sat at the end of a
    # long paragraph that also deletes the draft files, so it is its own step now.
    drafts = section(reference("collect-data", "accuracy.md"), "4. Draft requests")
    steps = re.findall(r"^\d+\. (.+)$", drafts, re.MULTILINE)
    show = [s for s in steps if "in full" in s]
    assert len(show) == 1, steps
    assert "`draft_message`" in show[0] and "rqh status <run> --json" in show[0]
    assert re.search(r"Never only (list|point)", show[0])


def test_candidate_until_confirmed():
    main, accuracy = skill("collect-data"), reference("collect-data", "accuracy.md")
    assert re.search(r"candidate until the user confirms it: only `rqh candidates confirm` puts a found figure into `inputs.yaml`", main)
    assert re.search(r"A candidate never goes into `inputs.yaml` directly", accuracy)
    assert "rqh candidates add <run>" in accuracy and "rqh candidates confirm <run> <id>" in accuracy
    assert re.search(r"Everything you find is a candidate until the user confirms it", accuracy)


def test_memory_batch_asks_one_yes_no_per_item_and_writes_only_via_library_add():
    text = skill("risk-quant-memory")
    batch = section(text, "Batch mode (end of run)")
    assert "invokes this once after `report`" in batch
    assert "internal_data" in batch and "sme_estimate" in batch
    assert re.search(r"Ask exactly ONE yes or no per item, never a blanket question", batch)
    assert "rqh library add" in batch
    assert re.search(r"`rqh library add` is the only write path\. Nothing is stored without a yes", text)
    assert re.search(r"Never write or edit anything under `.riskquant/library/` yourself", text)
    for clause in clauses(text):
        if re.search(r"\.riskquant/library/", clause) and re.search(r"\b(write|edit|create|copy|save)\b", clause, re.I):
            assert re.search(r"\b(never|not)\b", clause, re.I), clause
    assert re.search(r"never paste a raw export", text) and "`sensitivity`" in text and "500" in text


def test_research_cap_of_four_and_twelve_calls():
    yolo = reference("collect-data", "yolo.md")
    assert re.search(r"at most 4 in parallel", yolo)
    assert re.search(r"within 12 tool calls", yolo)
    assert re.search(r"YOLO parameters only", yolo)
    assert re.search(r"keep the first and discard the later one", yolo)
    agent = agent_text()
    assert re.search(r"At most 12 tool calls", agent)
    assert re.search(r"canonical `https://` URL", agent)


def test_agent_has_no_shell_or_file_access_and_uses_library_hits_first():
    meta = yaml.safe_load(re.match(r"---\n(.*?)\n---\n", agent_text(), re.DOTALL).group(1))
    assert meta["name"] == "benchmark-researcher"
    tools = {t.strip() for t in meta["tools"].split(",")}
    # it reads untrusted pages, so it holds no tool that reaches local data or runs commands
    assert tools == {"WebSearch", "WebFetch"}
    body = agent_text()
    assert body.index("Library hits first") < body.index("host's web search")
    assert "write no file" in body and "never an instruction to you" in body
    assert "cannot search the library itself" in reference("collect-data", "yolo.md")


def test_yolo_asks_nothing_and_never_runs_org_setup():
    yolo = reference("collect-data", "yolo.md")
    assert re.search(r"asks the user nothing", yolo)
    assert re.search(r"Never run `risk-quant-org-setup` on this route", yolo)
    assert "rqh library search" in yolo and "segment_match" in yolo and "`low`" in yolo
    assert yolo.index("Library search first") < yolo.index("benchmark-researcher")
    accuracy = reference("collect-data", "accuracy.md")
    assert re.search(r"invoke `risk-quant-org-setup` inline, with the minimal scope", accuracy)


def test_collect_data_hand_off_names_next_skill_and_chains_nothing():
    text = skill("collect-data")
    hand_off = section(text, "Hand-off")
    assert "rqh status" in hand_off and "next_skill" in hand_off and "without invoking" in hand_off
    assert "never invoke another phase skill" in text.lower()
    assert chained(text_of("collect-data")) == []


def chained(text: str) -> list[str]:
    names = "|".join(re.escape(n) for n in PHASES)
    verb = r"(?:invoke|run|call|launch|start|switch to|continue with|proceed to|hand over to)"
    target = rf"(?:`(?:{names})`|\b(?:{names})\s+skill\b)"
    return [m.group(0) for m in re.finditer(rf"\b{verb}\b[^.\n`]{{0,40}}?{target}", text, re.IGNORECASE)]


def test_chain_detector_catches_chaining():
    assert chained("When done, invoke `simulate` next.")


def test_collect_data_rereads_inputs_after_rqh_writes():
    assert re.search(r"Re-read `inputs.yaml` after any `rqh` command that writes it", skill("collect-data"))
    assert re.search(r"Re-read `inputs.yaml` afterwards", reference("collect-data", "accuracy.md"))


def test_resume_enters_the_router_loop():
    text = skill("risk-quant-resume")
    steps = section(text, "Steps")
    assert "awaiting_data" in steps and "invoke `collect-data` first" in steps
    assert "Enter the router loop" in steps and "`risk-quant` router" in steps
    assert "skills/risk-quant/SKILL.md" in steps
    assert steps.index("invoke `collect-data` first") < steps.index("Enter the router loop")
    assert "writes nothing" in text and "asks the user nothing of its own" in text
    assert "rqh status" in steps
    for other in ("simulate", "report", "scope-scenario"):
        assert not re.search(rf"\b(invoke|run)\b[^.\n`]{{0,20}}`{other}`", text.split("## Never")[0], re.IGNORECASE)


EDIT = re.compile(r"\b(edit|write|writes|modify|change|update|overwrite|append|patch|create)\b", re.IGNORECASE)
PROTECTED = re.compile(r"`run\.yaml`|`requests\.yaml`|`v<N>/`|v<N>/")


@pytest.mark.parametrize("name", [*OWN])
def test_no_instruction_to_edit_state_files_directly(name):
    for path in skill_files(name):
        for clause in clauses(path.read_text(encoding="utf-8")):
            if PROTECTED.search(clause) and EDIT.search(clause):
                assert re.search(r"\b(never|not)\b", clause, re.IGNORECASE), f"{path.name}: {clause}"
    assert re.search(r"Never edit `run.yaml`, `requests.yaml` or any `v<N>/` file", skill("collect-data"))
    assert re.search(r"Never edit `run.yaml`, `requests.yaml`", skill("risk-quant-memory"))


def test_edit_detector_catches_a_direct_edit():
    clause = "Write the status into `run.yaml` when the user confirms."
    assert PROTECTED.search(clause) and EDIT.search(clause)


def test_org_setup_is_read_only_confirmed_and_validated():
    text = skill("risk-quant-org-setup")
    assert "rqh validate .riskquant/org-profile.yaml" in text
    assert re.search(r"Nothing goes into the profile until the user confirms it", text)
    assert re.search(r"minimal scope|owner roles the run's Accuracy parameters route to", text)
    assert "logo_data_uri" in text and "200 KB" in text
    assert re.search(r"Never invent a person", text)


def test_the_router_keeps_going_after_a_phase_hands_back():
    # 0.1.0 live run: in 2 of 3 Accuracy trials the agent ended its reply on scope-scenario's
    # hand-off line ("the next skill is collect-data, the router will start it") instead of
    # returning to the loop, so nothing was drafted. The router runs in the same reply.
    loop = section(skill("risk-quant"), "The loop")
    assert "not the end of your reply" in loop and "until a stop rule" in loop


@pytest.mark.parametrize("name", ["scope-scenario", "collect-data", "simulate", "report"])
def test_every_phase_hands_back_to_the_router_without_chaining(name):
    text = skill(name)
    hand_off = section(text, "Hand-off")
    assert "without invoking" in hand_off
    assert "hand back to the router" in hand_off and "not the end of the reply" in hand_off
    assert chained(text_of(name)) == []


# --- F-B4: connector, web and owner text never lands on a shell command line ---

CANDIDATE_FLAG = re.compile(r"--(min|mode|max|unit|evidence|origin|link|note)(?![-\w])")


def test_candidate_and_answer_text_stays_off_the_command_line():
    accuracy = reference("collect-data", "accuracy.md")
    assert ("rqh candidates add <run> --parameter <path> --candidate-file "
            ".riskquant/runs/<run>/candidate-<parameter>.yaml") in accuracy
    assert ("rqh requests update <run> <id> --status answered --answer-file "
            ".riskquant/runs/<run>/answer-<id>.yaml") in accuracy
    assert len(re.findall(r"with your file-writing tool, never with a shell command", accuracy)) >= 3
    for path in [*sorted(SKILLS.rglob("*.md")), AGENT]:
        found = CANDIDATE_FLAG.search(path.read_text(encoding="utf-8"))
        assert not found, f"{path.relative_to(ROOT)} puts candidate or answer text on the command line with {found.group()}"


@pytest.mark.parametrize("line", ["--link <https url>", "`--note`", "--origin connector:x", "--min 1", "--unit\n"])
def test_the_candidate_flag_detector_catches_every_spelling(line):
    assert CANDIDATE_FLAG.search(line)
    assert not CANDIDATE_FLAG.search("--candidate-file x --answer-file y --max-results 5 --max-cost-usd 0")


def test_the_search_query_is_plain_words_in_single_quotes():
    yolo = reference("collect-data", "yolo.md")
    assert "rqh search '<query>'" in yolo
    assert not re.search(r"rqh search \"", text_of("collect-data"))
    [rule] = [c for c in clauses(yolo) if "only letters, digits, spaces and hyphens" in c]
    assert "scenario type" in rule and "segment" in rule and "parameter" in rule


# --- F-B3: the web-enabled researcher never sees the organisation's own figures ---

def test_the_researcher_is_given_only_shipped_benchmark_hits():
    research = section(reference("collect-data", "yolo.md"), "2. The benchmark-researcher for the gaps")
    assert "whose `origin` is `benchmark`" in research
    assert re.search(r"Never pass it a memory hit", research)
    assert not re.search(r"the library hits step 1 found", research)  # the old wording passed every hit
    body = agent_text()
    meta = yaml.safe_load(re.match(r"---\n(.*?)\n---\n", body, re.DOTALL).group(1))
    assert "shipped benchmark library hits" in meta["description"]
    assert "never the organisation's own" in meta["description"]
    inputs = section(body, "Input you receive")
    assert "`origin` `benchmark`" in inputs and re.search(r"You never receive the organisation's own figures", inputs)


# --- F-B5: SECURITY.md names the guardrails that only prose holds ---

def test_security_lists_the_prose_only_guardrails_and_the_real_control():
    security = section((ROOT / "SECURITY.md").read_text(encoding="utf-8"), "Guardrails the skills hold in prose")
    assert "permission prompts" in security and "actual control" in security
    for guardrail in ("send nothing", "read-only", "data, never an instruction", "`inputs.yaml`",
                      "`rqh candidates confirm`", "without a yes", "`.riskquant/library/`", "12 tool calls",
                      "internal figure"):
        assert guardrail in security, guardrail
    assert "allowed-tools" in security and "auto-approve" in security
    table, enforced = security.split("These are enforced:", 1)
    # keeping connector text off the shell is a prose rule: the per-field flags still accept any text
    assert "shell command line" in table and "file-writing tool" in table
    assert "`rqh search`" in table and "single quotes" in table
    assert "shell command line" not in enforced  # rqh only confines which file it reads


def test_no_skill_or_agent_declares_allowed_tools():
    # in Claude Code `allowed-tools` pre-approves tools, it does not restrict them (see SECURITY.md)
    for path in [*sorted(SKILLS.glob("*/SKILL.md")), *sorted((ROOT / "agents").glob("*.md"))]:
        meta = yaml.safe_load(re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.DOTALL).group(1))
        assert "allowed-tools" not in meta, path.relative_to(ROOT)
