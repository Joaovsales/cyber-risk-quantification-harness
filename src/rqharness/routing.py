"""Where each parameter family's evidence lives: system kind, owner role, artifact, example connectors."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from importlib import resources

import yaml

from rqharness.outcomes import Rejected
from rqharness.orgprofile import OrgProfile, Person, System
from rqharness.schemas import validate_document


@dataclass(frozen=True)
class Route:
    family: str
    system_kind: str
    owner_role: str
    expected_artifact: str
    ask: str
    connectors: tuple[str, ...]
    people: tuple[Person, ...] = ()
    systems: tuple[System, ...] = ()
    scenario_types: tuple[str, ...] = ()  # empty: the route suits every scenario type


@functools.lru_cache(maxsize=None)
def load_connector_map() -> dict:
    text = (resources.files("rqharness") / "data" / "connector-map.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    issues = validate_document("connector-map", data)
    if issues:
        raise Rejected(issues)
    return data


def families() -> list[str]:
    return sorted({route["family"] for route in load_connector_map()["routes"]})


def _same(a: str, b: str) -> bool:
    return a.strip().casefold() == b.strip().casefold()


def _scenario_rank(route_types: list[str], scenario_type: str | None) -> int:
    """0 for a route typed for this scenario, 1 for a general route, 2 for one typed for others."""
    if not route_types:
        return 1
    return 0 if scenario_type in route_types else 2


def resolve(parameter_family: str, profile: OrgProfile | None, *, scenario_type: str | None = None) -> list[Route]:
    """Routes for one estimate path; people and systems are filled from the profile when given.

    With a ``scenario_type``, routes tagged for that type come first, then general routes,
    then routes tagged only for other types (a stable sort keeps the map's order within each).
    """
    rows = [r for r in load_connector_map()["routes"] if r["family"] == parameter_family]
    if not rows:
        raise ValueError(f"unknown parameter family {parameter_family!r}")
    rows.sort(key=lambda r: _scenario_rank(r.get("scenario_types", []), scenario_type))
    routes = []
    for row in rows:
        people = systems = ()
        if profile is not None:
            people = tuple(p for p in profile.people if _same(p.role, row["owner_role"]))
            systems = tuple(s for s in profile.systems
                            if _same(s.owner_role, row["owner_role"]) or _same(s.kind, row["system_kind"]))
        routes.append(Route(row["family"], row["system_kind"], row["owner_role"], row["expected_artifact"],
                            row["ask"], tuple(row["connectors"]), people, systems,
                            tuple(row.get("scenario_types", ()))))
    return routes
