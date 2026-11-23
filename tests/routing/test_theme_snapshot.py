"""theme.snapshot.yaml has one owner: orgprofile writes it and reads it back; nobody else knows its keys."""

from __future__ import annotations

import ast
import inspect
from dataclasses import fields, replace
from pathlib import Path

import pytest

from rqharness import finalize, orgprofile
from rqharness.orgprofile import OrgProfile, Person, System, Theme
from rqharness.report import context, theme

FIXTURE = Path(__file__).parent / "fixtures" / "org-profile.yaml"
EMPTY = {"schema_version": "1", "org_name": None, "theme": {}, "people": [], "systems": []}
SNAPSHOT_KEYS = set(EMPTY) | {f.name for f in fields(Theme)}  # a new Theme field is guarded too


def _fixture_profile(tmp_path: Path) -> OrgProfile:
    (tmp_path / "org-profile.yaml").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    return orgprofile.load_profile(tmp_path)


# AC1 -----------------------------------------------------------------------------------------

def test_to_snapshot_without_a_profile():
    assert orgprofile.to_snapshot(None) == EMPTY


def test_to_snapshot_drops_unset_fields():
    profile = OrgProfile(org_name="Acme", segment={"industry": "x"}, teams=({"name": "SecOps"},),
                         people=(Person(name="Ada", role="CISO"),),
                         systems=(System(id="idp", kind="identity", name="Okta", owner_role="IT"),),
                         theme=Theme(accent="#112233", display_name="Acme Risk"))
    assert orgprofile.to_snapshot(profile) == {
        "schema_version": "1", "org_name": "Acme",
        "theme": {"accent": "#112233", "display_name": "Acme Risk"},
        "people": [{"name": "Ada", "role": "CISO"}],
        "systems": [{"id": "idp", "kind": "identity", "name": "Okta", "owner_role": "IT"}]}


def test_snapshot_round_trips_everything_the_report_reads(tmp_path):
    profile = _fixture_profile(tmp_path)
    # segment and teams are not part of the snapshot: the report reads neither
    assert orgprofile.from_snapshot(orgprofile.to_snapshot(profile)) == replace(profile, segment=None, teams=())


@pytest.mark.parametrize("snapshot", [EMPTY, {}, {"theme": None}, {"org_name": None, "people": None, "systems": None}])
def test_from_snapshot_of_no_profile_is_the_empty_profile(snapshot):
    assert orgprofile.from_snapshot(snapshot) == OrgProfile(
        org_name="", segment=None, teams=(), people=(), systems=(), theme=Theme())


@pytest.mark.parametrize(("org_name", "display_name", "shown"), [
    ("Acme", "Acme Risk", "Acme Risk"), ("Acme", None, "Acme"), ("", None, None), ("", "Acme Risk", "Acme Risk")])
def test_display_name_prefers_the_theme_over_the_org_name(org_name, display_name, shown):
    profile = orgprofile.from_snapshot({"org_name": org_name, "theme": {"display_name": display_name}})
    assert profile.display_name == shown


# AC2 -----------------------------------------------------------------------------------------

def _string_literals(source: str) -> set[str]:
    return {n.value for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


@pytest.mark.parametrize("module", [context, theme], ids=["context", "theme"])
def test_report_modules_never_name_a_snapshot_key(module):
    assert _string_literals(inspect.getsource(module)) & SNAPSHOT_KEYS == set()


def test_finalize_writes_the_snapshot_through_orgprofile():
    source = inspect.getsource(finalize._theme_snapshot)
    assert "orgprofile.to_snapshot(" in source
    assert _string_literals(source) & SNAPSHOT_KEYS == set()


def test_context_reads_the_snapshot_through_orgprofile():
    assert "orgprofile.from_snapshot(" in inspect.getsource(context.build_context)


def test_theme_renders_a_profile():
    for fn in (theme.theme_css, theme.logo_html):
        assert list(inspect.signature(fn).parameters) == ["profile"], fn.__name__
