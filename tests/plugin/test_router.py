"""AC35: the router loop, the SKILL.md fallback, phase hand-offs, and real rqh commands only."""

from __future__ import annotations

import argparse
import re

import pytest
from conftest import PHASE_SKILLS, read_skill, section

from rqharness import cli
from rqharness.report.narrative import render_narrative

ALL_PHASES = ("scope-scenario", "collect-data", "simulate", "report")


def test_router_loop_rules():
    text = read_skill("risk-quant")
    loop = section(text, "The loop")
    for needle in ("rqh init", "rqh status", "next_skill", "null", "unchanged", "risk-quant-memory", "once"):
        assert needle in loop, needle
    assert "missing" in loop and "no run" in loop
    assert "batch mode" in loop
    assert "ask the user nothing" in text.lower()


def test_skill_md_fallback():
    text = section(read_skill("risk-quant"), "When the host cannot invoke a skill")
    assert "skills/<next_skill>/SKILL.md" in text
    assert "inline" in text and "continue the loop" in text


def _chains(text: str) -> list[str]:
    """Sentences that tell the reader to invoke or run a phase skill."""
    names = "|".join(re.escape(n) for n in ALL_PHASES)
    verb = r"(?:invoke|run|call|launch|start|switch to|continue with|proceed to|hand over to)"
    target = rf"(?:`(?:{names})`|\b(?:{names})\s+skill\b)"
    pattern = re.compile(rf"\b{verb}\b[^.\n`]{{0,40}}?{target}", re.IGNORECASE)
    return [m.group(0) for m in pattern.finditer(text)]


def test_chain_detector_catches_a_real_chaining_sentence():
    assert _chains("When done, invoke `collect-data` next.")
    assert _chains("Then run the report skill.")
    assert not _chains("Tell the user the `next_skill` it returns.")


@pytest.mark.parametrize("name", [*PHASE_SKILLS, "collect-data"])
def test_phase_skills_name_next_and_never_chain(name):
    text = read_skill(name)
    hand_off = section(text, "Hand-off")
    assert "rqh status" in hand_off and "next_skill" in hand_off
    assert "without invoking" in hand_off
    assert "never invoke another phase skill" in text.lower()
    assert _chains(text) == [], _chains(text)


def _subparsers(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def _code_spans(text: str) -> list[str]:
    fences = re.findall(r"```[a-z]*\n(.*?)```", text, re.DOTALL)
    lines = [line for block in fences for line in block.splitlines()]
    inline = re.findall(r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.DOTALL))
    return lines + inline


@pytest.mark.parametrize(
    "name",
    ["risk-quant", *PHASE_SKILLS, "collect-data", "risk-quant-resume", "risk-quant-org-setup", "risk-quant-memory"],
)
def test_every_rqh_command_and_flag_is_real(name):
    root = cli.build_parser()
    checked = 0
    for span in _code_spans(read_skill(name)):
        match = re.match(r"\s*(?:rqh|python -m rqharness)\s+(.*)", span)
        if not match:
            continue
        words = [w for w in match.group(1).split() if not w.startswith(("<", "[", "..."))]
        parser = root
        for word in (w for w in words if not w.startswith("-")):
            children = _subparsers(parser)
            if not children:
                break
            assert word in children, f"{name}: `{span}` names unknown command '{word}'"
            parser = children[word]
        known = {opt for action in parser._actions for opt in action.option_strings} | {"--json"}
        for flag in re.findall(r"--[a-z][a-z-]*", match.group(1)):
            assert flag in known, f"{name}: `{span}` uses unknown flag {flag}"
        checked += 1
    assert checked, f"{name} names no rqh command"


def test_report_example_narrative_renders():
    example = re.search(r"```markdown\n(.*?)```", read_skill("report"), re.DOTALL)
    assert example, "report skill needs a worked ```markdown example"
    base = {"currency": "USD", "mean": 2_000_000.0, "median": 900_000.0, "p10": 1.0, "p25": 1.0,
            "p75": 1.0, "p90": 4_800_000.0, "p95": 1.0, "p99": 1.0}
    cut = {**base, "mean": 700_000.0, "p90": 2_000_000.0}
    lef = {"mean": 1.5, "median": 1.0, "p90": 3.0}
    summary = {"currency": "USD", "quality": {"grade": "B", "score": 0.65}, "variants": [
        {"id": "baseline", "label": "Current controls", "annual_cost": None, "annual_loss": base, "lef": lef, "event_count": lef},
        {"id": "mfa", "label": "MFA", "annual_cost": {"currency": "USD", "mean": 100_000.0}, "annual_loss": cut, "lef": lef, "event_count": lef}],
        "deltas": [{"variant": "mfa", "currency": "USD", "ale_reduction_mean": 1_300_000.0,
                    "ale_reduction_p90": 2_800_000.0, "return_on_control": 12.0}]}
    result = render_narrative(example.group(1), summary)
    assert result.rejected is None, result.rejected
