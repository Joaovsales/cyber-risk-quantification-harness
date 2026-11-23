"""State schemas (AC4): run, requests, library-entry, org-profile and connector-map."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from rqharness import cli
from rqharness.schemas import known_kinds, load_yaml, validate_document

FIXTURES = Path(__file__).parent / "fixtures"
KINDS = ["run", "requests", "library-entry", "org-profile", "connector-map"]
TS = "2026-11-10T09:00:00Z"


def load(kind: str) -> dict:
    data, issues = load_yaml(FIXTURES / f"{kind}.yaml", kind)
    assert not issues
    return data


def check(kind: str, data: dict) -> list[tuple[str, str]]:
    return [(i["path"], i["rule"]) for i in validate_document(kind, data, stem=kind)]


def mutated(kind: str, change) -> dict:
    data = copy.deepcopy(load(kind))
    change(data)
    return data


def test_kinds_are_registered():
    assert set(KINDS) <= set(known_kinds())


@pytest.mark.parametrize("kind", KINDS)
def test_state_fixtures_validate(kind):
    assert validate_document(kind, load(kind), stem=kind) == []


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_major_version_refused(kind):
    data = mutated(kind, lambda d: d.update(schema_version="2"))
    assert check(kind, data) == [(f"{kind}.schema_version", "unknown_major_version")]


@pytest.mark.parametrize("kind", KINDS)
def test_unknown_field_rejected(kind):
    data = mutated(kind, lambda d: d.update(surprise=1))
    assert (f"{kind}.surprise", "additionalProperties") in check(kind, data)


def test_run_rejections():
    def run(change):
        return check("run", mutated("run", change))

    assert ("run.status", "enum") in run(lambda d: d.update(status="done"))
    assert ("run.route", "enum") in run(lambda d: d.update(route="fast"))
    assert ("run.n", "minimum") in run(lambda d: d.update(n=0))
    assert ("run.seed", "maximum") in run(lambda d: d.update(seed=2**63))
    assert ("run.seed", "minimum") in run(lambda d: d.update(seed=-1))
    assert ("run.seed", "required") in run(lambda d: d.pop("seed"))
    assert ("run.created_at", "pattern") in run(lambda d: d.update(created_at="2026-11-10T09:00:00"))
    assert ("run.route_overrides.frequency.nope", "additionalProperties") in run(
        lambda d: d["route_overrides"].update({"frequency.nope": "yolo"}))
    assert ("run.route_overrides.frequency.tef", "enum") in run(
        lambda d: d["route_overrides"].update({"frequency.tef": "fast"}))
    assert run(lambda d: d.pop("route_overrides")) == []


def test_requests_rejections():
    def req(change):
        return check("requests", mutated("requests", change))

    assert ("requests.requests.0.status", "enum") in req(lambda d: d["requests"][0].update(status="done"))
    assert ("requests.requests.0.id", "pattern") in req(lambda d: d["requests"][0].update(id="r1"))
    assert ("requests.requests.0.parameter_path", "pattern") in req(
        lambda d: d["requests"][0].update(parameter_path="frequency.nope"))
    assert ("requests.requests.0.created_at", "pattern") in req(
        lambda d: d["requests"][0].update(created_at="2026-11-10T09:00:00+00:00"))
    assert ("requests.candidates.0.status", "enum") in req(
        lambda d: d["candidates"][0].update(status="maybe"))
    assert ("requests.candidates.0.link", "pattern") in req(
        lambda d: d["candidates"][0].update(link="http://example.com/x"))
    assert ("requests.candidates.0.origin", "pattern") in req(
        lambda d: d["candidates"][0].update(origin="somewhere"))
    assert ("requests.candidates.0.evidence_kind", "enum") in req(
        lambda d: d["candidates"][0].update(evidence_kind="guess"))


def test_requests_answer_rules():
    def req(change):
        return check("requests", mutated("requests", change))

    assert ("requests.requests.2.answer.note", "maxLength") in req(
        lambda d: d["requests"][2]["answer"].update(note="x" * 501))
    assert ("requests.requests.2.answer", "anyOf") in req(
        lambda d: d["requests"][2].update(answer={"received_at": TS}))
    assert ("requests.requests.2.answer.value.provenance", "additionalProperties") in req(
        lambda d: d["requests"][2]["answer"]["value"].update(provenance={"tier": "sme_estimate", "source_ids": []}))


def test_library_entry_rejections():
    def lib(change):
        return check("library-entry", mutated("library-entry", change))

    assert ("library-entry.sensitivity", "required") in lib(lambda d: d.pop("sensitivity"))
    assert ("library-entry.sensitivity", "enum") in lib(lambda d: d.update(sensitivity="secret"))
    assert ("library-entry.note", "maxLength") in lib(lambda d: d.update(note="x" * 501))
    assert ("library-entry.scenario_tags", "minItems") in lib(lambda d: d.update(scenario_tags=[]))
    assert ("library-entry.scenario_tags.0", "enum") in lib(lambda d: d.update(scenario_tags=["worms"]))
    assert ("library-entry.stale_after_months", "minimum") in lib(lambda d: d.update(stale_after_months=0))
    assert ("library-entry.tier", "enum") in lib(lambda d: d.update(tier="rumour"))
    assert ("library-entry.segment.size_band", "enum") in lib(lambda d: d["segment"].update(size_band="huge"))
    assert ("library-entry.period.start", "pattern") in lib(lambda d: d["period"].update(start="2025-01"))
    assert ("library-entry.raw_data", "additionalProperties") in lib(lambda d: d.update(raw_data=[1, 2]))
    assert lib(lambda d: d.pop("stale_after_months")) == []


def test_org_profile_rejections():
    def org(change):
        return check("org-profile", mutated("org-profile", change))

    assert ("org-profile.theme.accent", "pattern") in org(lambda d: d["theme"].update(accent="blue"))
    assert ("org-profile.theme.logo_data_uri", "pattern") in org(
        lambda d: d["theme"].update(logo_data_uri="https://x.test/l.png"))
    assert ("org-profile.theme.logo_data_uri", "maxLength") in org(
        lambda d: d["theme"].update(logo_data_uri="data:image/png;base64," + "A" * 204800))
    assert ("org-profile.org_name", "required") in org(lambda d: d.pop("org_name"))
    assert check("org-profile", {"schema_version": "1", "org_name": "Acme"}) == []


def test_connector_map_rejections():
    def cmap(change):
        return check("connector-map", mutated("connector-map", change))

    assert ("connector-map.routes.0.connectors", "minItems") in cmap(
        lambda d: d["routes"][0].update(connectors=[]))
    assert ("connector-map.routes.0.family", "pattern") in cmap(
        lambda d: d["routes"][0].update(family="frequency.nope"))
    assert ("connector-map.routes.0.ask", "required") in cmap(lambda d: d["routes"][0].pop("ask"))


@pytest.mark.parametrize("name", ["run", "org-profile"])
def test_cli_validates_fixture_by_filename(name, capsys):
    assert cli.main(["validate", str(FIXTURES / f"{name}.yaml"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["documents"] == [name]


def test_schema_ids_live_under_the_project_pages_site():
    """A schema `$id` names a URL the project controls, never a domain anyone could register."""
    base = "https://joaovsales.github.io/cyber-risk-quantification-harness/schemas/"
    schema_dir = Path(__file__).resolve().parents[2] / "src" / "rqharness" / "schemas"
    files = sorted(schema_dir.glob("*.v*.json"))
    assert files
    for path in files:
        assert json.loads(path.read_text(encoding="utf-8"))["$id"] == base + path.name, path.name
