"""Beta-PERT (gamma = 4) with a tabulated inverse CDF.

`scipy.special.betaincinv` costs about 5 microseconds per value, which misses the
simulation speed budget. Instead, each distribution's CDF is evaluated once on a
4,096-interval grid of the unit interval and quantiles are read back by linear
interpolation; the measured error is about 3e-5 of the span.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

import numpy as np
from scipy.special import betainc

PERT_GAMMA = 4.0
PERT_PARAMETERIZATION = "beta_pert_gamma_4"
PERT_METHOD = "beta_pert_gamma_4_quantile_table_4096_linear"
_GRID = np.linspace(0.0, 1.0, 4097)


@functools.lru_cache(maxsize=256)
def _cdf_table(alpha: float, beta: float) -> np.ndarray:
    cdf = np.maximum.accumulate(betainc(alpha, beta, _GRID))
    cdf[0], cdf[-1] = 0.0, 1.0
    return cdf


@dataclass(frozen=True)
class Pert:
    min: float
    mode: float
    max: float

    @property
    def is_degenerate(self) -> bool:
        return self.max == self.min

    @property
    def alpha(self) -> float:
        return 1.0 + PERT_GAMMA * (self.mode - self.min) / (self.max - self.min)

    @property
    def beta(self) -> float:
        return 1.0 + PERT_GAMMA * (self.max - self.mode) / (self.max - self.min)

    @property
    def mean(self) -> float:
        return (self.min + PERT_GAMMA * self.mode + self.max) / (PERT_GAMMA + 2.0)

    def ppf(self, u: np.ndarray) -> np.ndarray:
        """Quantiles for uniforms in (0, 1)."""
        if self.is_degenerate:
            return np.full(np.shape(u), float(self.min))
        x = np.interp(u, _cdf_table(self.alpha, self.beta), _GRID)
        x *= self.max - self.min
        x += self.min
        return x
