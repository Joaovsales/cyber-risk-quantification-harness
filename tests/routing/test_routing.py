from __future__ import annotations

import base64
from pathlib import Path

import pytest
import yaml

from rqharness import orgprofile, routing
from rqharness.outcomes import Rejected
from rqharness.schemas import validate_document

FIXTURE = Path(__file__).parent / "fixtures" / "org-profile.yaml"
_FORMS = ("productivity", "response", "replacement", "fines_and_judgments", "reputation", "competitive_advantage")

FAMILIES = [
    "frequency.lef", "frequency.tef", "frequency.contact", "frequency.action",
    "vulnerability.probability", "vulnerability.threat_capability", "vulnerability.resistance_strength",
    "secondary_loss.slef",
    *(f"primary_loss.{f}" for f in _FORMS),
    *(f"secondary_loss.{f}" for f in _FORMS),
]


def _profile_data() -> dict:
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / "org-profile.yaml").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path


def test_map_covers_every_family():
    assert validate_document("connector-map", routing.load_connector_map()) == []
    assert set(routing.families()) == set(FAMILIES)
    for family in FAMILIES:
        assert routing.resolve(family, None), family
    assert len(routing.resolve("frequency.tef", None)) >= 2


def test_map_asks_carry_no_numbers():
    for route in routing.load_connector_map()["routes"]:
        assert not any(ch.isdigit() for ch in route["ask"]), route["ask"]


def test_resolve_without_profile_has_no_people_or_systems():
    route = routing.resolve("frequency.tef", None)[0]
    assert route.family == "frequency.tef"
    assert route.system_kind and route.owner_role and route.expected_artifact and route.ask
    assert route.connectors and route.people == () and route.systems == ()


def test_resolve_unknown_family_raises():
    with pytest.raises(ValueError):
        routing.resolve("frequency.nope", None)


def test_resolve_adds_people_from_profile(tmp_path):
    profile = orgprofile.load_profile(_workspace(tmp_path))
    tef = routing.resolve("frequency.tef", profile)
    assert any(p.name == "Dana Reyes" for r in tef for p in r.people)
    assert any(s.id == "mail-gw" for r in tef for s in r.systems)  # kind match
    action = routing.resolve("frequency.action", profile)
    assert any(p.name == "Priya Nair" for r in action for p in r.people)  # trimmed, case-insensitive
    assert any(s.id == "phish-sim" for r in action for s in r.systems)  # owner_role match
    loss = routing.resolve("primary_loss.response", profile)
    assert all(p.name != "Dana Reyes" for r in loss for p in r.people)


def test_load_profile_absent_and_invalid(tmp_path):
    assert orgprofile.load_profile(tmp_path) is None
    (tmp_path / "org-profile.yaml").write_text("schema_version: '1'\n", encoding="utf-8")
    with pytest.raises(Rejected) as exc:
        orgprofile.load_profile(tmp_path)
    assert exc.value.issues[0]["path"] == "org-profile.org_name"


def test_load_profile_fields(tmp_path):
    profile = orgprofile.load_profile(_workspace(tmp_path))
    assert profile.org_name == "Northwind Analytics"
    assert profile.segment == {"industry": "software", "size_band": "mid_market"}
    assert profile.theme.accent == "#1F6FEB" and profile.theme.logo_data_uri is None
    assert profile.people[0].team == "secops"


def test_sample_profile_accepted():
    assert orgprofile.validate_profile(_profile_data()) == []


def _rules(data):
    return {(i["path"], i["rule"]) for i in orgprofile.validate_profile(data)}


def test_profile_rejects_large_logo_bad_accent_unknown_field():
    data = _profile_data()
    big = base64.b64encode(b"\0" * (200 * 1024 + 10)).decode()
    data["theme"]["logo_data_uri"] = f"data:image/png;base64,{big}"
    assert ("org-profile.theme.logo_data_uri", "logo_too_large") in _rules(data)

    for accent in ("blue", "#12345"):
        data = _profile_data()
        data["theme"]["accent"] = accent
        assert ("org-profile.theme.accent", "pattern") in _rules(data)

    data = _profile_data()
    data["extra"] = 1
    assert ("org-profile.extra", "additionalProperties") in _rules(data)

    data = _profile_data()
    data["people"][0]["phone"] = "x"
    assert ("org-profile.people.0.phone", "additionalProperties") in _rules(data)


def test_resolve_prefers_routes_typed_for_the_scenario():
    general = routing.resolve("vulnerability.probability", None)
    typed = routing.resolve("vulnerability.probability", None, scenario_type="business_email_compromise")
    assert general[0].scenario_types == ()  # without a type, general routes lead
    assert general[-1].system_kind == "Phishing simulation platform"
    assert typed[0].system_kind == "Phishing simulation platform"
    assert [r.system_kind for r in typed[1:]] == [r.system_kind for r in general[:-1]]  # stable within ranks


def test_routes_typed_for_other_scenarios_go_last():
    routes = routing.resolve("primary_loss.replacement", None, scenario_type="ransomware")
    assert routes[-1].scenario_types == ("business_email_compromise",)
    assert all(not r.scenario_types for r in routes[:-1])


def test_route_scenario_types_use_the_scenario_vocabulary():
    from rqharness.schemas import load_schema
    vocabulary = set(load_schema("scenario")["properties"]["scenario_type"]["enum"])
    for route in routing.load_connector_map()["routes"]:
        assert set(route.get("scenario_types", [])) <= vocabulary - {"other"}, route
