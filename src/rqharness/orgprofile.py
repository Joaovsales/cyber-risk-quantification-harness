"""The optional organisation profile: who owns which system, and how the report is themed."""

from __future__ import annotations

import base64
import binascii
from dataclasses import asdict, dataclass
from pathlib import Path

from rqharness.outcomes import Issue, Rejected, issue
from rqharness.schemas import load_yaml, validate_document

PROFILE_FILENAME = "org-profile.yaml"
MAX_LOGO_BYTES = 200 * 1024
_STEM = "org-profile"


@dataclass(frozen=True)
class Person:
    name: str
    role: str
    team: str | None = None
    contact_hint: str | None = None


@dataclass(frozen=True)
class System:
    id: str
    kind: str
    name: str
    owner_role: str
    connector: str | None = None


@dataclass(frozen=True)
class Theme:
    logo_data_uri: str | None = None
    accent: str | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class OrgProfile:
    org_name: str
    segment: dict | None
    teams: tuple[dict, ...]
    people: tuple[Person, ...]
    systems: tuple[System, ...]
    theme: Theme

    @property
    def display_name(self) -> str | None:
        """The name the report shows: the theme's display name, else the org name; None when neither is set."""
        return self.theme.display_name or self.org_name or None


def _logo_issues(data: dict) -> list[Issue]:
    theme = data.get("theme")
    uri = theme.get("logo_data_uri") if isinstance(theme, dict) else None
    if not isinstance(uri, str) or ";base64," not in uri:
        return []
    try:
        size = len(base64.b64decode(uri.split(";base64,", 1)[1], validate=True))
    except (binascii.Error, ValueError):
        return []  # the schema's pattern already reports malformed data
    if size > MAX_LOGO_BYTES:
        return [issue(f"{_STEM}.theme.logo_data_uri", "logo_too_large",
                      f"logo decodes to {size} bytes; the limit is {MAX_LOGO_BYTES}")]
    return []


def validate_profile(data: object) -> list[Issue]:
    """Schema issues plus the decoded-size rule for the logo."""
    issues = validate_document(_STEM, data)
    return issues + _logo_issues(data) if isinstance(data, dict) else issues


def _build(data: dict) -> OrgProfile:
    return OrgProfile(
        org_name=data["org_name"],
        segment=data.get("segment"),
        teams=tuple(data.get("teams", [])),
        people=tuple(Person(**p) for p in data.get("people", [])),
        systems=tuple(System(**s) for s in data.get("systems", [])),
        theme=Theme(**data.get("theme", {})),
    )


def load_profile(workspace: Path) -> OrgProfile | None:
    """The workspace's profile, ``None`` when absent; an invalid file raises :class:`Rejected`."""
    path = workspace / PROFILE_FILENAME
    if not path.is_file():
        return None
    data, issues = load_yaml(path, _STEM)
    if not issues:
        issues = validate_profile(data)
    if issues:
        raise Rejected(issues)
    return _build(data)


# --- theme.snapshot.yaml ---------------------------------------------------------------------------
# The part of the profile a version freezes, so rendering reads only ``v<N>/``. This pair is the
# format's only reader and writer; segment and teams stay out because the report reads neither.

_SNAPSHOT_VERSION = "1"


def _compact(obj: object) -> dict:
    return {k: v for k, v in asdict(obj).items() if v is not None}


def to_snapshot(profile: OrgProfile | None) -> dict:
    """The theme snapshot of ``profile``; unset fields are left out. ``None`` gives the empty snapshot."""
    if profile is None:
        return {"schema_version": _SNAPSHOT_VERSION, "org_name": None, "theme": {}, "people": [], "systems": []}
    return {
        "schema_version": _SNAPSHOT_VERSION,
        "org_name": profile.org_name,
        "theme": _compact(profile.theme),
        "people": [_compact(p) for p in profile.people],
        "systems": [_compact(s) for s in profile.systems],
    }


def from_snapshot(snapshot: dict) -> OrgProfile:
    """The profile a theme snapshot froze, with no segment or teams; the empty snapshot gives an unnamed profile."""
    theme = snapshot.get("theme")
    return OrgProfile(
        org_name=snapshot.get("org_name") or "", segment=None, teams=(),
        people=tuple(Person(**p) for p in snapshot.get("people") or ()),
        systems=tuple(System(**s) for s in snapshot.get("systems") or ()),
        theme=Theme(**theme) if isinstance(theme, dict) else Theme(),
    )
