"""The provenance tiers and their policies live in one table, rqharness/tiers.py."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rqharness import quality, requests, schemas, tiers, validate
from rqharness.report import context

PACKAGE = Path(tiers.__file__).parent


def _enum(kind: str, *path: str) -> list[str]:
    node = schemas.load_schema(kind)
    for key in path:
        node = node[key]
    return node["enum"]


def test_tier_names_equal_the_schema_enums():
    names = list(tiers.TIERS)
    assert names == _enum("inputs", "$defs", "provenance", "properties", "tier")
    assert names == _enum("library-entry", "properties", "tier")
    assert all(tier.name == name for name, tier in tiers.TIERS.items())


def test_evidence_kinds_equal_the_requests_schema_enum():
    candidate = schemas.load_schema("requests")["$defs"]["candidate"]
    assert list(tiers.EVIDENCE_TIER) == candidate["properties"]["evidence_kind"]["enum"]
    assert set(tiers.EVIDENCE_TIER.values()) <= set(tiers.TIERS)


def test_consumers_read_the_tier_table():
    assert quality.TIER_SCORES == {name: tier.score for name, tier in tiers.TIERS.items()}
    assert [context._tier(name) for name in tiers.TIERS] == [
        {"letter": tier.letter, "label": tier.label} for tier in tiers.TIERS.values()]
    inputs = {"parameters": {"frequency": {name: {"provenance": {"tier": name}} for name in tiers.TIERS}}}
    assert requests.fallback_parameters(inputs) == [
        f"frequency.{name}" for name, tier in tiers.TIERS.items() if tier.is_fallback]


# Library origins ("memory" | "benchmark") share the word "benchmark" with the tier; a different vocabulary.
_NOT_A_TIER = {("library.py", "benchmark")}


def test_no_module_but_tiers_names_a_tier():
    found = []
    for path in sorted(PACKAGE.rglob("*.py")):
        where = path.relative_to(PACKAGE).as_posix()
        if where == "tiers.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and node.value in tiers.TIERS and (where, node.value) not in _NOT_A_TIER:
                found.append(f"{where}:{node.lineno} {node.value!r}")
    assert not found, found


def test_a_memory_source_qualifies_only_through_its_entry_tier():
    with pytest.raises(ValueError, match="memory_entry_tiers"):
        tiers.Evidence("x", kinds=frozenset({"memory"}))


# The evidence rules as they stood before the table (validate._tier_satisfied), every case.
_RULES = [
    # tier, source, library entry tier, satisfied
    ("benchmark", {"kind": "web", "url": "https://x.example"}, None, True),
    ("benchmark", {"kind": "benchmark_library", "url": "https://x.example"}, None, True),
    ("benchmark", {"kind": "web", "url": "http://x.example"}, None, False),
    ("benchmark", {"kind": "web"}, None, False),
    ("benchmark", {"kind": "person"}, None, False),
    ("benchmark", {"kind": "memory", "library_entry_id": "e"}, "benchmark", False),
    ("internal_data", {"kind": "person"}, None, True),
    ("internal_data", {"kind": "internal_system"}, None, True),
    ("internal_data", {"kind": "web", "url": "https://x.example"}, None, False),
    ("internal_data", {"kind": "memory", "library_entry_id": "e"}, "internal_data", True),
    ("internal_data", {"kind": "memory", "library_entry_id": "e"}, "sme_estimate", False),
    ("internal_data", {"kind": "memory", "library_entry_id": "e"}, None, False),
    ("sme_estimate", {"kind": "person"}, None, True),
    ("sme_estimate", {"kind": "internal_system"}, None, False),
    ("sme_estimate", {"kind": "memory", "library_entry_id": "e"}, "sme_estimate", True),
    ("sme_estimate", {"kind": "memory", "library_entry_id": "e"}, "internal_data", True),
    ("sme_estimate", {"kind": "memory", "library_entry_id": "e"}, "benchmark", False),
    ("agent_assumption", {"kind": "person"}, None, False),
]


@pytest.mark.parametrize("tier,source,entry_tier,satisfied", _RULES)
def test_evidence_rules(tier, source, entry_tier, satisfied):
    entries = {"e": {"tier": entry_tier} if entry_tier else None}
    assert validate._tier_satisfied(tier, [source], entries) is satisfied


def test_only_agent_assumption_needs_no_source():
    assert [name for name, tier in tiers.TIERS.items() if tier.satisfied_by is None] == ["agent_assumption"]
