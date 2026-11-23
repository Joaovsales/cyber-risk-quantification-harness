"""The engine's memory budget: expected event cells estimated from the inputs (D32)."""

from __future__ import annotations

import pytest

from rqharness import engine, model

EVENTS = {"frequency.lef": "events/year", "frequency.tef": "events/year"}


def per_iteration(make_inputs, **kw) -> float:
    return engine.event_budget(model.load_model_inputs(make_inputs(**kw))).cells_per_iteration


def test_budget_constant_is_stated_next_to_the_engine():
    assert engine.MAX_EVENT_CELLS == 40_000_000


def test_cells_are_the_mean_events_over_the_period(make_inputs):
    # PERT(10, 20, 30) has mean 20; two years double it.
    assert per_iteration(make_inputs, freq_model="lef_direct", freq={"lef": (10, 20, 30)}, years=2) == pytest.approx(40)


def test_secondary_events_add_the_slef_mean_per_primary_event(make_inputs):
    got = per_iteration(make_inputs, freq_model="lef_direct", freq={"lef": (20,)},
                        secondary={"slef": (0.5,), "reputation": (100.0,)})
    assert got == pytest.approx(20 * 1.5)


def test_every_variant_adds_its_own_events(make_inputs, make_variant):
    got = per_iteration(make_inputs, freq_model="lef_direct", freq={"lef": (20,)},
                        variants=[make_variant("v", {"frequency.lef": (5,)}, EVENTS)])
    assert got == pytest.approx(20 + 5)


def test_decomposed_frequency_uses_the_engines_lef_formula_on_the_means(make_inputs):
    # tcap / (tcap + rs) = 30 / (30 + 70) on the means; contact x clip(action) = 100 x 0.5.
    got = per_iteration(make_inputs, freq_model="tef_and_vulnerability_decomposed",
                        freq={"contact": (100,), "action": (0.5,)},
                        vuln_model="tcap_x_resistance", vuln={"threat_capability": (30,), "resistance_strength": (70,)})
    assert got == pytest.approx(100 * 0.5 * 0.3)


def test_estimate_tracks_the_cells_a_simulation_lays_out(make_inputs):
    m = model.load_model_inputs(make_inputs(freq_model="lef_direct", freq={"lef": (5, 10, 40)}))
    drawn = engine.simulate(m, n=4_000, seed=3).variants["baseline"].event_count.sum()
    assert drawn == pytest.approx(engine.event_budget(m).cells(4_000), rel=0.05)


def test_max_n_is_the_largest_n_that_fits():
    budget = engine.EventBudget(cells_per_iteration=1_000.0)
    assert budget.max_n == 40_000
    assert budget.fits(budget.max_n) and not budget.fits(budget.max_n + 1)


def test_max_n_is_zero_when_one_iteration_is_over_the_budget():
    assert engine.EventBudget(cells_per_iteration=engine.MAX_EVENT_CELLS + 1.0).max_n == 0


def test_a_model_with_no_events_fits_any_n():
    assert engine.EventBudget(cells_per_iteration=0.0).fits(10**9)
