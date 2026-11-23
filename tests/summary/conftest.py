from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from rqharness import engine, model  # noqa: E402
from rqharness.sensitivity import contributions  # noqa: E402
from rqharness.summary import build_summary  # noqa: E402

SAMPLE = Path(__file__).parents[1] / "validate" / "fixtures" / "sample-run" / "inputs.yaml"
N = 20_000
SEED = 20261109


def summarise(inputs: dict, n: int = N, seed: int = SEED) -> dict:
    mi = model.load_model_inputs(inputs)
    res = engine.simulate(mi, n=n, seed=seed)
    return build_summary(inputs, mi, res, contributions(res))


@pytest.fixture(scope="session")
def sample_doc() -> dict:
    return yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def sample_summary(sample_doc) -> dict:
    return summarise(sample_doc)
