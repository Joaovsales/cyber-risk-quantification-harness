from __future__ import annotations

import pytest

from builders import est, lef_doc
from conftest import SEED, engine, model
from rqharness.sensitivity import contributions


def run(doc, n=10_000):
    return contributions(engine.simulate(model.load_model_inputs(doc), n=n, seed=SEED))


def test_contributions_sum_to_one(sample_doc):
    res = engine.simulate(model.load_model_inputs(sample_doc), n=10_000, seed=SEED)
    s = contributions(res)
    assert list(s.contributions) == list(res.parameter_stats)
    assert sum(s.contributions.values()) == pytest.approx(1.0, abs=1e-12)
    assert all(v >= 0 for v in s.contributions.values())
    assert s.fallback is False


def test_dominant_parameter_ranked_first():
    doc = lef_doc((1, 2, 3), {"response": (1000, 2000, 3000), "replacement": (10, 5_000_000, 100_000_000)})
    s = run(doc)
    ranked = sorted(s.contributions, key=s.contributions.get, reverse=True)
    assert ranked[0] == "primary_loss.replacement"
    assert s.contributions["primary_loss.replacement"] > 0.5


def test_degenerate_parameter_contributes_zero():
    doc = lef_doc((1, 3, 6), {"response": (500, 1000, 4000), "replacement": (7000,)})
    s = run(doc)
    assert s.contributions["primary_loss.replacement"] == 0.0
    assert sum(s.contributions.values()) == pytest.approx(1.0, abs=1e-12)
    assert s.fallback is False


def test_all_constant_falls_back_to_equal_weights():
    doc = lef_doc((2,), {"response": (1000,), "replacement": (500,)})
    s = run(doc, n=1000)
    assert s.fallback is True
    assert set(s.contributions.values()) == {1 / 3}
    assert len(s.contributions) == 3


def test_inverse_driver_contributes_positively_by_squared_rank_correlation():
    """Resistance strength lowers loss (negative rank correlation); its share must still be
    positive, because a contribution is the SQUARED Spearman correlation."""
    doc = lef_doc((1, 1, 1), {"response": (1000, 1000, 1000)})
    doc["parameters"]["frequency"] = {
        "model": "tef_x_vulnerability",
        "tef": est(10, 20, 40, unit="events/year"),
    }
    doc["parameters"]["vulnerability"] = {
        "model": "tcap_x_resistance",
        "threat_capability": est(1, 1, 1, unit="score"),
        "resistance_strength": est(0.1, 1, 5, unit="score"),
    }
    sens = run(doc)
    share = sens.contributions["vulnerability.resistance_strength"]
    assert all(v >= 0 for v in sens.contributions.values())
    assert share > sens.contributions["frequency.tef"] > 0
