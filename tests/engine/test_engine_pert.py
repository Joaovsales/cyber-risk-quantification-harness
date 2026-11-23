from __future__ import annotations

import numpy as np
import pytest
from scipy.special import betaincinv

from rqharness.pert import PERT_GAMMA, PERT_METHOD, Pert


def test_parameters_and_mean():
    p = Pert(10.0, 20.0, 50.0)
    assert PERT_GAMMA == 4.0
    assert p.alpha == pytest.approx(1 + 4 * 10 / 40)
    assert p.beta == pytest.approx(1 + 4 * 30 / 40)
    assert p.mean == pytest.approx((10 + 80 + 50) / 6)
    assert not p.is_degenerate and Pert(3.0, 3.0, 3.0).is_degenerate


def test_method_name_is_stated():
    assert PERT_METHOD == "beta_pert_gamma_4_quantile_table_4096_linear"


def test_degenerate_ppf_is_constant():
    out = Pert(7.0, 7.0, 7.0).ppf(np.array([1e-9, 0.5, 1 - 1e-9]))
    assert np.array_equal(out, [7.0, 7.0, 7.0])


@pytest.mark.parametrize("lo,mode,hi", [(0, 1, 10), (0, 5, 10), (0, 10, 10), (0, 0, 10), (100, 150, 5000)])
def test_ppf_matches_exact_quantile_within_tolerance_and_is_monotone(lo, mode, hi):
    p = Pert(float(lo), float(mode), float(hi))
    u = np.linspace(1e-6, 1 - 1e-6, 20001)
    got = p.ppf(u)
    exact = lo + (hi - lo) * betaincinv(p.alpha, p.beta, u)
    assert np.max(np.abs(got - exact)) <= 1e-4 * (hi - lo)
    assert np.all(np.diff(got) >= 0) and got.min() >= lo and got.max() <= hi
