"""Vectorised Monte Carlo engine with common random numbers.

Semantics follow the predecessor engine's ADR 0002 rules. Per iteration i the loss
event frequency (LEF) comes from the frequency model, the event count is
N ~ Poisson(LEF x years), each event draws every primary loss form, and, when the
secondary block is present, each primary event draws k ~ Poisson(lambda_s) secondary
events (lambda_s drawn once per iteration from `secondary_loss.slef`) which each draw
every secondary form. Annual loss is the horizon total divided by years.

Common random numbers. Every draw is the inverse CDF of one uniform, and a uniform
depends only on (stream, seed, iteration, ordinal). A stream is a name: an estimate
path, `events` or `secondary_events`. The uniform comes from Philox4x32-10 with

    key     = (w0, w1)                      from the stream key
    counter = (ordinal, iteration, w2 ^ seed_lo, w3 ^ seed_hi)

where (w0..w3) are the first sixteen bytes of blake2b(name) read as little-endian
uint32 words and seed_lo / seed_hi are the halves of the seed. So the counter's low
64 bits are `iteration * 2**32 + ordinal`, and the seed enters through the counter's
high words (the stream key stays a pure function of the name).

Ordinals: per-iteration estimates, and `events` use ordinal 0;
primary form p of event j uses ordinal j; `secondary_events` uses j; secondary form q
of the m-th secondary event of primary event j uses `j * 2**16 + m` (this repository's
extension, which keeps secondary draws addressable per event). Each of j and m must
stay below 2**16.

A variant evaluates its overridden estimates on the same uniforms as the baseline, so
it differs only through what it overrides. Magnitudes are computed once for
max_v N_v(i) events per iteration (a ragged layout over the valid cells of the padded
[n, max_events] grid) and a variant that overrides no magnitude estimate reuses them.
"""

from __future__ import annotations

import hashlib
import struct
import sys
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Literal

import numpy as np
from scipy.stats import poisson

from rqharness.model import USES_VULNERABILITY, ModelInputs
from rqharness.pert import Pert

# Recorded in every manifest: change them together with the code they describe.
STREAM_RULE = "philox4x32-10; key=blake2b(name)[0:16]; counter=(ordinal, iteration, w2^seed_lo, w3^seed_hi)"
SECONDARY_LOSS_RULE_VERSION = "v1_poisson_per_primary"

# Events per iteration, and secondary events per primary event, are 16-bit ordinals.
ORDINAL_LIMIT = 1 << 16
# The largest value `uniforms` returns: the largest float below 1 (see _unit_from_bits).
LARGEST_UNIFORM = np.nextafter(1.0, 0.0)
# The largest Poisson mean validation admits for either count. Even LARGEST_UNIFORM
# draws Poisson(63,000) to about 65,050 < ORDINAL_LIMIT, so for validated inputs
# the guards in _EventCells never fire, whatever n is.
MAX_EVENT_MEAN = 63_000
# The most event cells (primary plus secondary events, over every iteration) a run may
# expect; see event_budget. Peak memory measured 13 to 93 bytes per cell, the high end
# with all twelve loss forms, so the budget keeps a simulation under about 4 GB.
MAX_EVENT_CELLS = 40_000_000

_CHUNK = 1 << 17
_M0, _M1 = np.uint64(0xD2511F53), np.uint64(0xCD9E8D57)
_W0, _W1 = 0x9E3779B9, 0xBB67AE85
_MASK = np.uint64(0xFFFFFFFF)
_S32, _S5, _S6, _S26 = np.uint64(32), np.uint64(5), np.uint64(6), np.uint64(26)
_INV_2_53 = 2.0**-53
_POISSON_DIRECT_MAX = 30.0
_POISSON_TAIL = 1e-18


def stream_key(name: str) -> tuple[int, int, int, int]:
    """Four little-endian uint32 words of blake2b(name); identical in every process."""
    return struct.unpack("<4I", hashlib.blake2b(name.encode("utf-8")).digest()[:16])


def _philox_rounds(a, b, c, d, key0: int, key1: int) -> tuple:
    """Ten Philox4x32 rounds on uint64 buffers holding 32-bit words; buffers are reused."""
    t0, t1 = np.empty_like(a), np.empty_like(a)
    for _ in range(10):
        k0, k1 = np.uint64(key0), np.uint64(key1)
        np.multiply(a, _M0, out=t0)
        np.multiply(c, _M1, out=t1)
        np.right_shift(t1, _S32, out=c)
        np.bitwise_xor(c, b, out=c)
        np.bitwise_xor(c, k0, out=c)
        np.bitwise_and(t1, _MASK, out=b)
        np.right_shift(t0, _S32, out=t1)
        np.bitwise_xor(t1, d, out=t1)
        np.bitwise_xor(t1, k1, out=t1)
        np.bitwise_and(t0, _MASK, out=d)
        a, c, t0, t1 = c, t1, a, t0
        key0, key1 = (key0 + _W0) & 0xFFFFFFFF, (key1 + _W1) & 0xFFFFFFFF
    return a, b, c, d


def philox4x32(key0: int, key1: int, c0, c1, c2, c3) -> tuple[np.ndarray, ...]:
    """Philox4x32-10 output words for counters (c0, c1, c2, c3); arrays or ints."""
    shape = np.broadcast(*(np.asarray(c) for c in (c0, c1, c2, c3))).shape
    words = [np.array(np.broadcast_to(np.asarray(c, dtype=np.uint64), shape)) for c in (c0, c1, c2, c3)]
    return _philox_rounds(*words, key0, key1)


def uniforms(name: str, seed: int, iteration: np.ndarray, ordinal: np.ndarray) -> np.ndarray:
    """Uniforms in the open interval (0, 1) for (stream `name`, seed, iteration, ordinal)."""
    w0, w1, w2, w3 = stream_key(name)
    c2 = np.uint64(w2 ^ (seed & 0xFFFFFFFF))
    c3 = np.uint64(w3 ^ (seed >> 32))
    out = np.empty(len(iteration), dtype=np.float64)
    for lo in range(0, len(iteration), _CHUNK):
        hi = min(lo + _CHUNK, len(iteration))
        a = ordinal[lo:hi].astype(np.uint64)
        b = iteration[lo:hi].astype(np.uint64)
        c = np.full(hi - lo, c2, dtype=np.uint64)
        d = np.full(hi - lo, c3, dtype=np.uint64)
        x0, x1, _, _ = _philox_rounds(a, b, c, d, w0, w1)
        np.right_shift(x0, _S5, out=x0)
        np.left_shift(x0, _S26, out=x0)
        np.right_shift(x1, _S6, out=x1)
        np.add(x0, x1, out=x0)
        _unit_from_bits(x0, out[lo:hi])
    return out


def _unit_from_bits(bits: np.ndarray, out: np.ndarray) -> None:
    """Write (bits + 1/2) / 2**53 for 53-bit `bits` into `out`, inside [2**-54, 1 - 2**-53].

    At bits = 2**53 - 1 the float64 sum rounds up to 2**53, so the top is clamped to the
    largest float below 1; every other value is left exactly as the plain mapping gives it.
    """
    out[:] = bits
    out += 0.5
    out *= _INV_2_53
    np.minimum(out, LARGEST_UNIFORM, out=out)


def poisson_inverse(u: np.ndarray, lam: np.ndarray) -> np.ndarray:
    """Smallest k with Poisson(lam) CDF(k) >= u; equals scipy's ppf for u in (0, 1).

    Any other u (0, 1, outside, NaN) raises ValueError: the engine's uniforms never produce
    one, and scipy would turn 1 into inf, which the int64 cast makes the int64 minimum.
    """
    u = np.asarray(u, dtype=np.float64)
    lam = np.asarray(lam, dtype=np.float64)
    if u.size and not (u.min() > 0.0 and u.max() < 1.0):  # NaN fails both comparisons
        bad = u.flat[np.flatnonzero(~((u > 0.0) & (u < 1.0)))[0]]
        raise ValueError(f"poisson_inverse needs u in the open interval (0, 1), got {float(bad)!r}")
    out = np.zeros(u.shape, dtype=np.int64)
    big = lam > _POISSON_DIRECT_MAX
    if big.any():
        out[big] = poisson.ppf(u[big], lam[big])
    small = np.flatnonzero(~big)
    p = np.exp(-lam[small])
    act = np.flatnonzero(u[small] > p)
    idx, lam_a, u_a, p_a, cdf_a = small[act], lam[small][act], u[small][act], p[act], p[act]
    step = 0
    while idx.size:
        step += 1
        p_a = p_a * lam_a / step
        cdf_a = cdf_a + p_a
        done = (cdf_a >= u_a) | ((p_a < _POISSON_TAIL) & (step > lam_a))
        out[idx[done]] = step
        keep = ~done
        idx, lam_a, u_a, p_a, cdf_a = idx[keep], lam_a[keep], u_a[keep], p_a[keep], cdf_a[keep]
    return out


@dataclass(frozen=True)
class VariantDraws:
    annual_loss: np.ndarray
    lef: np.ndarray
    event_count: np.ndarray


@dataclass(frozen=True)
class SimulationResult:
    n: int
    seed: int
    variants: dict[str, VariantDraws]
    parameter_stats: dict[str, np.ndarray]


class _Secondary:
    """Secondary events of the ragged cells: geometry, form draws and per-event totals."""

    def __init__(self, event: np.ndarray, iteration: np.ndarray, forms: dict[str, np.ndarray], totals: np.ndarray):
        self.event, self.iteration, self.forms, self.totals = event, iteration, forms, totals


def _lef(frequency_model: str, vulnerability_model: str | None, estimate: Callable[[str], np.ndarray],
         *, upper_bound: bool = False) -> np.ndarray:
    """The frequency model's LEF, with `estimate(path)` giving one array per estimate path.

    `upper_bound` says the estimates are upper bounds and asks for the LEF's: the share
    tcap / (tcap + rs) is then taken as 1, its own bound, and neither estimate is read (the
    share of the maxima is not the maximum share; see expected_events).
    """
    if frequency_model == "lef_direct":
        return estimate("frequency.lef")
    if frequency_model == "tef_x_vulnerability":
        rate = estimate("frequency.tef")
    else:
        rate = estimate("frequency.contact") * np.clip(estimate("frequency.action"), 0.0, 1.0)
    if frequency_model not in USES_VULNERABILITY:
        return rate
    if vulnerability_model == "direct_probability":
        v = np.clip(estimate("vulnerability.probability"), 0.0, 1.0)
    elif upper_bound:
        v = np.ones(1)
    else:
        tcap, rs = estimate("vulnerability.threat_capability"), estimate("vulnerability.resistance_strength")
        total = tcap + rs
        v = np.divide(tcap, total, out=np.zeros_like(total), where=total > 0)
    return rate * v


@dataclass(frozen=True)
class Statistic:
    """A statistic of each estimate that expected_events evaluates the LEF formula on."""

    attribute: str  # the Pert attribute it reads
    upper_bound: bool  # whether it bounds every estimate from above, so the LEF on it bounds the LEF


# Every statistic expected_events accepts. A new one must say whether it is an upper bound,
# which decides how the tcap share is treated (_lef's upper_bound).
STATISTICS = MappingProxyType({
    "mean": Statistic("mean", upper_bound=False),  # the memory budget's size (event_budget)
    "max": Statistic("max", upper_bound=True),  # validation's expected_events rule
})


@dataclass(frozen=True)
class ExpectedEvents:
    """Primary events one iteration expects, from one statistic of each estimate."""

    per_iteration: float
    estimates: tuple[str, ...]  # the estimate paths it was computed from, the rate first


def expected_events(frequency_model: str, vulnerability_model: str | None, years: float,
                    estimate: Callable[[str], Pert], statistic: Literal["mean", "max"]) -> ExpectedEvents:
    """The LEF formula on `statistic` of each estimate, times years, drawing nothing.

    `estimate(path)` gives one scope's estimate, so a caller passes the baseline or a variant
    without building a ModelInputs (validation runs before load_model_inputs).

    - An upper-bound statistic (STATISTICS) bounds the Poisson mean of the event count from
      above: the LEF grows with every rate and probability, each at most its bound, and the
      share tcap / (tcap + rs) is at most 1, so it is taken as 1 and neither estimate is read.
    - Any other statistic gives the LEF formula on it; on "mean" that is E[LEF] x years, exact
      for a product of independent estimates and a close estimate for the tcap share.
    """
    stat = STATISTICS[statistic]
    read: list[str] = []

    def value(path: str) -> np.ndarray:
        read.append(path)
        return np.array([getattr(estimate(path), stat.attribute)], dtype=float)

    lef = _lef(frequency_model, vulnerability_model, value, upper_bound=stat.upper_bound)
    return ExpectedEvents(float(lef[0]) * years, tuple(read))


def _effective(model: ModelInputs) -> dict[str, dict[str, Pert]]:
    """Each variant id, the baseline first, with the estimates it simulates."""
    return {"baseline": model.baseline, **{v.id: {**model.baseline, **v.overrides} for v in model.variants}}


@dataclass(frozen=True)
class EventBudget:
    """The event cells one iteration of a model is expected to lay out, against MAX_EVENT_CELLS."""

    cells_per_iteration: float

    def cells(self, n: int) -> float:
        return n * self.cells_per_iteration

    def fits(self, n: int) -> bool:
        return self.cells(n) <= MAX_EVENT_CELLS

    @property
    def max_n(self) -> int:
        """The largest n that fits; 0 when even one iteration is over the budget."""
        if self.cells_per_iteration <= 0:
            return sys.maxsize
        return int(MAX_EVENT_CELLS // self.cells_per_iteration)


def event_budget(model: ModelInputs) -> EventBudget:
    """The model's expected event cells per iteration, estimated without drawing anything.

    Per variant: expected_events on the PERT means (E[LEF] x years primary events), each
    bringing E[slef] secondary events when the secondary block is present, summed over the
    baseline and every variant (an upper bound on the shared layout that also covers
    per-variant arrays).
    """
    per_iteration = 0.0
    for eff in _effective(model).values():
        events = expected_events(model.frequency_model, model.vulnerability_model, model.years,
                                 eff.__getitem__, "mean").per_iteration
        if "secondary_loss.slef" in eff:
            events *= 1.0 + eff["secondary_loss.slef"].mean
        per_iteration += events
    return EventBudget(per_iteration)


class _IterationDraws:
    """Per-iteration draws: estimates at ordinal 0, the LEF they give and the event count it gives."""

    def __init__(self, model: ModelInputs, n: int, seed: int):
        self.model, self.n, self.seed = model, n, seed
        self.ids = np.arange(n, dtype=np.int64)
        self._draws: dict[tuple[str, Pert], np.ndarray] = {}
        self._u_events: np.ndarray | None = None

    def iter_draw(self, path: str, pert: Pert) -> np.ndarray:
        key = (path, pert)
        if key not in self._draws:
            u = uniforms(path, self.seed, self.ids, np.zeros(self.n, dtype=np.int64))
            self._draws[key] = pert.ppf(u)
        return self._draws[key]

    def lef(self, eff: dict[str, Pert]) -> np.ndarray:
        m = self.model
        return _lef(m.frequency_model, m.vulnerability_model, lambda path: self.iter_draw(path, eff[path]))

    def event_count(self, lef: np.ndarray) -> np.ndarray:
        """N ~ Poisson(LEF x years) on the shared `events` stream."""
        if self._u_events is None:
            self._u_events = uniforms("events", self.seed, self.ids, np.zeros(self.n, dtype=np.int64))
        return poisson_inverse(self._u_events, lef * self.model.years)


class _EventCells:
    """Event draws over the ragged layout of the valid cells of the padded [n, max_events] grid.

    `counts` holds each variant's event count per iteration. The layout is their
    elementwise maximum, so every variant's events have cells and a variant with fewer
    events masks the rest. Every cache here is valid for this one layout, which is why the
    layout is built in the constructor and nowhere else.
    """

    def __init__(self, draws: _IterationDraws, counts: dict[str, np.ndarray]):
        layout = np.maximum.reduce(list(counts.values()))
        if layout.size and layout.max() >= ORDINAL_LIMIT:
            raise ValueError("an iteration has 65,536 or more events")
        self._iteration, self._counts = draws, dict(counts)
        self._n, self._seed, self._years = draws.n, draws.seed, draws.model.years
        self._baseline = draws.model.baseline
        self._cell_iter = np.repeat(draws.ids, layout)
        starts = np.cumsum(layout) - layout
        self._cell_j = np.arange(len(self._cell_iter), dtype=np.int64) - np.repeat(starts, layout)
        self._primary_paths = [p for p in self._baseline if p.startswith("primary_loss.")]
        self._secondary_forms = [
            p for p in self._baseline if p.startswith("secondary_loss.") and not p.endswith(".slef")
        ]
        self._has_secondary = "secondary_loss.slef" in self._baseline
        self._cell_draws: dict[tuple[str, Pert], np.ndarray] = {}
        self._k: dict[Pert, np.ndarray] = {}
        self._sec: dict[tuple, _Secondary] = {}
        self._totals: dict[tuple, np.ndarray] = {}

    def annual_loss(self, variant_id: str, eff: dict[str, Pert]) -> np.ndarray:
        """Horizon loss of the variant's events in each iteration, divided by years."""
        weights = np.where(self._in_variant(variant_id), self._event_totals(eff), 0.0)
        return np.bincount(self._cell_iter, weights=weights, minlength=self._n) / self._years

    def parameter_stats(self) -> dict[str, np.ndarray]:
        """Per-iteration value of each baseline estimate; per-event estimates averaged over the events."""
        base, stats = self._baseline, {}
        in_base = self._in_variant("baseline")
        for path, pert in base.items():
            if path in self._primary_paths:
                stats[path] = self._event_mean(self._cell_iter, self._cell_draw(path, pert), in_base, pert)
            elif path in self._secondary_forms:
                sec = self._secondary(base)
                mask = in_base[sec.event]
                stats[path] = self._event_mean(sec.iteration, sec.forms[path], mask, pert)
            else:
                stats[path] = self._iteration.iter_draw(path, pert)
        return stats

    def _in_variant(self, variant_id: str) -> np.ndarray:
        return self._cell_j < self._counts[variant_id][self._cell_iter]

    def _cell_draw(self, path: str, pert: Pert) -> np.ndarray:
        key = (path, pert)
        if key not in self._cell_draws:
            self._cell_draws[key] = pert.ppf(uniforms(path, self._seed, self._cell_iter, self._cell_j))
        return self._cell_draws[key]

    def _secondary(self, eff: dict[str, Pert]) -> _Secondary:
        slef = eff["secondary_loss.slef"]
        key = (slef, *(eff[p] for p in self._secondary_forms))
        if key in self._sec:
            return self._sec[key]
        if slef not in self._k:
            u = uniforms("secondary_events", self._seed, self._cell_iter, self._cell_j)
            lam_s = self._iteration.iter_draw("secondary_loss.slef", slef)
            self._k[slef] = poisson_inverse(u, lam_s[self._cell_iter])
        k = self._k[slef]
        if k.size and k.max() >= ORDINAL_LIMIT:
            raise ValueError("a primary event has 65,536 or more secondary events")
        event = np.repeat(np.arange(len(k), dtype=np.int64), k)
        m = np.arange(len(event), dtype=np.int64) - np.repeat(np.cumsum(k) - k, k)
        iteration = self._cell_iter[event]
        ordinal = self._cell_j[event] * ORDINAL_LIMIT + m
        forms, per_event = {}, np.zeros(len(event))
        for path in self._secondary_forms:
            forms[path] = eff[path].ppf(uniforms(path, self._seed, iteration, ordinal))
            per_event += forms[path]
        totals = np.bincount(event, weights=per_event, minlength=len(k))
        self._sec[key] = _Secondary(event, iteration, forms, totals)
        return self._sec[key]

    def _event_totals(self, eff: dict[str, Pert]) -> np.ndarray:
        key = (tuple(eff[p] for p in self._primary_paths), *(
            (eff["secondary_loss.slef"], *(eff[p] for p in self._secondary_forms)) if self._has_secondary else ()
        ))
        if key not in self._totals:
            total = np.zeros(len(self._cell_iter))
            for path in self._primary_paths:
                total += self._cell_draw(path, eff[path])
            if self._has_secondary:
                total += self._secondary(eff).totals
            self._totals[key] = total
        return self._totals[key]

    def _event_mean(self, iteration: np.ndarray, draws: np.ndarray, mask: np.ndarray, pert: Pert) -> np.ndarray:
        sums = np.bincount(iteration, weights=np.where(mask, draws, 0.0), minlength=self._n)
        counts = np.bincount(iteration, weights=mask, minlength=self._n)
        return np.divide(sums, counts, out=np.full(self._n, pert.mean), where=counts > 0)


def simulate(model: ModelInputs, *, n: int, seed: int) -> SimulationResult:
    """Simulate the baseline and every variant on shared uniforms."""
    if not isinstance(n, (int, np.integer)) or n < 1:
        raise ValueError("n must be an integer >= 1")
    if not isinstance(seed, (int, np.integer)) or not 0 <= seed < 2**63:
        raise ValueError("seed must be an integer in [0, 2**63)")
    n, seed = int(n), int(seed)
    draws = _IterationDraws(model, n, seed)
    effective = _effective(model)

    lefs = {vid: draws.lef(eff) for vid, eff in effective.items()}
    counts = {vid: draws.event_count(lef) for vid, lef in lefs.items()}
    cells = _EventCells(draws, counts)

    variants = {
        vid: VariantDraws(cells.annual_loss(vid, eff), lefs[vid], counts[vid]) for vid, eff in effective.items()
    }
    return SimulationResult(n, seed, variants, cells.parameter_stats())
