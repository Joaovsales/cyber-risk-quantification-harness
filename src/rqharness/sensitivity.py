"""Variance-contribution sensitivity: normalised squared Spearman correlation with baseline loss."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import rankdata

from rqharness.engine import SimulationResult


@dataclass(frozen=True)
class Sensitivity:
    contributions: dict[str, float]
    fallback: bool


def _squared_spearman(x: np.ndarray, y_ranks: np.ndarray) -> float:
    """Squared Pearson correlation of the ranks; a constant series has correlation 0."""
    x_ranks = rankdata(x)
    xc = x_ranks - x_ranks.mean()
    yc = y_ranks - y_ranks.mean()
    denom = float(np.sqrt((xc @ xc) * (yc @ yc)))
    if denom == 0.0:
        return 0.0
    return float((xc @ yc) / denom) ** 2


def contributions(result: SimulationResult) -> Sensitivity:
    """Contribution of each parameter to baseline annual loss, over the same n iterations."""
    loss_ranks = rankdata(result.variants["baseline"].annual_loss)
    raw = {path: _squared_spearman(draws, loss_ranks) for path, draws in result.parameter_stats.items()}
    total = sum(raw.values())
    if total == 0.0:
        equal = 1.0 / len(raw)
        return Sensitivity({path: equal for path in raw}, fallback=True)
    return Sensitivity({path: value / total for path, value in raw.items()}, fallback=False)
