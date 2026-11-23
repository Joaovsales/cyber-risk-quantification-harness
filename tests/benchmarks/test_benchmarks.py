"""Slice 11: the shipped benchmark library (AC18)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from rqharness import library
from rqharness.schemas import validate_document

SHIPPED = library.shipped_dir()
TYPES = [
    "ransomware",
    "business_email_compromise",
    "credential_phishing",
    "third_party_breach",
    "cloud_misconfiguration",
    "ddos",
    "insider_data_theft",
    "lost_or_stolen_device",
]
UNITS = {
    "frequency.lef": "events/year",
    "frequency.tef": "events/year",
    "frequency.contact": "events/year",
    "frequency.action": "probability",
    "vulnerability.probability": "probability",
    "secondary_loss.slef": "events/event",
}


def files() -> list[Path]:
    return sorted(SHIPPED.rglob("*.yaml"))


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_coverage_per_scenario_type():
    for scenario_type in TYPES:
        in_dir = list((SHIPPED / scenario_type).glob("*.yaml"))
        tagged = [p for p in files() if scenario_type in load(p)["scenario_tags"]]
        assert len(in_dir) >= 2, f"{scenario_type}: {len(in_dir)} entries in its directory"
        assert len(tagged) >= 2, f"{scenario_type}: {len(tagged)} tagged entries"


@pytest.mark.parametrize("path", files(), ids=lambda p: p.stem)
def test_every_entry_public_cited_segmented(path: Path):
    entry = load(path)
    assert validate_document("library-entry", entry, stem=path.stem) == []
    assert entry["entry_id"] == path.stem
    assert path.parent.name in entry["scenario_tags"]
    assert entry["tier"] == "benchmark"
    assert entry["sensitivity"] == "public"
    source = entry["source"]
    assert source["kind"] == "web"
    assert source["url"].startswith("https://") and "?" not in source["url"]
    assert source["retrieved_at"] == "2026-11-10"
    assert source["applicability_note"].strip()
    assert entry["segment"]["industry"] and entry["segment"]["size_band"]
    assert entry["stale_after_months"] == 18
    assert 0 < len(entry["note"]) <= 500
    value = entry["value"]
    assert value["min"] <= value["mode"] <= value["max"]
    expected = UNITS.get(entry["parameter_family"], "USD")
    assert value["unit"] == expected
    if expected == "probability":
        assert value["max"] <= 1


def test_library_search_returns_shipped_entries_as_benchmark():
    hits = library.search(
        library.LibraryQuery("primary_loss.response", scenario_type="ransomware"),
        workspace=None,
        today=date(2026, 11, 10),
    )
    assert hits and all(h.origin == "benchmark" for h in hits)
    assert all("ransomware" in h.entry["scenario_tags"] for h in hits)
