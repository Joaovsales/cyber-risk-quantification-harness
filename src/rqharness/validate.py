"""The single validator: JSON Schema documents plus cross-reference rules.

Schema checks live in :mod:`rqharness.schemas`; this module adds the rules that span
fields and documents. Validation is pure: it returns issues and raises only on I/O faults.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from rqharness import engine, library, model, tiers
from rqharness.outcomes import Issue, Rejected, issue
from rqharness.model import LOSS_FORMS, lef_models
from rqharness.pert import Pert
from rqharness.schemas import parse_document, validate_document
from rqharness.workspace import Run

KIND_BY_FILENAME = {
    "scenario.yaml": "scenario",
    "inputs.yaml": "inputs",
    "run.yaml": "run",
    "requests.yaml": "requests",
    "org-profile.yaml": "org-profile",
    "connector-map.yaml": "connector-map",
}


# --- cross-reference rules for inputs -------------------------------------------


def _estimates(inputs: dict) -> Iterator[tuple[str, str | None, dict]]:
    """(dotted path in the document, estimate path, estimate) for every estimate."""
    for block, body in inputs["parameters"].items():
        if isinstance(body, dict):
            for key, value in body.items():
                if isinstance(value, dict):
                    yield f"parameters.{block}.{key}", f"{block}.{key}", value
    for i, variant in enumerate(inputs["variants"]):
        for path, value in variant["overrides"].items():
            yield f"variants.{i}.overrides.{path}", path, value
        if "annual_cost" in variant:
            yield f"variants.{i}.annual_cost", None, variant["annual_cost"]


def _is_amount(path: str | None) -> bool:
    return path is None or path.split(".", 1)[1] in LOSS_FORMS


def _tier_satisfied(tier: str, linked: list[dict], entries: dict[str, dict | None]) -> bool:
    rule = tiers.TIERS[tier].satisfied_by
    return rule is not None and any(
        rule.met_by(source, (entries.get(source.get("library_entry_id")) or {}).get("tier")) for source in linked)


def _expected_events_issues(inputs: dict) -> list[Issue]:
    """Expected events per iteration, and secondary events per primary event, within engine.MAX_EVENT_MEAN.

    Expected events are at most engine.expected_events on the estimates' maxima, which does not
    depend on n. A variant is checked when it overrides an estimate the bound reads, and the
    issue names the first one it overrides; the baseline's names its rate.
    """
    params = inputs["parameters"]
    frequency_model, vulnerability_model = lef_models(inputs)
    years = params.get("analysis_period_years", 1)
    baseline = {path: est for where, path, est in _estimates(inputs) if where.startswith("parameters.")}
    scopes = [("inputs.parameters", baseline)]
    scopes += [(f"inputs.variants.{i}.overrides", v["overrides"]) for i, v in enumerate(inputs["variants"])]
    issues: list[Issue] = []
    for prefix, own in scopes:
        eff = {path: Pert(est["min"], est["mode"], est["max"]) for path, est in {**baseline, **own}.items()}
        bound = engine.expected_events(frequency_model, vulnerability_model, years, eff.__getitem__, "max")
        blamed = next((p for p in bound.estimates if p in own), None)
        events = bound.per_iteration
        if blamed is not None and events > engine.MAX_EVENT_MEAN:
            issues.append(issue(f"{prefix}.{blamed}.max", "expected_events",
                                f"up to {events:,.0f} expected events per iteration (frequency maxima x "
                                f"analysis_period_years) exceeds the engine's {engine.MAX_EVENT_MEAN:,}; lower the "
                                "frequency max or the analysis period, or count events at a coarser grain "
                                "(one per attack campaign, not per attempt)"))
    for where, path, est in _estimates(inputs):
        if path == "secondary_loss.slef" and est["max"] > engine.MAX_EVENT_MEAN:
            issues.append(issue(f"inputs.{where}.max", "expected_events",
                                f"slef max {est['max']:,} exceeds the engine's {engine.MAX_EVENT_MEAN:,} secondary "
                                "events per primary event; lower it or count secondary events at a coarser grain"))
    return issues


def _cross_reference_issues(inputs: dict, entry_lookup: library.EntryLookup) -> list[Issue]:
    issues: list[Issue] = []
    sources = {s["id"]: s for s in inputs["sources"]}
    entries: dict[str, dict | None] = {}
    for i, source in enumerate(inputs["sources"]):
        if source["kind"] == "memory":
            entry_id = source["library_entry_id"]
            entries[entry_id], unresolved = entry_lookup(entry_id, f"inputs.sources.{i}.library_entry_id")
            issues += unresolved
    baseline = {path: est for where, path, est in _estimates(inputs) if where.startswith("parameters.")}
    currency = inputs["currency"]
    for where, path, est in _estimates(inputs):
        prefix = f"inputs.{where}"
        provenance = est["provenance"]
        unresolved = [sid for sid in provenance["source_ids"] if sid not in sources]
        for sid in unresolved:
            index = provenance["source_ids"].index(sid)
            issues.append(issue(f"{prefix}.provenance.source_ids.{index}", "source_unresolved",
                                f"source id {sid!r} is not in sources"))
        needs = tiers.TIERS[provenance["tier"]].satisfied_by
        linked = [sources[sid] for sid in provenance["source_ids"] if sid in sources]
        if needs and not unresolved and not _tier_satisfied(provenance["tier"], linked, entries):
            issues.append(issue(f"{prefix}.provenance.source_ids", "tier_source",
                                f"a {provenance['tier']} estimate needs {needs.description}"))
        if _is_amount(path) and est["unit"] != currency:
            issues.append(issue(f"{prefix}.unit", "currency",
                                f"unit {est['unit']!r} differs from the run currency {currency!r}"))
        if not est["min"] <= est["mode"] <= est["max"]:
            issues.append(issue(prefix, "pert_order", "min, mode and max must satisfy min <= mode <= max"))
        if where.startswith("variants.") and path:
            base = baseline.get(path)
            if base is None:
                issues.append(issue(prefix, "override_absent", f"{path} is not an estimate in the baseline"))
            elif base["unit"] != est["unit"]:
                issues.append(issue(f"{prefix}.unit", "override_unit",
                                    f"unit {est['unit']!r} differs from the baseline unit {base['unit']!r}"))
    issues += _expected_events_issues(inputs)
    return issues


def validate_inputs(data: object, *, entry_lookup: library.EntryLookup) -> list[Issue]:
    """Schema first; the cross-reference rules only run on a schema-valid document.

    ``memory`` sources resolve through ``entry_lookup``, from :func:`library.entry_lookup`.
    """
    issues = validate_document("inputs", data, stem="inputs")
    if issues:
        return issues
    return _cross_reference_issues(data, entry_lookup)  # type: ignore[arg-type]


# --- runs -------------------------------------------------------------------------


@dataclass(frozen=True)
class RunContents:
    """A run's scenario and inputs as bytes read once, each None when its file is absent."""

    scenario: bytes | None
    inputs: bytes | None


def missing_document(path: Path) -> Issue:
    """The issue for a run document that is not there: ``<stem>.document`` / ``missing``, naming its folder."""
    return issue(f"{path.stem}.document", "missing", f"{path.name} is missing from {path.parent}")


@dataclass(frozen=True)
class ReadyRun:
    """A run ready to simulate: both documents present and validated, as :func:`validate_run` read them."""

    scenario_bytes: bytes
    inputs_bytes: bytes
    inputs: dict

    @functools.cached_property  # caches in the instance __dict__, so the class takes no slots
    def inputs_model(self) -> model.ModelInputs:
        """The validated inputs loaded for the engine, once (spec D30: only from validated inputs)."""
        return model.load_model_inputs(self.inputs)


@dataclass(frozen=True)
class ValidationReport:
    """What :func:`validate_run` found, and the documents it validated.

    ``contents`` holds the bytes it read. ``scenario`` and ``inputs`` are those bytes parsed, each
    None unless the document is present and passes its own checks (parse, schema and, for inputs,
    the cross-reference rules). A caller that goes on to use a document takes it from here, so
    what it uses is what was validated.

    ``readiness`` is the one readiness rule that `rqh status` and `rqh finalize` share: the
    :class:`ReadyRun`, or the non-empty list of reasons the run is not ready, which is the issues
    plus a missing inputs.yaml (``issues`` allows that, so `rqh validate` passes a run still
    collecting its inputs). One field holds both answers, so the two commands cannot disagree.
    """

    ok: bool
    issues: list[Issue]
    contents: RunContents
    scenario: dict | None
    inputs: dict | None
    readiness: ReadyRun | list[Issue]

    def __post_init__(self) -> None:
        if self.readiness == []:
            raise ValueError("a run that is not ready needs at least one readiness issue")

    @property
    def documents(self) -> list[str]:
        """Stems of the documents that were present."""
        return [stem for stem in ("scenario", "inputs") if getattr(self.contents, stem) is not None]

    @property
    def readiness_issues(self) -> list[Issue]:
        """Every reason the run is not ready to simulate; empty exactly when :meth:`ready` returns."""
        return [] if isinstance(self.readiness, ReadyRun) else self.readiness

    def ready(self) -> ReadyRun:
        """The run as `rqh finalize` snapshots and simulates it; raises ``Rejected`` with ``readiness_issues``."""
        if isinstance(self.readiness, ReadyRun):
            return self.readiness
        raise Rejected(self.readiness)


def _read_contents(run_dir: Path) -> RunContents:
    def read(name: str) -> bytes | None:
        path = run_dir / name
        return path.read_bytes() if path.is_file() else None

    return RunContents(scenario=read("scenario.yaml"), inputs=read("inputs.yaml"))


def validate_run(run: Run) -> ValidationReport:
    """Read the run's scenario and inputs once, validate them, and return them with the issues."""
    run_dir = run.dir
    contents = _read_contents(run_dir)
    scenario: object | None = None
    inputs: object | None = None
    inputs_issues: list[Issue] = []

    if contents.scenario is not None:
        scenario, loaded = parse_document(contents.scenario, "scenario")
        scenario_issues = loaded or validate_document("scenario", scenario, stem="scenario")
    else:
        scenario_issues = [missing_document(run_dir / "scenario.yaml")]

    if contents.inputs is not None:
        inputs, loaded = parse_document(contents.inputs, "inputs")
        inputs_issues = loaded or validate_inputs(inputs, entry_lookup=library.entry_lookup(run.workspace))

    issues = scenario_issues + inputs_issues
    if isinstance(scenario, dict) and isinstance(inputs, dict):
        if scenario.get("scenario_id") != inputs.get("scenario_id"):
            issues.append(issue("inputs.scenario_id", "scenario_id",
                                f"{inputs.get('scenario_id')!r} does not equal scenario.scenario_id {scenario.get('scenario_id')!r}"))
    readiness: ReadyRun | list[Issue] = (
        issues if contents.inputs is not None else [*issues, missing_document(run_dir / "inputs.yaml")])
    if not readiness:  # both documents were read and passed every check
        assert contents.scenario is not None and contents.inputs is not None and isinstance(inputs, dict)
        readiness = ReadyRun(scenario_bytes=contents.scenario, inputs_bytes=contents.inputs, inputs=inputs)
    # a document with no issues of its own passed its schema, so it is a mapping
    return ValidationReport(ok=not issues, issues=issues, contents=contents,
                            scenario=None if scenario_issues else scenario,
                            inputs=None if inputs_issues else inputs,
                            readiness=readiness)
