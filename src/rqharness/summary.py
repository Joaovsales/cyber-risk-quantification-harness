"""RunSummary: per-variant statistics, deltas, return on control and sensitivity.

Pure and free of timestamps so identical inputs, n, seed and version give identical bytes.
"""

from __future__ import annotations

import json

import numpy as np

from rqharness import quality
from rqharness.engine import SimulationResult
from rqharness.manifest import dumps as manifest_dumps
from rqharness.model import ModelInputs
from rqharness.pert import Pert
from rqharness.sensitivity import Sensitivity

BASELINE_LABEL = "Current controls"
LEC_POINTS = 200
HISTOGRAM_BINS = 60
_LOSS_STATS = (("p10", 0.10), ("p25", 0.25), ("p75", 0.75), ("p90", 0.90), ("p95", 0.95), ("p99", 0.99))


def _q(values: np.ndarray, q: float | np.ndarray) -> np.ndarray:
    return np.quantile(values, q, method="linear")


def _loss_stats(loss: np.ndarray, currency: str) -> dict:
    out = {"currency": currency, "mean": float(loss.mean()), "median": float(_q(loss, 0.5))}
    out.update({name: float(_q(loss, q)) for name, q in _LOSS_STATS})
    return out


def _count_stats(values: np.ndarray) -> dict:
    return {"mean": float(values.mean()), "median": float(_q(values, 0.5)), "p90": float(_q(values, 0.9))}


def _cost(pert: Pert | None, currency: str) -> dict | None:
    if pert is None:
        return None
    return {"currency": currency, "mean": pert.mean, "min": pert.min, "mode": pert.mode, "max": pert.max}


def _lec(loss: np.ndarray, currency: str) -> dict:
    xs = _q(loss, np.linspace(0.0, 0.999, LEC_POINTS))
    xs = xs[np.concatenate(([True], np.diff(xs) != 0))]
    return {"currency": currency, "points": [[float(x), float((loss > x).mean())] for x in xs]}


def _histogram(loss: np.ndarray, currency: str) -> dict:
    top = float(_q(loss, 0.995))
    if top <= 0.0:
        top = float(loss.max())
    if top <= 0.0:
        top = 1.0
    edges = np.linspace(0.0, top, HISTOGRAM_BINS + 1)
    counts, _ = np.histogram(loss, bins=edges)
    return {
        "currency": currency,
        "edges": [float(e) for e in edges],
        "counts": [int(c) for c in counts],
        "above": int((loss > top).sum()),
    }


def _variant(vid: str, label: str, draws, cost: Pert | None, currency: str) -> dict:
    loss = draws.annual_loss
    return {
        "id": vid,
        "label": label,
        "annual_loss": _loss_stats(loss, currency),
        "p_annual_loss_gt_0": float((loss > 0).mean()),
        "lef": _count_stats(draws.lef),
        "event_count": _count_stats(draws.event_count),
        "annual_cost": _cost(cost, currency),
        "lec": _lec(loss, currency),
        "histogram": _histogram(loss, currency),
    }


def estimate_at(inputs: dict, path: str) -> dict:
    """The estimate document at a dotted path such as ``primary_loss.response``."""
    node = inputs["parameters"]
    for part in path.split("."):
        node = node[part]
    return node


def _parameter(inputs: dict, model: ModelInputs, path: str, contribution: float) -> dict:
    doc = estimate_at(inputs, path)
    pert = model.baseline[path]
    provenance = doc.get("provenance") or {}
    return {
        "path": path,
        "label": doc.get("label") or path,
        "min": pert.min,
        "mode": pert.mode,
        "max": pert.max,
        "unit": doc.get("unit"),
        "tier": provenance.get("tier"),
        "source_ids": list(provenance.get("source_ids") or []),
        "contribution": contribution,
    }


def build_summary(inputs: dict, model: ModelInputs, result: SimulationResult, sens: Sensitivity) -> dict:
    currency = model.currency
    variants = [_variant("baseline", BASELINE_LABEL, result.variants["baseline"], None, currency)]
    for v in model.variants:
        variants.append(_variant(v.id, v.label, result.variants[v.id], v.annual_cost, currency))

    base = variants[0]["annual_loss"]
    deltas = []
    for v in variants[1:]:
        reduction = base["mean"] - v["annual_loss"]["mean"]
        cost = v["annual_cost"]
        deltas.append(
            {
                "variant": v["id"],
                "currency": currency,
                "ale_reduction_mean": reduction,
                "ale_reduction_p90": base["p90"] - v["annual_loss"]["p90"],
                "return_on_control": (reduction - cost["mean"]) / cost["mean"] if cost else None,
            }
        )

    parameters = [_parameter(inputs, model, p, c) for p, c in sens.contributions.items()]
    return {
        "schema_version": "1",
        "scenario_id": inputs["scenario_id"],
        "currency": currency,
        "n": int(result.n),
        "seed": int(result.seed),
        "analysis_period_years": model.years,
        "variants": variants,
        "deltas": deltas,
        "parameters": parameters,
        "sensitivity_fallback": sens.fallback,
        "quality": quality.quality_block(parameters),
    }


dumps = manifest_dumps  # one canonical JSON form for every artifact in v<N>/
