"""Run manifest: the versions and hashes that make a run reproducible. Timestamps live here, never in the summary."""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

import numpy
import scipy

import rqharness
from rqharness import engine, pert

STREAM_RULE = engine.STREAM_RULE


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_manifest(
    *, scenario_id: str, version: int, n: int, seed: int, inputs_sha256: str, generated_at: str, route: str
) -> dict:
    return {
        "schema_version": "1",
        "scenario_id": scenario_id,
        "version": version,
        "n": n,
        "seed": seed,
        "package_version": rqharness.__version__,
        "numpy_version": numpy.__version__,
        "scipy_version": scipy.__version__,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "pert_method": pert.PERT_METHOD,
        "pert_parameterization": pert.PERT_PARAMETERIZATION,
        "secondary_loss_rule_version": engine.SECONDARY_LOSS_RULE_VERSION,
        "stream_rule": STREAM_RULE,
        "inputs_sha256": inputs_sha256,
        "generated_at": generated_at,
        "route": route,
    }


def dumps(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=False, ensure_ascii=False, allow_nan=False) + "\n"
