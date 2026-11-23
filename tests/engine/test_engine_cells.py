"""The engine's two stages: per-iteration draws, then event cells built from every variant's counts."""

from __future__ import annotations

import numpy as np

from rqharness import engine
from rqharness.model import load_model_inputs


def _stages(model, n, seed):
    effective = {"baseline": model.baseline, **{v.id: {**model.baseline, **v.overrides} for v in model.variants}}
    draws = engine._IterationDraws(model, n, seed)
    counts = {vid: draws.event_count(draws.lef(eff)) for vid, eff in effective.items()}
    return effective, counts, engine._EventCells(draws, counts)


def test_event_cells_reproduce_simulate_for_every_variant(sample_inputs):
    model = load_model_inputs(sample_inputs)
    effective, counts, cells = _stages(model, 2000, 7)
    res = engine.simulate(model, n=2000, seed=7)
    assert set(effective) == set(res.variants) and len(effective) > 1
    for vid, eff in effective.items():
        assert np.array_equal(counts[vid], res.variants[vid].event_count)
        assert np.array_equal(cells.annual_loss(vid, eff), res.variants[vid].annual_loss)
    stats = cells.parameter_stats()
    assert list(stats) == list(res.parameter_stats)
    assert all(np.array_equal(stats[p], res.parameter_stats[p]) for p in stats)


def test_each_variant_is_masked_by_its_own_counts(make_inputs, make_variant):
    # The layout is the maximum over variants; a variant with fewer events sums only its own.
    doc = make_inputs(
        freq_model="lef_direct", freq={"lef": (6.0,)}, primary={"response": (1000.0,)}, years=2,
        variants=[make_variant("low", {"frequency.lef": (1.0,)}, {"frequency.lef": "events/year"})],
    )
    effective, counts, cells = _stages(load_model_inputs(doc), 3000, 4)
    assert np.all(counts["low"] <= counts["baseline"]) and counts["low"].sum() < counts["baseline"].sum()
    for vid, eff in effective.items():
        assert np.array_equal(cells.annual_loss(vid, eff), 1000.0 * counts[vid] / 2)
