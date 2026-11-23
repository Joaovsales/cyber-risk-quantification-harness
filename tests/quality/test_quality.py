"""AC10: the sensitivity-weighted tier score and its A-D grade."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rqharness import library, quality

SAMPLE = Path(__file__).parents[1] / "validate" / "fixtures" / "sample-run" / "inputs.yaml"


def rows(*pairs: tuple[str, float]) -> list[dict]:
    return [
        {"path": f"primary_loss.p{i}", "label": f"P{i}", "tier": tier, "contribution": c}
        for i, (tier, c) in enumerate(pairs)
    ]


@pytest.mark.parametrize(
    ("params", "expected_grade"),
    [
        (rows(("internal_data", 0.9), ("benchmark", 0.1)), "A"),  # 0.94
        (rows(("sme_estimate", 0.8), ("internal_data", 0.2)), "B"),  # 0.76
        (rows(("benchmark", 0.6), ("sme_estimate", 0.4)), "C"),  # 0.52
        (rows(("agent_assumption", 0.7), ("benchmark", 0.3)), "D"),  # 0.19
    ],
)
def test_grade_thresholds(params, expected_grade):
    assert quality.grade(quality.score(params)) == expected_grade
    assert quality.quality_block(params)["grade"] == expected_grade


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.85, "A"), (0.8499, "B"), (0.65, "B"), (0.6499, "C"), (0.40, "C"), (0.3999, "D"), (1.0, "A"), (0.0, "D")],
)
def test_threshold_boundaries_are_inclusive(value, expected):
    assert quality.grade(value) == expected


def test_score_is_contribution_weighted_tier_score():
    params = rows(("internal_data", 0.5), ("sme_estimate", 0.25), ("benchmark", 0.15), ("agent_assumption", 0.1))
    assert quality.score(params) == pytest.approx(0.5 * 1.0 + 0.25 * 0.7 + 0.15 * 0.4 + 0.1 * 0.1)


def test_unknown_tier_is_rejected_by_validation():
    """Quality trusts the tier enum to the inputs schema (D30), so validation must catch it."""
    from rqharness.validate import validate_inputs

    inputs = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    assert validate_inputs(inputs, entry_lookup=library.entry_lookup(None)) == []
    inputs["parameters"]["frequency"]["tef"]["provenance"]["tier"] = "guess"
    issues = validate_inputs(inputs, entry_lookup=library.entry_lookup(None))
    assert ("inputs.parameters.frequency.tef.provenance.tier", "enum") in {(i["path"], i["rule"]) for i in issues}


def test_quality_block_shape():
    block = quality.quality_block(rows(("benchmark", 1.0)))
    assert block == {
        "score": pytest.approx(0.4),
        "grade": "C",
        "tier_scores": {"internal_data": 1.0, "sme_estimate": 0.7, "benchmark": 0.4, "agent_assumption": 0.1},
    }


def test_improvement_priority_orders_by_contribution_times_gap():
    params = rows(("internal_data", 0.6), ("benchmark", 0.3), ("agent_assumption", 0.1))
    ranked = quality.improvement_priority(params)
    # priorities: 0.6 * 0 = 0, 0.3 * 0.6 = 0.18, 0.1 * 0.9 = 0.09
    assert [r["path"] for r in ranked] == ["primary_loss.p1", "primary_loss.p2", "primary_loss.p0"]
    assert ranked[0]["priority"] == pytest.approx(0.18)
    assert set(ranked[0]) == {"path", "label", "tier", "contribution", "priority"}


def test_sample_run_has_a_grade():
    from rqharness import engine, sensitivity, summary
    from rqharness.model import load_model_inputs

    inputs = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    model = load_model_inputs(inputs)
    result = engine.simulate(model, n=5_000, seed=20261109)
    built = summary.build_summary(inputs, model, result, sensitivity.contributions(result))
    block = quality.quality_block(built["parameters"])
    assert 0.0 <= block["score"] <= 1.0
    assert block["grade"] in {"A", "B", "C", "D"}
