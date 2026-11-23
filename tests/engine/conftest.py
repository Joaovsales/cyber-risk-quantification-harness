from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SAMPLE = Path(__file__).parents[1] / "validate" / "fixtures" / "sample-run" / "inputs.yaml"


def est(lo: float, mode: float | None = None, hi: float | None = None, unit: str = "USD") -> dict:
    """An estimate document; one argument gives a degenerate (constant) PERT."""
    mode = lo if mode is None else mode
    hi = mode if hi is None else hi
    return {
        "min": lo,
        "mode": mode,
        "max": hi,
        "unit": unit,
        "provenance": {"tier": "agent_assumption", "source_ids": []},
    }


FREQ_UNITS = {"lef": "events/year", "tef": "events/year", "contact": "events/year", "action": "probability"}
VULN_UNITS = {"probability": "probability", "threat_capability": "score", "resistance_strength": "score"}


def inputs_doc(
    *,
    freq_model: str,
    freq: dict,
    vuln_model: str | None = None,
    vuln: dict | None = None,
    primary: dict | None = None,
    secondary: dict | None = None,
    years: float = 1,
    variants: list | None = None,
) -> dict:
    frequency = {"model": freq_model, **{k: est(*v, unit=FREQ_UNITS[k]) for k, v in freq.items()}}
    params: dict = {"analysis_period_years": years, "frequency": frequency}
    if vuln_model:
        params["vulnerability"] = {
            "model": vuln_model,
            **{k: est(*v, unit=VULN_UNITS[k]) for k, v in vuln.items()},
        }
    params["primary_loss"] = {k: est(*v) for k, v in (primary or {"response": (1000,)}).items()}
    if secondary:
        sec = {"slef": est(*secondary["slef"], unit="events/event")}
        sec.update({k: est(*v) for k, v in secondary.items() if k != "slef"})
        params["secondary_loss"] = sec
    return {
        "schema_version": "1",
        "scenario_id": "x",
        "currency": "USD",
        "parameters": params,
        "sources": [],
        "variants": variants or [],
    }


def variant(vid: str, overrides: dict, unit_of: dict | None = None) -> dict:
    """A variant whose overrides map an estimate path to a (min, mode, max) tuple."""
    units = unit_of or {}
    return {
        "id": vid,
        "label": vid,
        "overrides": {p: est(*v, unit=units.get(p, "USD")) for p, v in overrides.items()},
    }


@pytest.fixture
def sample_inputs() -> dict:
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def make_inputs():
    return inputs_doc


@pytest.fixture
def make_variant():
    return variant
