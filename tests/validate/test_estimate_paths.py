"""The estimate-path vocabulary is written in the model and in several schemas: they must agree."""

from __future__ import annotations

import json
import re
from importlib import resources

from rqharness.model import (
    ESTIMATE_PATHS,
    FREQUENCY_ESTIMATES,
    LOSS_FORMS,
    USES_VULNERABILITY,
    VULNERABILITY_ESTIMATES,
)


def _schemas() -> dict[str, object]:
    folder = resources.files("rqharness") / "schemas"
    return {p.name: json.loads(p.read_text(encoding="utf-8")) for p in folder.iterdir() if p.name.endswith(".json")}


def _enumerations(node: object, where: str = ""):
    """Every regex alternation and every property set that lists estimate paths."""
    if isinstance(node, dict):
        if "frequency.lef" in node:
            yield where, set(node)
        pattern = node.get("pattern")
        if isinstance(pattern, str) and pattern.startswith("^(frequency"):
            yield where + ".pattern", set(re.fullmatch(r"\^\((.*)\)\$", pattern).group(1).replace("\\.", ".").split("|"))
        for key, value in node.items():
            yield from _enumerations(value, f"{where}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _enumerations(value, f"{where}[{i}]")


def _per_model_estimates(block: dict) -> dict[str, set[str]]:
    """model -> the estimates the schema requires for it, from the block's allOf if/then branches."""
    out = {}
    for branch in block["allOf"]:
        (model,) = branch["if"]["properties"]["model"]["enum"]
        forbidden = {k for k, v in branch["then"].get("properties", {}).items() if v == {"not": {}}}
        assert set(branch["then"]["required"]) == set(block["properties"]) - {"model"} - forbidden, model
        out[model] = set(branch["then"]["required"])
    return out


def test_the_model_tables_match_the_inputs_schema():
    """D30: the schema owns the rules; the read tables the engine computes with must agree with it."""
    params = json.loads((resources.files("rqharness") / "schemas" / "inputs.v1.json").read_text(encoding="utf-8"))
    params = params["properties"]["parameters"]
    blocks = params["properties"]
    assert _per_model_estimates(blocks["frequency"]) == {m: set(e) for m, e in FREQUENCY_ESTIMATES.items()}
    assert _per_model_estimates(blocks["vulnerability"]) == {m: set(e) for m, e in VULNERABILITY_ESTIMATES.items()}
    assert set(blocks["frequency"]["properties"]["model"]["enum"]) == set(FREQUENCY_ESTIMATES)
    assert set(blocks["vulnerability"]["properties"]["model"]["enum"]) == set(VULNERABILITY_ESTIMATES)
    assert set(params["if"]["properties"]["frequency"]["properties"]["model"]["enum"]) == USES_VULNERABILITY
    assert params["then"] == {"required": ["vulnerability"]}
    assert params["else"] == {"properties": {"vulnerability": {"not": {}}}}
    for loss in ("primary_loss", "secondary_loss"):
        assert set(blocks[loss]["properties"]) - {"slef"} == set(LOSS_FORMS)


def test_the_model_knows_twenty_estimate_paths():
    assert len(ESTIMATE_PATHS) == 20


def test_every_schema_enumeration_equals_the_model_paths():
    found = [(name, where, paths) for name, schema in _schemas().items() for where, paths in _enumerations(schema)]
    assert len(found) >= 6  # run route_overrides, inputs overrides, requests x2, library-entry, connector-map
    for name, where, paths in found:
        assert paths == ESTIMATE_PATHS, f"{name}{where}: {sorted(paths ^ ESTIMATE_PATHS)}"
