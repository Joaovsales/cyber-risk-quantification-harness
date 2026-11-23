"""The data-quality grade: how much of the result rests on the organisation's own data.

score = sum over parameters of contribution x tier score, where contributions are the
normalised sensitivity shares (they sum to 1), so the score lies in [0, 1]. The grade
maps the score to A-D (spec D13). ``improvement_priority`` ranks what to collect next:
the parameters whose uncertainty matters most and whose evidence is weakest.

Rows are the ones finalize builds from a validated inputs document, whose schema owns the
tier enum (spec D30), so an unknown tier is not re-checked here.
"""

from __future__ import annotations

from rqharness import tiers

TIER_SCORES: dict[str, float] = {name: tier.score for name, tier in tiers.TIERS.items()}
GRADE_THRESHOLDS: tuple[tuple[str, float], ...] = (("A", 0.85), ("B", 0.65), ("C", 0.40))
LOWEST_GRADE = "D"


def score(parameters: list[dict]) -> float:
    """Contribution-weighted tier score over summary ``parameters`` rows."""
    return float(sum(p["contribution"] * TIER_SCORES[p["tier"]] for p in parameters))


def grade(value: float) -> str:
    for letter, floor in GRADE_THRESHOLDS:
        if value >= floor:
            return letter
    return LOWEST_GRADE


def quality_block(parameters: list[dict]) -> dict:
    """The ``quality`` section finalize appends to ``run_summary.json``."""
    value = score(parameters)
    return {"score": value, "grade": grade(value), "tier_scores": dict(TIER_SCORES)}


def improvement_priority(parameters: list[dict]) -> list[dict]:
    """Rows ranked by contribution x (1 - tier score), highest first (ties by path)."""
    ranked = [
        {
            "path": p["path"],
            "label": p.get("label", p["path"]),
            "tier": p["tier"],
            "contribution": p["contribution"],
            "priority": p["contribution"] * (1.0 - TIER_SCORES[p["tier"]]),
        }
        for p in parameters
    ]
    return sorted(ranked, key=lambda r: (-r["priority"], r["path"]))
