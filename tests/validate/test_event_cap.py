"""Validation states the engine's event cap, so finalize never reaches the guard."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml

from rqharness import cli, engine, library, model
from rqharness.validate import validate_inputs

SAMPLE = Path(__file__).parent / "fixtures" / "sample-run"
RUN_ID = "credential-phishing-bec"


def sample_inputs() -> dict:
    return yaml.safe_load((SAMPLE / "inputs.yaml").read_text(encoding="utf-8"))


def _range(est: dict, lo: float, mode: float, hi: float) -> None:
    est.update(min=lo, mode=mode, max=hi)


def ddos_inputs() -> dict:
    """DDoS-like: two million attack attempts a year, half of which get through."""
    d = sample_inputs()
    _range(d["parameters"]["frequency"]["tef"], 500_000, 1_000_000, 2_000_000)
    _range(d["parameters"]["vulnerability"]["probability"], 0.1, 0.3, 0.5)
    return d


def cap_issues(d: dict) -> list[tuple[str, str]]:
    return [(i["path"], i["rule"]) for i in validate_inputs(d, entry_lookup=library.entry_lookup(None)) if i["rule"] == "expected_events"]


# --- AC1: the rule ------------------------------------------------------------------


def test_high_tef_rejected_on_the_rate_estimate():
    issues = [i for i in validate_inputs(ddos_inputs(), entry_lookup=library.entry_lookup(None)) if i["rule"] == "expected_events"]
    assert [i["path"] for i in issues] == ["inputs.parameters.frequency.tef.max"]
    assert "1,000,000" in issues[0]["message"] and f"{engine.MAX_EVENT_MEAN:,}" in issues[0]["message"]


def test_high_tef_with_low_vulnerability_accepted():
    d = ddos_inputs()
    _range(d["parameters"]["vulnerability"]["probability"], 0.01, 0.02, 0.05)  # at most 100,000 x 0.05 ...
    _range(d["parameters"]["frequency"]["tef"], 400_000, 800_000, 1_000_000)  # ... = 50,000 events
    assert cap_issues(d) == []


def test_analysis_period_scales_the_expected_events():
    d = sample_inputs()
    _range(d["parameters"]["frequency"]["tef"], 100_000, 150_000, 200_000)  # 200,000 x 0.06 = 12,000 a year
    assert cap_issues(d) == []
    d["parameters"]["analysis_period_years"] = 10
    assert cap_issues(d) == [("inputs.parameters.frequency.tef.max", "expected_events")]


def test_slef_over_the_cap_rejected():
    d = sample_inputs()
    _range(d["parameters"]["secondary_loss"]["slef"], 1, 10, engine.MAX_EVENT_MEAN + 1)
    assert cap_issues(d) == [("inputs.parameters.secondary_loss.slef.max", "expected_events")]


def test_variant_override_of_the_probability_factor_blames_the_variant():
    d = sample_inputs()
    _range(d["parameters"]["frequency"]["tef"], 100_000, 500_000, 1_000_000)  # baseline 1e6 x 0.06 = 60,000
    assert cap_issues(d) == []
    _range(d["variants"][0]["overrides"]["vulnerability.probability"], 0.05, 0.08, 0.1)  # 100,000
    assert cap_issues(d) == [("inputs.variants.0.overrides.vulnerability.probability.max", "expected_events")]


# The bound reads every frequency estimate of each model: tests/engine/test_expected_events.py.


def test_variant_identical_in_frequency_is_not_reported_twice():
    d = ddos_inputs()
    d["variants"][0]["overrides"] = {}
    assert cap_issues(d) == [("inputs.parameters.frequency.tef.max", "expected_events")]


# --- AC2: finalize exits 1 with the issue ---------------------------------------------


@pytest.fixture
def ddos_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    assert cli.main(["init"]) == 0
    d = tmp_path / ".riskquant" / "runs" / RUN_ID
    d.mkdir(parents=True)
    shutil.copy(SAMPLE / "scenario.yaml", d / "scenario.yaml")
    (d / "inputs.yaml").write_text(yaml.safe_dump(ddos_inputs(), sort_keys=False), encoding="utf-8")
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo", "--n", "2000", "--seed", "7"]) == 0
    return d


def test_finalize_on_high_tef_exits_1_with_the_issue(ddos_run, capsys):
    capsys.readouterr()
    code = cli.main(["finalize", RUN_ID, "--json"])
    env = json.loads(capsys.readouterr().out)
    assert code == 1
    issues = [(i["path"], i["rule"]) for i in env["issues"]]
    assert issues == [("inputs.parameters.frequency.tef.max", "expected_events")]
    assert not list(ddos_run.glob("v*"))


# --- AC3: the engine's bound and its guards -------------------------------------------


def test_bound_keeps_the_largest_draw_below_the_ordinal_limit():
    """Every engine uniform is at most engine.LARGEST_UNIFORM, so no n can draw past the bound."""
    largest = np.array([engine.LARGEST_UNIFORM])
    assert engine.ORDINAL_LIMIT == 1 << 16
    assert engine.poisson_inverse(largest, np.array([float(engine.MAX_EVENT_MEAN)]))[0] < engine.ORDINAL_LIMIT


def every_contact_lands(tef: tuple[float, float, float], slef: tuple[float, float, float]) -> dict:
    """The baseline alone, with a vulnerability near 1 so the event rate is the TEF."""
    d = sample_inputs()
    _range(d["parameters"]["frequency"]["tef"], *tef)
    _range(d["parameters"]["vulnerability"]["probability"], 0.99, 0.995, 1.0)
    _range(d["parameters"]["secondary_loss"]["slef"], *slef)
    d["variants"] = []
    return d


def test_engine_accepts_events_at_the_bound():
    d = every_contact_lands((62_000, 62_900, engine.MAX_EVENT_MEAN), (0.02, 0.08, 0.25))
    assert cap_issues(d) == []
    result = engine.simulate(model.load_model_inputs(d), n=8, seed=1)
    counts = result.variants["baseline"].event_count
    assert counts.max() < engine.ORDINAL_LIMIT and counts.min() > 60_000


def test_engine_accepts_secondary_events_at_the_bound():
    d = every_contact_lands((1, 2, 3), (62_000, 62_900, engine.MAX_EVENT_MEAN))
    assert cap_issues(d) == []
    result = engine.simulate(model.load_model_inputs(d), n=4, seed=1)
    assert result.variants["baseline"].event_count.sum() > 0


@pytest.mark.parametrize("tef, slef, message", [
    ((70_000, 75_000, 80_000), (0.02, 0.08, 0.25), "an iteration has 65,536 or more events"),
    ((1, 2, 3), (70_000, 75_000, 80_000), "a primary event has 65,536 or more secondary events"),
])
def test_engine_guards_remain_for_unvalidated_inputs(tef, slef, message):
    d = every_contact_lands(tef, slef)
    assert cap_issues(d)
    with pytest.raises(ValueError, match=message):
        engine.simulate(model.load_model_inputs(d), n=2, seed=1)
