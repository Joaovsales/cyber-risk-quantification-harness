"""Each expected-events statistic declares whether it is an upper bound."""

from __future__ import annotations

from typing import get_args, get_type_hints

import pytest

from rqharness import engine
from rqharness.pert import Pert

TCAP_MODEL = {"frequency.tef": Pert(10, 500, 1000), "vulnerability.threat_capability": Pert(1, 2, 3),
              "vulnerability.resistance_strength": Pert(50, 60, 70)}
SHARE = ("vulnerability.threat_capability", "vulnerability.resistance_strength")


def test_every_statistic_declares_whether_it_is_an_upper_bound():
    accepted = get_args(get_type_hints(engine.expected_events)["statistic"])
    assert set(engine.STATISTICS) == set(accepted)
    assert engine.STATISTICS["max"] == engine.Statistic("max", upper_bound=True)  # validation's bound
    assert engine.STATISTICS["mean"] == engine.Statistic("mean", upper_bound=False)  # the memory budget


def test_the_statistics_cannot_be_changed_at_run_time():
    with pytest.raises(TypeError):
        engine.STATISTICS["max"] = engine.Statistic("max", upper_bound=False)  # type: ignore[index]


@pytest.mark.parametrize("name, upper_bound, expected", [
    ("max", False, (1000 * 3 / (3 + 70), ("frequency.tef", *SHARE))),  # the share of the maxima
    ("mean", True, (Pert(10, 500, 1000).mean, ("frequency.tef",))),  # the share taken as 1
])
def test_the_share_treatment_follows_the_declared_bound_not_the_name(monkeypatch, name, upper_bound, expected):
    monkeypatch.setattr(engine, "STATISTICS", {**engine.STATISTICS, name: engine.Statistic(name, upper_bound)})
    got = engine.expected_events("tef_x_vulnerability", "tcap_x_resistance", 1.0, TCAP_MODEL.__getitem__, name)
    assert (got.per_iteration, got.estimates) == (pytest.approx(expected[0]), expected[1])
