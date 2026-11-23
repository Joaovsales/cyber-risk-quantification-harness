from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from rqharness import cli, library, workspace
from rqharness.schemas import known_kinds, load_yaml, validate_document
from rqharness.validate import validate_inputs, validate_run

SAMPLE = Path(__file__).parent / "fixtures" / "sample-run"
SAMPLE_ID = "credential-phishing-bec"
SHIPPED_ONLY = library.entry_lookup(None)


def sample_inputs() -> dict:
    return yaml.safe_load((SAMPLE / "inputs.yaml").read_text(encoding="utf-8"))


def sample_scenario() -> dict:
    return yaml.safe_load((SAMPLE / "scenario.yaml").read_text(encoding="utf-8"))


def pairs(issues) -> set[tuple[str, str]]:
    return {(i["path"], i["rule"]) for i in issues}


def rules(issues) -> set[str]:
    return {i["rule"] for i in issues}


def make_run(tmp_path: Path, scenario=None, inputs=None) -> workspace.Run:
    ws = tmp_path / ".riskquant"
    run = workspace.Run(ws, ws / "runs" / "r1")
    run.dir.mkdir(parents=True)
    if scenario is not None:
        (run.dir / "scenario.yaml").write_text(yaml.safe_dump(scenario), encoding="utf-8")
    if inputs is not None:
        (run.dir / "inputs.yaml").write_text(yaml.safe_dump(inputs), encoding="utf-8")
    return run


@pytest.fixture
def sample_run(tmp_path, monkeypatch) -> workspace.Run:
    """The sample run copied into a workspace in the current directory."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    ws = tmp_path / ".riskquant"
    shutil.copytree(SAMPLE, ws / "runs" / SAMPLE_ID)
    return workspace.Run(ws, ws / "runs" / SAMPLE_ID)


def put_library_entry(tmp_path: Path, tier: str, folder: str = "") -> None:
    lib = tmp_path / ".riskquant" / "library" / folder
    lib.mkdir(parents=True)
    entry = {  # a complete entry: the validator only trusts entries that pass the library-entry schema
        "schema_version": "1", "entry_id": "phish-rate", "parameter_family": "primary_loss.response",
        "value": {"min": 1000, "mode": 2000, "max": 4000, "unit": "USD"}, "tier": tier,
        "source": {"id": "src-1", "kind": "person", "title": "Incident response lead estimate",
                   "owner_role": "Incident response lead", "retrieved_at": "2026-11-09"},
        "scenario_tags": ["business_email_compromise"], "segment": {"industry": "software", "size_band": "mid_market"},
        "period": {"start": "2025-11-09", "end": "2026-11-09"}, "captured_at": "2026-11-09",
        "stale_after_months": 18, "sensitivity": "internal", "note": "Derived from past incident tickets.",
    }
    (lib / "phish-rate.yaml").write_text(yaml.safe_dump(entry), encoding="utf-8")


def _del(d, *keys):
    for k in keys[:-1]:
        d = d[k]
    del d[keys[-1]]


def _set(d, keys, value):
    for k in keys[:-1]:
        d = d[k]
    d[keys[-1]] = value


def test_known_kinds_include_core_schemas():
    assert {"scenario", "inputs"} <= set(known_kinds())


def test_sample_run_valid(sample_run):
    report = validate_run(sample_run)
    assert report.ok and report.issues == []


@pytest.mark.parametrize("by", ["id", "path"])
def test_sample_run_valid_through_cli(sample_run, by, capsys):
    ref = SAMPLE_ID if by == "id" else str(sample_run.dir)
    assert cli.main(["validate", ref, "--json"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    assert env["data"]["documents"] == ["scenario", "inputs"]


def test_a_run_directory_outside_the_workspace_runs_is_refused(sample_run, capsys):
    """The loose fixture is not a run of the workspace in use; its documents still validate one by one."""
    assert cli.main(["validate", str(SAMPLE), "--json"]) == cli.EXIT_USAGE
    assert json.loads(capsys.readouterr().out)["issues"][0]["rule"] == "outside_workspace"
    assert cli.main(["validate", str(SAMPLE / "scenario.yaml"), "--json"]) == 0


def test_cli_single_file_by_filename(capsys):
    assert cli.main(["validate", str(SAMPLE / "inputs.yaml"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["documents"] == ["inputs"]


def test_cli_unknown_kind_is_usage_error(tmp_path, capsys):
    odd = tmp_path / "odd.yaml"
    odd.write_text("a: 1\n", encoding="utf-8")
    assert cli.main(["validate", str(odd), "--json"]) == cli.EXIT_USAGE


def test_cli_text_mode_prints_ok(sample_run, capsys):
    assert cli.main(["validate", SAMPLE_ID]) == 0
    assert "ok" in capsys.readouterr().out


SCHEMA_CASES = [
    ("scenario", lambda d: _del(d, "title"), "scenario.title", "required"),
    ("scenario", lambda d: _set(d, ["scenario_type"], "meteor"), "scenario.scenario_type", "enum"),
    ("scenario", lambda d: _set(d, ["scenario_id"], "Bad Id"), "scenario.scenario_id", "pattern"),
    ("scenario", lambda d: _set(d, ["extra"], 1), "scenario.extra", "additionalProperties"),
    ("inputs", lambda d: _set(d, ["parameters", "vulnerability", "probability", "provenance", "tier"], "guess"),
     "inputs.parameters.vulnerability.probability.provenance.tier", "enum"),
    ("inputs", lambda d: _set(d, ["sources", 1, "url"], "http://www.verizon.com/x"),
     "inputs.sources.1.url", "pattern"),
    ("inputs", lambda d: _set(d, ["currency"], "usd"), "inputs.currency", "pattern"),
    ("inputs", lambda d: _del(d, "currency"), "inputs.currency", "required"),
    ("inputs", lambda d: _set(d, ["parameters", "vulnerability", "probability", "max"], 1.5),
     "inputs.parameters.vulnerability.probability.max", "maximum"),
    ("inputs", lambda d: _set(d, ["parameters", "primary_loss", "response", "min"], -1),
     "inputs.parameters.primary_loss.response.min", "minimum"),
    ("inputs", lambda d: _del(d, "parameters", "frequency", "tef"),
     "inputs.parameters.frequency.tef", "required"),
    ("inputs", lambda d: _set(d, ["parameters", "frequency", "lef"],
                              copy.deepcopy(d["parameters"]["frequency"]["tef"])),
     "inputs.parameters.frequency.lef", "forbidden"),
    ("inputs", lambda d: _del(d, "parameters", "vulnerability"),
     "inputs.parameters.vulnerability", "required"),
    ("inputs", lambda d: _set(d, ["parameters", "frequency", "model"], "lef_direct"),
     "inputs.parameters.frequency.lef", "required"),
    ("inputs", lambda d: _del(d, "parameters", "primary_loss", "replacement", "provenance", "rationale"),
     "inputs.parameters.primary_loss.replacement.provenance.rationale", "required"),
    ("inputs", lambda d: _set(d, ["sources", 0, "kind"], "memory"),
     "inputs.sources.0.library_entry_id", "required"),
    ("inputs", lambda d: _set(d, ["variants", 0, "id"], "baseline"), "inputs.variants.0.id", "not"),
    ("inputs", lambda d: _set(d, ["parameters", "primary_loss", "response", "unit"], "usd"),
     "inputs.parameters.primary_loss.response.unit", "pattern"),
]


@pytest.mark.parametrize("kind,mutate,path,rule", SCHEMA_CASES)
def test_schema_violation_reports_dotted_path(kind, mutate, path, rule):
    data = sample_scenario() if kind == "scenario" else sample_inputs()
    mutate(data)
    issues = validate_document(kind, data, stem=kind)
    assert (path, rule) in pairs(issues), issues


def test_schema_violation_exit_1_through_cli(tmp_path, monkeypatch, capsys):
    scenario = sample_scenario()
    del scenario["title"]
    run = make_run(tmp_path, scenario, sample_inputs())
    monkeypatch.setenv(cli.WORKSPACE_ENV, str(run.workspace))
    assert cli.main(["validate", str(run.dir), "--json"]) == cli.EXIT_REJECTED
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False
    assert ("scenario.title", "required") in pairs(env["issues"])


def test_unknown_major_version_is_one_issue():
    data = sample_inputs()
    data["schema_version"] = "2"
    data["currency"] = "bad"
    issues = validate_document("inputs", data, stem="inputs")
    assert pairs(issues) == {("inputs.schema_version", "unknown_major_version")}
    assert len(issues) == 1


def test_malformed_yaml_reports_document(tmp_path):
    bad = tmp_path / "scenario.yaml"
    bad.write_text("a: [unclosed\n", encoding="utf-8")
    data, issues = load_yaml(bad, "scenario")
    assert data is None
    assert pairs(issues) == {("scenario.document", "yaml")}


def test_missing_scenario_is_reported(tmp_path):
    run = make_run(tmp_path, None, sample_inputs())
    assert ("scenario.document", "missing") in pairs(validate_run(run).issues)


def test_malformed_yaml_in_run(tmp_path):
    run = make_run(tmp_path, sample_scenario(), None)
    (run.dir / "inputs.yaml").write_text("{: bad", encoding="utf-8")
    assert ("inputs.document", "yaml") in pairs(validate_run(run).issues)


def test_unquoted_dates_are_accepted(tmp_path):
    text = (SAMPLE / "inputs.yaml").read_text(encoding="utf-8").replace('"2026-11-09"', "2026-11-09")
    path = tmp_path / "inputs.yaml"
    path.write_text(text, encoding="utf-8")
    data, issues = load_yaml(path, "inputs")
    assert issues == [] and validate_inputs(data, entry_lookup=SHIPPED_ONLY) == []


def test_scenario_id_must_match_across_files(tmp_path):
    inputs = sample_inputs()
    inputs["scenario_id"] = "another-scenario"
    run = make_run(tmp_path, sample_scenario(), inputs)
    assert ("inputs.scenario_id", "scenario_id") in pairs(validate_run(run).issues)


# --- AC3: one case per cross-reference rule -------------------------------------

BASE = "inputs.parameters."


def _provenance(path_keys, tier, source_ids):
    def mutate(d):
        _set(d, path_keys + ["provenance"], {"tier": tier, "source_ids": source_ids})
    return mutate


def _memory_source(d):
    d["sources"].append({"id": "mem", "kind": "memory", "title": "Org memory", "library_entry_id": "phish-rate"})
    _set(d, ["parameters", "frequency", "tef", "provenance"], {"tier": "sme_estimate", "source_ids": ["mem"]})


CROSS_CASES = [
    ("source_unresolved",
     _provenance(["parameters", "frequency", "tef"], "internal_data", ["nope"]),
     BASE + "frequency.tef.provenance.source_ids.0"),
    ("tier_source",
     _provenance(["parameters", "vulnerability", "probability"], "benchmark", ["ir-lead"]),
     BASE + "vulnerability.probability.provenance.source_ids"),
    ("tier_source",
     _provenance(["parameters", "frequency", "tef"], "internal_data", ["ibm-cost-of-breach"]),
     BASE + "frequency.tef.provenance.source_ids"),
    ("tier_source",
     _provenance(["parameters", "primary_loss", "response"], "sme_estimate", ["mail-gateway"]),
     BASE + "primary_loss.response.provenance.source_ids"),
    ("currency",
     lambda d: _set(d, ["parameters", "primary_loss", "response", "unit"], "EUR"),
     BASE + "primary_loss.response.unit"),
    ("currency",
     lambda d: _set(d, ["variants", 0, "annual_cost", "unit"], "EUR"),
     "inputs.variants.0.annual_cost.unit"),
    ("override_absent",
     lambda d: _set(d, ["variants", 0, "overrides", "frequency.lef"],
                    copy.deepcopy(d["variants"][1]["overrides"]["frequency.tef"])),
     "inputs.variants.0.overrides.frequency.lef"),
    ("override_unit",
     lambda d: _set(d, ["variants", 0, "overrides", "primary_loss.response"],
                    {**copy.deepcopy(d["parameters"]["primary_loss"]["response"]), "unit": "EUR"}),
     "inputs.variants.0.overrides.primary_loss.response.unit"),
    ("pert_order",
     lambda d: _set(d, ["parameters", "frequency", "tef", "min"], 500),
     BASE + "frequency.tef"),
    ("pert_order",
     lambda d: _set(d, ["parameters", "primary_loss", "response", "max"], 20000),
     BASE + "primary_loss.response"),
    ("pert_order",
     lambda d: _set(d, ["variants", 0, "overrides", "vulnerability.probability", "min"], 0.02),
     "inputs.variants.0.overrides.vulnerability.probability"),
    ("pert_order",
     lambda d: _set(d, ["variants", 0, "annual_cost", "max"], 1),
     "inputs.variants.0.annual_cost"),
    ("library_entry_missing", _memory_source, "inputs.sources.5.library_entry_id"),
]


@pytest.mark.parametrize("rule,mutate,path", CROSS_CASES)
def test_cross_reference_rules(rule, mutate, path):
    data = sample_inputs()
    mutate(data)
    issues = validate_inputs(data, entry_lookup=SHIPPED_ONLY)
    assert any(i["rule"] == rule and i["path"].startswith(path) for i in issues), issues


def test_cross_rules_skipped_when_schema_invalid():
    data = sample_inputs()
    del data["currency"]
    data["parameters"]["primary_loss"]["response"]["unit"] = "EUR"
    assert rules(validate_inputs(data, entry_lookup=SHIPPED_ONLY)) == {"required"}


@pytest.mark.parametrize("entry_tier,accepted", [("internal_data", True), ("sme_estimate", False)])
def test_internal_data_with_memory_source(tmp_path, entry_tier, accepted):
    run = make_run(tmp_path, sample_scenario(), None)
    put_library_entry(tmp_path, entry_tier)
    data = sample_inputs()
    data["sources"].append({"id": "mem", "kind": "memory", "title": "Org memory", "library_entry_id": "phish-rate"})
    _set(data, ["parameters", "frequency", "tef", "provenance"], {"tier": "internal_data", "source_ids": ["mem"]})
    issues = validate_inputs(data, entry_lookup=library.entry_lookup(run.workspace))
    assert ("tier_source" not in rules(issues)) is accepted
    assert "library_entry_missing" not in rules(issues)


def test_sme_estimate_accepts_memory_with_internal_data_entry(tmp_path):
    run = make_run(tmp_path, sample_scenario(), None)
    put_library_entry(tmp_path, "internal_data")
    data = sample_inputs()
    data["sources"].append({"id": "mem", "kind": "memory", "title": "Org memory", "library_entry_id": "phish-rate"})
    _set(data, ["parameters", "primary_loss", "response", "provenance"], {"tier": "sme_estimate", "source_ids": ["mem"]})
    assert validate_inputs(data, entry_lookup=library.entry_lookup(run.workspace)) == []


def test_run_copy_validates_from_workspace_layout(tmp_path):
    ws = tmp_path / ".riskquant"
    shutil.copytree(SAMPLE, ws / "runs" / "copy")
    assert validate_run(workspace.Run(ws, ws / "runs" / "copy")).ok


def _with_memory_source(data: dict) -> dict:
    data["sources"].append({"id": "mem", "kind": "memory", "title": "Org memory", "library_entry_id": "phish-rate"})
    _set(data, ["parameters", "frequency", "tef", "provenance"], {"tier": "internal_data", "source_ids": ["mem"]})
    return data


def test_validate_inputs_requires_an_entry_lookup():
    with pytest.raises(TypeError):
        validate_inputs(sample_inputs())  # type: ignore[call-arg]  # no silent "no memory" default


def test_validate_inputs_resolves_memory_through_the_lookup_it_is_given():
    entry = {"tier": "internal_data"}
    seen = []
    issues = validate_inputs(_with_memory_source(sample_inputs()), entry_lookup=lambda i, at: (seen.append(i) or entry, []))
    assert seen == ["phish-rate"] and issues == []


def test_run_reports_a_memory_entry_two_files_hold_and_keeps_collecting(tmp_path):
    data = _with_memory_source(sample_inputs())
    data["parameters"]["primary_loss"]["response"]["unit"] = "EUR"  # an unrelated issue, still reported
    run = make_run(tmp_path, sample_scenario(), data)
    put_library_entry(tmp_path, "internal_data")
    put_library_entry(tmp_path, "internal_data", "team-a")
    issues = validate_run(run).issues
    source = len(data["sources"]) - 1
    ambiguous = [i for i in issues if i["rule"] == "duplicate_entry_id"]
    assert [i["path"] for i in ambiguous] == [f"inputs.sources.{source}.library_entry_id"]
    assert "team-a/phish-rate.yaml" in ambiguous[0]["message"] and "rqh library validate" in ambiguous[0]["message"]
    assert "currency" in rules(issues) and "library_entry_missing" not in rules(issues)


def test_validate_inputs_finds_shipped_benchmarks_without_a_workspace():
    shipped = sorted(library.shipped_dir().rglob("*.yaml"))[0].stem
    data = sample_inputs()
    data["sources"].append({"id": "mem", "kind": "memory", "title": "Benchmark", "library_entry_id": shipped})
    assert "library_entry_missing" not in rules(validate_inputs(data, entry_lookup=SHIPPED_ONLY))


def _sample_run_with_memory(sample_run: workspace.Run, folder: str = "") -> workspace.Run:
    put_library_entry(sample_run.workspace.parent, "internal_data", folder)
    (sample_run.dir / "inputs.yaml").write_text(yaml.safe_dump(_with_memory_source(sample_inputs())), encoding="utf-8")
    return sample_run


def test_validate_file_and_run_agree_on_the_memory_source(sample_run, tmp_path):
    run = _sample_run_with_memory(sample_run)
    loose = tmp_path / "elsewhere" / "inputs.yaml"
    loose.parent.mkdir()
    shutil.copy(run.dir / "inputs.yaml", loose)
    assert cli.main(["validate", str(run.dir), "--json"]) == 0
    assert cli.main(["validate", str(run.dir / "inputs.yaml"), "--json"]) == 0
    assert cli.main(["validate", str(loose), "--json"]) == 0  # a lone file reads the default workspace's memory


def test_validate_file_without_a_workspace_resolves_shipped_benchmarks_only(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    path = tmp_path / "inputs.yaml"
    path.write_text(yaml.safe_dump(_with_memory_source(sample_inputs())), encoding="utf-8")
    assert cli.main(["validate", str(path), "--json"]) == cli.EXIT_REJECTED
    assert "library_entry_missing" in capsys.readouterr().out


def test_subfolder_memory_entry_found_by_search_and_validate(sample_run):
    run = _sample_run_with_memory(sample_run, folder="incident-response")
    hits = library.search(library.LibraryQuery(parameter_family="primary_loss.response"), workspace=run.workspace)
    assert [h.entry["entry_id"] for h in hits if h.origin == "memory"] == ["phish-rate"]
    assert validate_run(run).ok
    assert cli.main(["validate", str(run.dir / "inputs.yaml"), "--json"]) == 0


def test_validate_reports_an_invalid_memory_override_of_a_shipped_benchmark(sample_run, capsys):
    shipped = sorted(library.shipped_dir().rglob("*.yaml"))[0]
    override = yaml.safe_load(shipped.read_text(encoding="utf-8"))
    del override["sensitivity"]  # the user's override of the benchmark, with a mistake in it
    (sample_run.workspace / "library" / "team-a").mkdir(parents=True)
    (sample_run.workspace / "library" / "team-a" / "override.yaml").write_text(yaml.safe_dump(override), encoding="utf-8")
    data = sample_inputs()
    data["sources"].append({"id": "mem", "kind": "memory", "title": "Override", "library_entry_id": override["entry_id"]})
    (sample_run.dir / "inputs.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["validate", str(sample_run.dir), "--json"]) == cli.EXIT_REJECTED
    issues = json.loads(capsys.readouterr().out)["issues"]
    assert [(i["path"], i["rule"]) for i in issues] == [
        (f"inputs.sources.{len(data['sources']) - 1}.library_entry_id", "library_entry_invalid")]
    assert "'team-a/override.yaml'" in issues[0]["message"]
