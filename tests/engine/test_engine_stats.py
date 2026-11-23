from __future__ import annotations

import numpy as np

from rqharness.engine import simulate
from rqharness.model import load_model_inputs


def test_parameter_stats_use_pert_mean_when_no_events(make_inputs):
    doc = make_inputs(
        freq_model="lef_direct",
        freq={"lef": (0.5,)},
        primary={"response": (10.0, 20.0, 90.0)},
        secondary={"slef": (0.5,), "reputation": (100.0, 200.0, 900.0)},
    )
    model = load_model_inputs(doc)
    res = simulate(model, n=3000, seed=2)
    stats, events = res.parameter_stats, res.variants["baseline"].event_count
    resp = model.baseline["primary_loss.response"].mean
    rep = model.baseline["secondary_loss.reputation"].mean
    assert (events == 0).any()
    assert np.all(stats["primary_loss.response"][events == 0] == resp)
    assert np.all(stats["secondary_loss.reputation"][events == 0] == rep)
    assert (stats["secondary_loss.reputation"] != rep).any()
