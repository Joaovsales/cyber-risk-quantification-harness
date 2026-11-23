from __future__ import annotations

import copy

import pytest

from rqharness import library
from rqharness.model import load_model_inputs
from rqharness.pert import Pert
from rqharness.validate import validate_inputs


def test_sample_loads(sample_inputs):
    m = load_model_inputs(sample_inputs)
    assert (m.currency, m.years) == ("USD", 1)
    assert (m.frequency_model, m.vulnerability_model) == ("tef_x_vulnerability", "direct_probability")
    assert list(m.baseline) == [
        "frequency.tef",
        "vulnerability.probability",
        "primary_loss.productivity",
        "primary_loss.response",
        "primary_loss.replacement",
        "secondary_loss.slef",
        "secondary_loss.fines_and_judgments",
        "secondary_loss.reputation",
    ]
    assert m.baseline["frequency.tef"] == Pert(150, 400, 900)
    assert m.variant_ids == ("baseline", "mfa", "mfa-sandbox")
    v = m.variants[1]
    assert (v.id, v.label) == ("mfa-sandbox", "MFA + mail sandboxing")
    assert set(v.overrides) == {"vulnerability.probability", "frequency.tef"}
    assert v.annual_cost == Pert(180000, 210000, 240000)


def test_years_default_is_one(sample_inputs):
    del sample_inputs["parameters"]["analysis_period_years"]
    assert load_model_inputs(sample_inputs).years == 1


# --- D30: the engine trusts validated documents ------------------------------------------
# load_model_inputs keeps only structural reads. Every rule it relies on is owned by the
# inputs schema or the cross-reference rules, and each case below proves validation rejects
# an input that would otherwise reach the engine malformed.

P = "inputs.parameters."


def _set(*keys, value):
    def mutate(d):
        for k in keys[:-1]:
            d = d[k]
        d[keys[-1]] = value
    return mutate


def _pop(*keys):
    def mutate(d):
        for k in keys[:-1]:
            d = d[k]
        d.pop(keys[-1])
    return mutate


def _copy_to(src: tuple, dst: tuple):
    def mutate(d):
        node = d
        for k in src:
            node = node[k]
        _set(*dst, value=copy.deepcopy(node))(d)
    return mutate


def _vulnerability_on_lef_direct(d):
    freq = d["parameters"]["frequency"]
    freq["model"] = "lef_direct"
    freq["lef"] = freq.pop("tef")


ENGINE_TRUSTS = [
    # the frequency-model and vulnerability-model enums
    ("frequency model enum", _set("parameters", "frequency", "model", value="nope"),
     P + "frequency.model", "enum"),
    ("vulnerability model enum", _set("parameters", "vulnerability", "model", value="nope"),
     P + "vulnerability.model", "enum"),
    # the exact estimate set per model
    ("frequency estimate missing", _pop("parameters", "frequency", "tef"),
     P + "frequency.tef", "required"),
    ("frequency estimate of another model", _copy_to(("parameters", "frequency", "tef"), ("parameters", "frequency", "lef")),
     P + "frequency.lef", "forbidden"),
    ("vulnerability block missing", _pop("parameters", "vulnerability"),
     P + "vulnerability", "required"),
    ("vulnerability block not used by the frequency model", _vulnerability_on_lef_direct,
     P + "vulnerability", "forbidden"),
    ("vulnerability estimate missing", _pop("parameters", "vulnerability", "probability"),
     P + "vulnerability.probability", "required"),
    ("vulnerability estimate of another model",
     _copy_to(("parameters", "vulnerability", "probability"), ("parameters", "vulnerability", "threat_capability")),
     P + "vulnerability.threat_capability", "forbidden"),
    ("no primary loss form", _set("parameters", "primary_loss", value={}),
     P + "primary_loss", "minProperties"),
    ("unknown primary loss form", _copy_to(("parameters", "primary_loss", "response"), ("parameters", "primary_loss", "other")),
     P + "primary_loss.other", "additionalProperties"),
    ("secondary loss without slef", _pop("parameters", "secondary_loss", "slef"),
     P + "secondary_loss.slef", "required"),
    ("secondary loss with no loss form",
     lambda d: d["parameters"].__setitem__("secondary_loss", {"slef": d["parameters"]["secondary_loss"]["slef"]}),
     P + "secondary_loss", "minProperties"),
    ("estimate without a mode", _pop("parameters", "frequency", "tef", "mode"),
     P + "frequency.tef.mode", "required"),
    ("override of an estimate absent from the baseline",
     _copy_to(("parameters", "primary_loss", "response"), ("variants", 0, "overrides", "primary_loss.fines_and_judgments")),
     "inputs.variants.0.overrides.primary_loss.fines_and_judgments", "override_absent"),
    # min <= mode <= max, on a baseline estimate, an override and an annual cost
    ("baseline min above mode", _set("parameters", "frequency", "tef", "min", value=500),
     P + "frequency.tef", "pert_order"),
    ("override min above mode", _set("variants", 0, "overrides", "vulnerability.probability", "min", value=0.02),
     "inputs.variants.0.overrides.vulnerability.probability", "pert_order"),
    ("annual cost max below mode", _set("variants", 0, "annual_cost", "max", value=1),
     "inputs.variants.0.annual_cost", "pert_order"),
    # analysis_period_years > 0
    ("zero analysis period", _set("parameters", "analysis_period_years", value=0),
     P + "analysis_period_years", "exclusiveMinimum"),
    ("negative analysis period", _set("parameters", "analysis_period_years", value=-1),
     P + "analysis_period_years", "exclusiveMinimum"),
]


@pytest.mark.parametrize("mutate,path,rule", [c[1:] for c in ENGINE_TRUSTS], ids=[c[0] for c in ENGINE_TRUSTS])
def test_validation_rejects_what_the_engine_trusts(sample_inputs, mutate, path, rule):
    assert validate_inputs(sample_inputs, entry_lookup=library.entry_lookup(None)) == []
    mutate(sample_inputs)
    issues = validate_inputs(sample_inputs, entry_lookup=library.entry_lookup(None))
    assert (path, rule) in {(i["path"], i["rule"]) for i in issues}, issues
