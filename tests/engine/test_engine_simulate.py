from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import poisson

from rqharness import engine
from rqharness.engine import simulate, stream_key
from rqharness.model import load_model_inputs

SRC = str(Path(__file__).parents[2] / "src")
N = 20_000
SEED = 12345

SECONDARY = {"slef": (0.5,), "reputation": (2000.0,), "fines_and_judgments": (500.0,)}
PRIMARY = {"response": (1000.0,), "productivity": (250.0,)}

# (id, frequency model, freq estimates, vulnerability model, vulnerability estimates, LEF per year)
MODELS = [
    ("lef_direct", "lef_direct", {"lef": (4.0,)}, None, None, 4.0),
    ("tef_x_v_direct", "tef_x_vulnerability", {"tef": (20.0,)}, "direct_probability", {"probability": (0.3,)}, 6.0),
    ("tef_x_v_tcap", "tef_x_vulnerability", {"tef": (20.0,)}, "tcap_x_resistance",
     {"threat_capability": (3.0,), "resistance_strength": (1.0,)}, 15.0),
    ("cf_poa", "tef_decomposed_cf_poa", {"contact": (20.0,), "action": (0.25,)}, None, None, 5.0),
    ("tef_and_v", "tef_and_vulnerability_decomposed", {"contact": (20.0,), "action": (0.5,)}, "direct_probability",
     {"probability": (0.4,)}, 4.0),
]


def _analytic(lef: float, primary=PRIMARY, secondary=SECONDARY) -> float:
    total = lef * sum(v[0] for v in primary.values())
    if secondary:
        total += lef * secondary["slef"][0] * sum(v[0] for k, v in secondary.items() if k != "slef")
    return total


@pytest.mark.parametrize("years", [1, 2])
@pytest.mark.parametrize("with_secondary", [False, True])
@pytest.mark.parametrize("case", MODELS, ids=[m[0] for m in MODELS])
def test_degenerate_pert_matches_analytic_mean(make_inputs, case, with_secondary, years):
    _, fm, freq, vm, vuln, lef = case
    sec = SECONDARY if with_secondary else None
    model = load_model_inputs(
        make_inputs(freq_model=fm, freq=freq, vuln_model=vm, vuln=vuln, primary=PRIMARY, secondary=sec, years=years)
    )
    loss = simulate(model, n=N, seed=SEED).variants["baseline"].annual_loss
    stderr = loss.std() / np.sqrt(N)
    assert abs(loss.mean() - _analytic(lef, secondary=sec)) <= 4 * stderr


def test_tcap_zero_sum_gives_zero_vulnerability(make_inputs):
    model = load_model_inputs(
        make_inputs(freq_model="tef_x_vulnerability", freq={"tef": (20.0,)}, vuln_model="tcap_x_resistance",
                    vuln={"threat_capability": (0.0,), "resistance_strength": (0.0,)})
    )
    res = simulate(model, n=500, seed=1).variants["baseline"]
    assert not res.lef.any() and not res.annual_loss.any()


def test_probability_is_clipped_to_unit_interval(make_inputs):
    model = load_model_inputs(
        make_inputs(freq_model="tef_decomposed_cf_poa", freq={"contact": (10.0,), "action": (3.0,)})
    )
    assert np.all(simulate(model, n=200, seed=1).variants["baseline"].lef == 10.0)


def test_variant_without_overrides_identical(sample_inputs):
    sample_inputs["variants"].append({"id": "noop", "label": "No change", "overrides": {}})
    res = simulate(load_model_inputs(sample_inputs), n=5000, seed=7)
    base, noop = res.variants["baseline"], res.variants["noop"]
    assert np.array_equal(base.annual_loss, noop.annual_loss)
    assert np.array_equal(base.event_count, noop.event_count)
    assert np.array_equal(base.lef, noop.lef)


def _scaled(path_est: tuple, factor: float) -> tuple:
    return tuple(v * factor for v in path_est)


def test_scaled_down_vulnerability_never_increases_loss_sample(sample_inputs):
    est = sample_inputs["parameters"]["vulnerability"]["probability"]
    scaled = {k: est[k] * 0.6 for k in ("min", "mode", "max")}
    sample_inputs["variants"] = [
        {"id": "v06", "label": "v", "overrides": {"vulnerability.probability": {**est, **scaled}}}
    ]
    res = simulate(load_model_inputs(sample_inputs), n=20_000, seed=3)
    base, var = res.variants["baseline"], res.variants["v06"]
    assert np.all(var.annual_loss <= base.annual_loss)
    assert np.all(var.event_count <= base.event_count)
    assert var.annual_loss.sum() < base.annual_loss.sum()


def test_scaled_down_vulnerability_never_increases_loss_secondary_direct(make_inputs, make_variant):
    vuln = (0.05, 0.10, 0.30)
    doc = make_inputs(
        freq_model="tef_x_vulnerability",
        freq={"tef": (10.0, 30.0, 60.0)},
        vuln_model="direct_probability",
        vuln={"probability": vuln},
        primary={"response": (100.0, 1000.0, 9000.0), "productivity": (10.0, 20.0, 40.0)},
        secondary={"slef": (0.1, 0.5, 1.5), "reputation": (500.0, 2000.0, 9000.0)},
        variants=[make_variant("v06", {"vulnerability.probability": tuple(v * 0.6 for v in vuln)},
                               {"vulnerability.probability": "probability"})],
    )
    res = simulate(load_model_inputs(doc), n=20_000, seed=11)
    base, var = res.variants["baseline"], res.variants["v06"]
    assert np.all(var.annual_loss <= base.annual_loss)
    assert var.annual_loss.sum() < base.annual_loss.sum()


def test_variant_overriding_a_magnitude_changes_only_that_magnitude(make_inputs, make_variant):
    doc = make_inputs(
        freq_model="lef_direct", freq={"lef": (6.0,)},
        primary={"response": (100.0, 1000.0, 5000.0), "productivity": (10.0, 20.0, 40.0)},
        variants=[make_variant("r2", {"primary_loss.response": (200.0, 2000.0, 10000.0)})],
    )
    res = simulate(load_model_inputs(doc), n=4000, seed=5)
    base, r2 = res.variants["baseline"], res.variants["r2"]
    assert np.array_equal(base.event_count, r2.event_count)
    # response doubles exactly (same uniforms); productivity unchanged -> response share is recoverable
    assert np.all(r2.annual_loss >= base.annual_loss)
    assert np.all((r2.annual_loss - base.annual_loss)[base.event_count > 0] > 0)


def test_overriding_slef_keeps_primary_loss_events(make_inputs, make_variant):
    doc = make_inputs(
        freq_model="lef_direct", freq={"lef": (6.0,)}, primary={"response": (1000.0,)},
        secondary={"slef": (0.2,), "reputation": (300.0,)},
        variants=[make_variant("s0", {"secondary_loss.slef": (0.0,)}, {"secondary_loss.slef": "events/event"})],
    )
    res = simulate(load_model_inputs(doc), n=4000, seed=5)
    base, s0 = res.variants["baseline"], res.variants["s0"]
    assert np.array_equal(s0.annual_loss, 1000.0 * s0.event_count)
    assert np.all(base.annual_loss >= s0.annual_loss)


def test_parameter_stats(sample_inputs):
    model = load_model_inputs(sample_inputs)
    res = simulate(model, n=3000, seed=9)
    stats = res.parameter_stats
    assert list(stats) == list(model.baseline)
    assert all(len(a) == 3000 for a in stats.values())
    resp = model.baseline["primary_loss.response"]
    assert np.all((stats["primary_loss.response"] >= resp.min) & (stats["primary_loss.response"] <= resp.max))
    tef = model.baseline["frequency.tef"]
    assert np.all((stats["frequency.tef"] >= tef.min) & (stats["frequency.tef"] <= tef.max))
    rep = model.baseline["secondary_loss.reputation"]
    assert np.all((stats["secondary_loss.reputation"] >= rep.min) & (stats["secondary_loss.reputation"] <= rep.max))


def test_parameter_stats_per_event_mean_is_mean_of_event_draws(make_inputs):
    doc = make_inputs(freq_model="lef_direct", freq={"lef": (3.0,)}, primary={"response": (10.0, 20.0, 90.0)})
    res = simulate(load_model_inputs(doc), n=2000, seed=2)
    base = res.variants["baseline"]
    # the loss of an iteration is its events' draws summed, so the per-iteration mean times N is the loss
    got = res.parameter_stats["primary_loss.response"] * base.event_count
    assert np.allclose(got, base.annual_loss, rtol=1e-12)


def test_reproducible(sample_inputs):
    model = load_model_inputs(sample_inputs)
    a, b = simulate(model, n=3000, seed=42), simulate(model, n=3000, seed=42)
    c = simulate(model, n=3000, seed=43)
    for vid in a.variants:
        assert np.array_equal(a.variants[vid].annual_loss, b.variants[vid].annual_loss)
    assert not np.array_equal(a.variants["baseline"].annual_loss, c.variants["baseline"].annual_loss)
    assert a.seed == 42 and a.n == 3000


def test_dtypes_and_lengths(sample_inputs):
    res = simulate(load_model_inputs(sample_inputs), n=100, seed=0)
    assert list(res.variants) == ["baseline", "mfa", "mfa-sandbox"]
    for d in res.variants.values():
        assert (d.annual_loss.dtype, d.lef.dtype, d.event_count.dtype) == (np.float64, np.float64, np.int64)
        assert len(d.annual_loss) == len(d.lef) == len(d.event_count) == 100


@pytest.mark.parametrize("n,seed", [(0, 1), (-1, 1), (10, -1), (10, 2**63)])
def test_bad_arguments_raise(sample_inputs, n, seed):
    with pytest.raises(ValueError):
        simulate(load_model_inputs(sample_inputs), n=n, seed=seed)


def test_stream_key_is_blake2b_words():
    import hashlib
    import struct

    expected = struct.unpack("<4I", hashlib.blake2b(b"frequency.tef").digest()[:16])
    assert stream_key("frequency.tef") == expected
    assert stream_key("events") != stream_key("secondary_events")


def test_stream_keys_stable_across_processes():
    names = ["events", "secondary_events", "frequency.tef", "primary_loss.response", "secondary_loss.slef"]
    code = (
        "from rqharness.engine import stream_key\n"
        f"for n in {names!r}:\n    print(*stream_key(n))\n"
    )
    env = {**os.environ, "PYTHONPATH": SRC, "PYTHONHASHSEED": "777"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout
    got = [tuple(int(w) for w in line.split()) for line in out.strip().splitlines()]
    assert got == [stream_key(n) for n in names]


def test_philox_known_answer():
    z = np.zeros(1, dtype=np.uint64)
    out = engine.philox4x32(0, 0, z, z, 0, 0)
    assert [int(w[0]) for w in out] == [0x6627E8D5, 0xE169C58D, 0xBC57AC4C, 0x9B00DBD8]


def test_uniforms_depend_only_on_stream_iteration_ordinal():
    it = np.arange(5, dtype=np.int64)
    a = engine.uniforms("x", 3, it, np.zeros(5, dtype=np.int64))
    b = engine.uniforms("x", 3, it[::-1], np.zeros(5, dtype=np.int64))
    assert np.array_equal(a, b[::-1])
    assert not np.array_equal(a, engine.uniforms("y", 3, it, np.zeros(5, dtype=np.int64)))
    assert not np.array_equal(a, engine.uniforms("x", 4, it, np.zeros(5, dtype=np.int64)))
    assert np.all((a > 0) & (a < 1))


def test_uniforms_are_uniform():
    u = engine.uniforms("x", 1, np.arange(200_000, dtype=np.int64), np.zeros(200_000, dtype=np.int64))
    assert abs(u.mean() - 0.5) < 0.005 and abs(u.var() - 1 / 12) < 0.002


_TOP_BITS = 2**53 - 1


def _unit(bits: list[int]) -> np.ndarray:
    out = np.empty(len(bits), dtype=np.float64)
    engine._unit_from_bits(np.array(bits, dtype=np.uint64), out)
    return out


def test_unit_mapping_keeps_the_extreme_bits_inside_the_open_interval():
    lowest, below_top, top = _unit([0, _TOP_BITS - 1, _TOP_BITS])
    assert lowest == 2.0**-54
    assert below_top == 1 - 2.0**-52  # the clamp leaves every other value as it was
    assert top == engine.LARGEST_UNIFORM == 1 - 2.0**-53  # the largest float below 1


@pytest.mark.parametrize("lam", [5.0, 29.9, 31.0, 1000.0, float(engine.MAX_EVENT_MEAN)])
def test_poisson_inverse_is_finite_at_the_largest_uniform(lam):
    count = engine.poisson_inverse(_unit([_TOP_BITS]), np.array([lam]))[0]
    assert lam <= count < engine.ORDINAL_LIMIT


@pytest.mark.parametrize("lam", [5.0, float(engine._POISSON_DIRECT_MAX), 31.0, float(engine.MAX_EVENT_MEAN)])
@pytest.mark.parametrize("bad", [0.0, 1.0, -0.1, 1.5, np.nan, np.inf])
def test_poisson_inverse_rejects_u_outside_the_open_interval(lam, bad):
    u = np.array([0.5, bad, 0.25])
    with pytest.raises(ValueError, match=r"open interval \(0, 1\)"):
        engine.poisson_inverse(u, np.full(3, lam))


def test_poisson_inverse_equals_scipy():
    rng = np.random.default_rng(0)
    lam = np.concatenate([[0.0, 1e-12, 0.01, 0.5, 3.0, 10.0, 29.9, 30.0, 31.0, 80.0], rng.uniform(0, 60, 3000)])
    u = rng.uniform(0, 1, len(lam))
    u[:10] = [0.5, 0.999999, 1e-9, 0.3, 0.7, 0.99, 0.5, 1 - 1e-12, 0.2, 0.9]
    got = engine.poisson_inverse(u, lam)
    assert np.array_equal(got, poisson.ppf(u, lam).astype(np.int64))
    assert got.min() >= 0


def test_poisson_inverse_on_a_dense_grid_and_extremes():
    lam = np.repeat([0.1, 2.0, 10.0, 25.0], 5001)
    u = np.tile(np.concatenate([[1e-16, 1 - 1e-12], np.linspace(0.0003, 0.9997, 4999)]), 4)
    assert np.array_equal(engine.poisson_inverse(u, lam), poisson.ppf(u, lam).astype(np.int64))


def _perf_doc(make_inputs, make_variant) -> dict:
    forms = {
        "productivity": (1000.0, 5000.0, 20000.0),
        "response": (5000.0, 20000.0, 90000.0),
        "replacement": (0.0, 15000.0, 400000.0),
        "fines_and_judgments": (0.0, 10000.0, 800000.0),
        "reputation": (1000.0, 30000.0, 500000.0),
        "competitive_advantage": (0.0, 5000.0, 200000.0),
    }
    sec = {"slef": (0.05, 0.2, 0.5), "reputation": (2000.0, 50000.0, 900000.0),
           "fines_and_judgments": (0.0, 20000.0, 1000000.0)}
    return make_inputs(
        freq_model="tef_x_vulnerability",
        freq={"tef": (100.0, 180.0, 300.0)},
        vuln_model="direct_probability",
        vuln={"probability": (0.04, 0.055, 0.07)},
        primary=forms,
        secondary=sec,
        variants=[
            make_variant("vuln", {"vulnerability.probability": (0.016, 0.022, 0.028)},
                         {"vulnerability.probability": "probability"}),
            make_variant("freq", {"frequency.tef": (80.0, 140.0, 240.0)}, {"frequency.tef": "events/year"}),
        ],
    )


def test_perf_budget(make_inputs, make_variant):
    model = load_model_inputs(_perf_doc(make_inputs, make_variant))
    simulate(model, n=200, seed=1)  # warm-up: imports, table cache
    start = time.perf_counter()
    res = simulate(model, n=50_000, seed=1)
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"simulate took {elapsed:.2f}s"
    assert 8.0 < res.variants["baseline"].event_count.mean() < 12.0
    assert set(res.variants) == {"baseline", "vuln", "freq"}
