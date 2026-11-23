"""The four provenance tiers and every per-tier policy, in one table (spec D13).

A tier says where an estimate's value came from. Each row carries what the rest of the
package needs to know about it: its weight in the data-quality score, its report badge,
how the report counts it, whether data collection should replace it, and which sources
let an estimate claim it. The keys are the schemas' tier enum, in the same best-first
order (tests/validate pins it).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    """The sources that let an estimate claim a tier; any one linked source is enough."""

    description: str  # how the rule reads in a validation issue
    kinds: frozenset[str]  # source kinds that qualify on their own
    memory_entry_tiers: frozenset[str] = frozenset()  # a memory source qualifies when its entry has one
    https_only: bool = False  # a qualifying source must carry an https:// URL

    def __post_init__(self) -> None:
        if "memory" in self.kinds:
            raise ValueError("a memory source qualifies through memory_entry_tiers, not kinds")

    def met_by(self, source: dict, entry_tier: str | None) -> bool:
        """Whether `source` qualifies; `entry_tier` is the tier of a memory source's library entry."""
        if source["kind"] == "memory":
            return entry_tier in self.memory_entry_tiers
        if source["kind"] not in self.kinds:
            return False
        return not self.https_only or str(source.get("url", "")).startswith("https://")


@dataclass(frozen=True)
class Tier:
    name: str
    score: float  # weight in the data-quality score
    letter: str  # report badge
    label: str  # report label
    is_own_data: bool  # the report counts it as coming from the organisation's own systems
    is_fallback: bool  # a public or assumed value that data collection should replace
    satisfied_by: Evidence | None  # None: no source needed (an assumption carries a rationale instead)


TIERS: dict[str, Tier] = {tier.name: tier for tier in (
    Tier("internal_data", 1.0, "I", "Internal data", is_own_data=True, is_fallback=False, satisfied_by=Evidence(
        "a person or internal_system source, or a memory source whose entry is internal_data",
        kinds=frozenset({"person", "internal_system"}), memory_entry_tiers=frozenset({"internal_data"}))),
    Tier("sme_estimate", 0.7, "S", "SME estimate", is_own_data=False, is_fallback=False, satisfied_by=Evidence(
        "a person source, or a memory source whose entry is sme_estimate or internal_data",
        kinds=frozenset({"person"}), memory_entry_tiers=frozenset({"sme_estimate", "internal_data"}))),
    Tier("benchmark", 0.4, "B", "Benchmark", is_own_data=False, is_fallback=True, satisfied_by=Evidence(
        "a web or benchmark_library source with an https:// URL",
        kinds=frozenset({"web", "benchmark_library"}), https_only=True)),
    Tier("agent_assumption", 0.1, "A", "Assumption", is_own_data=False, is_fallback=True, satisfied_by=None),
)}

# The tier a confirmed candidate takes from its evidence kind (the requests schema enum).
EVIDENCE_TIER: dict[str, str] = {"measured": "internal_data", "judgement": "sme_estimate"}
