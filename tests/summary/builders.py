"""Inputs-document builders for sensitivity fixtures (copied from the engine tests)."""

from __future__ import annotations


def est(lo: float, mode: float | None = None, hi: float | None = None, unit: str = "USD") -> dict:
    mode = lo if mode is None else mode
    hi = mode if hi is None else hi
    return {
        "min": lo,
        "mode": mode,
        "max": hi,
        "unit": unit,
        "provenance": {"tier": "agent_assumption", "source_ids": []},
    }


def lef_doc(lef: tuple, primary: dict) -> dict:
    params = {
        "analysis_period_years": 1,
        "frequency": {"model": "lef_direct", "lef": est(*lef, unit="events/year")},
        "primary_loss": {k: est(*v) for k, v in primary.items()},
    }
    return {
        "schema_version": "1",
        "scenario_id": "x",
        "currency": "USD",
        "parameters": params,
        "sources": [],
        "variants": [],
    }
