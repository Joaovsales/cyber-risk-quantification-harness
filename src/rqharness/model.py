"""Typed model inputs for the engine, built from a validated inputs document."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rqharness.pert import Pert

FREQUENCY_ESTIMATES = {
    "lef_direct": ("lef",),
    "tef_x_vulnerability": ("tef",),
    "tef_decomposed_cf_poa": ("contact", "action"),
    "tef_and_vulnerability_decomposed": ("contact", "action"),
}
VULNERABILITY_ESTIMATES = {
    "direct_probability": ("probability",),
    "tcap_x_resistance": ("threat_capability", "resistance_strength"),
}
USES_VULNERABILITY = {"tef_x_vulnerability", "tef_and_vulnerability_decomposed"}
LOSS_FORMS = (
    "productivity",
    "response",
    "replacement",
    "fines_and_judgments",
    "reputation",
    "competitive_advantage",
)
# Every estimate path the models know: the schemas enumerate the same set (tests/validate pins it).
ESTIMATE_PATHS = frozenset(
    [f"frequency.{e}" for es in FREQUENCY_ESTIMATES.values() for e in es]
    + [f"vulnerability.{e}" for es in VULNERABILITY_ESTIMATES.values() for e in es]
    + [f"primary_loss.{form}" for form in LOSS_FORMS]
    + ["secondary_loss.slef"]
    + [f"secondary_loss.{form}" for form in LOSS_FORMS]
)


@dataclass(frozen=True)
class VariantInputs:
    id: str
    label: str
    overrides: dict[str, Pert]
    annual_cost: Pert | None


@dataclass(frozen=True)
class ModelInputs:
    currency: str
    years: float
    frequency_model: str
    vulnerability_model: str | None
    baseline: dict[str, Pert]
    variants: tuple[VariantInputs, ...]

    @property
    def variant_ids(self) -> tuple[str, ...]:
        return ("baseline", *(v.id for v in self.variants))


def _pert(doc: dict) -> Pert:
    return Pert(float(doc["min"]), float(doc["mode"]), float(doc["max"]))


def _read(block: dict, names: Iterable[str], prefix: str, out: dict[str, Pert]) -> None:
    for name in names:
        out[f"{prefix}.{name}"] = _pert(block[name])


def lef_models(inputs: dict) -> tuple[str, str | None]:
    """The frequency model of a schema-valid inputs document and the vulnerability model it uses, if any."""
    params = inputs["parameters"]
    freq_model = params["frequency"]["model"]
    return freq_model, params["vulnerability"]["model"] if freq_model in USES_VULNERABILITY else None


def load_model_inputs(inputs: dict) -> ModelInputs:
    """The typed view of an inputs document that has passed ``validate_inputs`` (spec D30).

    Only structural reads happen here. The inputs schema and the cross-reference rules own every
    rule this relies on (the model enums, the estimate set per model, ``min <= mode <= max``,
    ``analysis_period_years > 0``, override targets), and none of them is repeated. The tables
    above say which estimates each model computes with; tests/validate pins them to the schema.
    An unvalidated document fails with whatever a read raises, or loads wrong.
    """
    params = inputs["parameters"]
    freq_model, vuln_model = lef_models(inputs)
    years = float(params.get("analysis_period_years", 1))

    baseline: dict[str, Pert] = {}
    _read(params["frequency"], FREQUENCY_ESTIMATES[freq_model], "frequency", baseline)
    if vuln_model is not None:
        _read(params["vulnerability"], VULNERABILITY_ESTIMATES[vuln_model], "vulnerability", baseline)
    primary = params["primary_loss"]
    _read(primary, [f for f in LOSS_FORMS if f in primary], "primary_loss", baseline)
    if "secondary_loss" in params:
        secondary = params["secondary_loss"]
        _read(secondary, ["slef", *(f for f in LOSS_FORMS if f in secondary)], "secondary_loss", baseline)

    variants = tuple(
        VariantInputs(
            id=var["id"],
            label=var["label"],
            overrides={path: _pert(doc) for path, doc in var["overrides"].items()},
            annual_cost=_pert(var["annual_cost"]) if "annual_cost" in var else None,
        )
        for var in inputs["variants"]
    )
    return ModelInputs(inputs["currency"], years, freq_model, vuln_model, baseline, variants)
