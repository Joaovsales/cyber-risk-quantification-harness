"""AC27 and AC29: manifests, skill frontmatter, and the wording scan."""

from __future__ import annotations

import json
import re
import tomllib

from conftest import ROOT, SKILLS, frontmatter, read_skill

import rqharness

PLUGIN = ROOT / ".claude-plugin"


def _json(name: str) -> dict:
    return json.loads((PLUGIN / name).read_text(encoding="utf-8"))


def test_manifests_parse():
    plugin, market = _json("plugin.json"), _json("marketplace.json")
    for key in ("name", "version", "description", "author", "license", "keywords"):
        assert plugin[key], key
    assert plugin["name"] == "risk-quantification-harness"
    assert plugin["license"] == "Apache-2.0"
    assert set(plugin["author"]) == {"name"}
    assert set(market) == {"name", "owner", "plugins"}
    assert market["owner"]["name"]
    (entry,) = market["plugins"]
    assert set(entry) == {"name", "source", "description", "version"}
    assert entry["name"] == plugin["name"] and entry["source"] == "./"


def test_versions_match():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in pyproject["project"]["dynamic"]
    plugin, market = _json("plugin.json"), _json("marketplace.json")
    assert plugin["version"] == rqharness.__version__
    assert market["plugins"][0]["version"] == rqharness.__version__


def test_every_skill_has_frontmatter(skill_dirs):
    assert {d.name for d in skill_dirs} >= {
        "risk-quant", "scope-scenario", "collect-data", "simulate", "report",
        "risk-quant-resume", "risk-quant-org-setup", "risk-quant-memory",
    }
    for directory in skill_dirs:
        meta = frontmatter(read_skill(directory.name))
        assert meta["name"] == directory.name
        assert isinstance(meta["description"], str) and len(meta["description"]) > 40


def test_no_swag_and_no_fair_in_names(skill_dirs):
    scanned = [p for base in (SKILLS, PLUGIN, ROOT / "src/rqharness/report/templates")
               for p in base.rglob("*") if p.is_file()]
    assert scanned
    for path in scanned:
        assert not re.search("swag", path.read_text(encoding="utf-8"), re.IGNORECASE), path
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = [pyproject["project"]["name"], _json("plugin.json")["name"], *(d.name for d in skill_dirs)]
    assert all("fair" not in name.lower() for name in names)
