"""One engine function owns the LEF composition behind every expected-event estimate."""

from __future__ import annotations

import pytest

from rqharness import engine, library, model
from rqharness.pert import Pert
from rqharness.validate import validate_inputs

FREQ_UNITS = {"frequency.lef": "events/year", "frequency.tef": "events/year"}
MODELS = [(f, v) for f in model.FREQUENCY_ESTIMATES
          for v in (model.VULNERABILITY_ESTIMATES if f in model.USES_VULNERABILITY else [None])]


def events(frequency_model, vulnerability_model, estimates: dict[str, Pert], statistic, years=1.0):
    return engine.expected_events(frequency_model, vulnerability_model, years, estimates.__getitem__, statistic)


def anything(path: str) -> Pert:
    return Pert(1.0, 2.0, 3.0)


@pytest.mark.parametrize("frequency_model, vulnerability_model", MODELS)
def test_the_bound_reads_every_frequency_estimate_of_the_model(frequency_model, vulnerability_model):
    """A new frequency estimate must join the bound, or validation stops bounding the engine."""
    got = engine.expected_events(frequency_model, vulnerability_model, 1.0, anything, "max").estimates
    expected = tuple(f"frequency.{name}" for name in model.FREQUENCY_ESTIMATES[frequency_model])
    if vulnerability_model == "direct_probability":
        expected += ("vulnerability.probability",)
    assert got == expected  # the rate first: validation blames the first one a variant overrides


def test_vulnerability_models_are_a_probability_or_a_share():
    assert model.VULNERABILITY_ESTIMATES == {
        "direct_probability": ("probability",),
        "tcap_x_resistance": ("threat_capability", "resistance_strength"),  # a share tcap / (tcap + rs) <= 1
    }


def test_the_bound_is_the_product_of_the_maxima_over_the_period():
    got = events("tef_x_vulnerability", "direct_probability",
                 {"frequency.tef": Pert(10, 500, 1000), "vulnerability.probability": Pert(0.1, 0.2, 0.5)},
                 "max", years=3)
    assert got.per_iteration == pytest.approx(1000 * 0.5 * 3)
    got = events("tef_decomposed_cf_poa", None,
                 {"frequency.contact": Pert(1, 100, 200), "frequency.action": Pert(0, 0.1, 0.25)}, "max")
    assert got.per_iteration == pytest.approx(200 * 0.25)


def test_the_bound_takes_the_tcap_share_as_one():
    got = events("tef_x_vulnerability", "tcap_x_resistance",
                 {"frequency.tef": Pert(10, 500, 1000), "vulnerability.threat_capability": Pert(1, 2, 3),
                  "vulnerability.resistance_strength": Pert(50, 60, 70)}, "max", years=2)
    assert (got.per_iteration, got.estimates) == (pytest.approx(2000), ("frequency.tef",))


def test_the_mean_is_the_lef_formula_on_the_pert_means():
    got = events("tef_and_vulnerability_decomposed", "tcap_x_resistance",
                 {"frequency.contact": Pert(100, 100, 100), "frequency.action": Pert(0.5, 0.5, 0.5),
                  "vulnerability.threat_capability": Pert(30, 30, 30),
                  "vulnerability.resistance_strength": Pert(70, 70, 70)}, "mean", years=2)
    assert got.per_iteration == pytest.approx(100 * 0.5 * 0.3 * 2)
    assert got.estimates == ("frequency.contact", "frequency.action", "vulnerability.threat_capability",
                             "vulnerability.resistance_strength")


def test_validation_takes_its_bound_from_the_engine(sample_inputs, monkeypatch):
    """validate.py lists no frequency factor: the engine's bound and the estimates it read decide."""
    tef_max = [sample_inputs["parameters"]["frequency"]["tef"]["max"]]
    tef_max += [v["overrides"]["frequency.tef"]["max"] for v in sample_inputs["variants"]
                if "frequency.tef" in v["overrides"]]
    calls = []

    def fake(frequency_model, vulnerability_model, years, estimate, statistic):
        calls.append((frequency_model, vulnerability_model, years, estimate("frequency.tef").max, statistic))
        return engine.ExpectedEvents(engine.MAX_EVENT_MEAN + 1.0, ("frequency.tef",))
    monkeypatch.setattr(engine, "expected_events", fake)
    issues = [(i["path"], i["rule"]) for i in validate_inputs(sample_inputs, entry_lookup=library.entry_lookup(None))]
    overriding = [f"inputs.variants.{i}.overrides.frequency.tef.max"
                  for i, v in enumerate(sample_inputs["variants"]) if "frequency.tef" in v["overrides"]]
    assert overriding, "the sample has a variant that overrides the rate"
    assert issues == [(p, "expected_events") for p in ["inputs.parameters.frequency.tef.max", *overriding]]
    assert len(calls) == 1 + len(sample_inputs["variants"])
    assert {c[:3] + (c[4],) for c in calls} == {("tef_x_vulnerability", "direct_probability", 1, "max")}
    assert sorted({c[3] for c in calls}) == sorted(set(tef_max))


def test_the_memory_budget_sizes_each_variant_from_the_engine_means(make_inputs, make_variant):
    m = model.load_model_inputs(make_inputs(freq_model="lef_direct", freq={"lef": (10, 20, 30)}, years=2,
                                            variants=[make_variant("v", {"frequency.lef": (5,)}, FREQ_UNITS)]))
    sizes = [engine.expected_events(m.frequency_model, m.vulnerability_model, m.years, eff.__getitem__, "mean")
             for eff in ({**m.baseline}, {**m.baseline, **m.variants[0].overrides})]
    assert engine.event_budget(m).cells_per_iteration == pytest.approx(sum(s.per_iteration for s in sizes))
