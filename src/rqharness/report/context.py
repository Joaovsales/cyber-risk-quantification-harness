"""The report view model: everything the template shows, computed from one ``v<N>/`` directory.

Pure: reads only the version's own files. How a figure prints belongs to ``formatting``; this
module decides which figures each section shows.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from markupsafe import Markup

from rqharness import orgprofile, quality, routing, tiers, workspace
from rqharness.outcomes import Rejected, issue
from rqharness.orgprofile import OrgProfile
from rqharness.report import narrative, svg, theme
from rqharness.report.formatting import fmt_int, fmt_money, fmt_pct, fmt_rate, largest_cut, lower_first, pick_focus
from rqharness.summary import estimate_at

_GRADE_NOTES = {
    "A": "Inputs come mostly from the organisation's own data.",
    "B": "Inputs mix the organisation's own data with expert estimates.",
    "C": "Most inputs are benchmarks or assumptions.",
    "D": "Inputs rest mostly on assumptions.",
}
_SOURCE_KINDS = {
    "person": "Person", "internal_system": "Internal system", "web": "Web page",
    "benchmark_library": "Benchmark library", "memory": "Memory library",
}
_STATS = (("Mean", "mean"), ("p10", "p10"), ("p25", "p25"), ("p50 (median)", "median"),
          ("p75", "p75"), ("p90", "p90"), ("p95", "p95"), ("p99", "p99"))
DISCLOSURE = "Loss magnitudes use Beta-PERT distributions (gamma = 4) elicited per FAIR-aligned loss form."
YOLO_NOTE = "Benchmark-based estimate. Not yet validated against {org}'s own data."


# --- estimates in the provenance table -------------------------------------------------------------

def _fmt_amount(x: float) -> str:
    return fmt_int(x) if abs(x) >= 100 else f"{x:.2f}".rstrip("0").rstrip(".")


def _fmt_estimate(value: float, unit: str) -> str:
    if re.fullmatch(r"[A-Z]{3}", unit):
        return fmt_money(value, unit)
    return fmt_pct(value) if unit == "probability" else _fmt_amount(value)


def _unit_text(unit: str) -> str:
    return f"{unit} per event" if re.fullmatch(r"[A-Z]{3}", unit) else unit.replace("/", " per ")


# --- what the headline figures centre on -----------------------------------------------------------

def _round_threshold(mean: float) -> float:
    """The largest 1, 2.5 or 5 x 10^k not above the baseline mean: a round amount near it."""
    if mean < 1:
        return 1.0
    scale = 10.0 ** (len(str(int(mean))) - 1)
    return max(c * scale for c in (1.0, 2.5, 5.0) if c * scale <= mean)


@dataclass(frozen=True)
class _Story:
    """The variants and the loss threshold the headline figures talk about, picked once for every section."""

    base: dict  # the baseline variant: current controls
    focus: dict | None  # the delta the story centres on (pick_focus)
    focus_variant: dict | None  # the variant that delta describes
    cut: dict | None  # the delta with the largest cut in mean loss
    cut_variant: dict | None
    threshold: float  # a round annual loss near the baseline mean
    chance: dict[str, float]  # per variant id: the chance of a year above the threshold

    @classmethod
    def of(cls, summary: dict) -> _Story:
        variants = summary["variants"]
        by_id = {v["id"]: v for v in variants}
        focus, cut = pick_focus(summary), largest_cut(summary)
        threshold = _round_threshold(variants[0]["annual_loss"]["mean"])
        return cls(base=variants[0], focus=focus, focus_variant=by_id[focus["variant"]] if focus else None,
                   cut=cut, cut_variant=by_id[cut["variant"]] if cut else None, threshold=threshold,
                   chance={v["id"]: svg.exceedance(v["lec"]["points"], threshold) for v in variants})

    @property
    def base_chance(self) -> float:
        return self.chance[self.base["id"]]


# --- loading ---------------------------------------------------------------------------------------

_CURRENCY = re.compile(r"[A-Z]{3}")


def load_summary(version_dir: Path) -> dict:
    """The version's ``run_summary.json``; raises ``Rejected`` when its currency is no ISO 4217 code.

    The currency is printed into the page as markup, and finalize only ever writes a validated code,
    so anything else is a hand-edited summary the report refuses to show.
    """
    summary = json.loads((version_dir / "run_summary.json").read_text(encoding="utf-8"))
    currency = summary.get("currency") if isinstance(summary, dict) else None
    if not (isinstance(currency, str) and _CURRENCY.fullmatch(currency)):
        where = f"{version_dir.name}/run_summary.json"
        raise Rejected([issue(f"{where}.currency", "pattern",
                              f"{where} currency is not a three-letter ISO 4217 code; run `rqh finalize` again")])
    return summary


def _takeaway(version_dir: Path, summary: dict, scenario: dict, *, omit_narrative: bool) -> str:
    """The stored narrative's HTML, else the fixed sentence; a stored narrative that fails the rule is refused."""
    stored = version_dir / "narrative.md"
    if omit_narrative or not stored.is_file():
        return narrative.fixed_takeaway(summary, scenario)
    result = narrative.render_narrative(stored.read_text(encoding="utf-8"), summary)
    if result.rejected is not None:
        raise result.rejected.error(stored=f"{version_dir.name}/narrative.md")
    return result.html


def _snapshot(version_dir: Path, name: str) -> dict:
    """One of the version's frozen YAML snapshots, dates as ISO strings. Every snapshot is required."""
    path = version_dir / name
    if not path.is_file():
        raise FileNotFoundError(path)
    return workspace.read_yaml(path) or {}


# --- sections --------------------------------------------------------------------------------------

def _tier(name: str) -> dict:
    tier = tiers.TIERS[name]
    return {"letter": tier.letter, "label": tier.label}


def _hero(summary: dict, story: _Story) -> list[dict]:
    currency, base_loss, focus, focus_v = summary["currency"], story.base["annual_loss"], story.focus, story.focus_variant
    hero = [{"value": fmt_money(base_loss["mean"], currency, short=True), "cap": "Estimated annual loss today (mean)",
             "cls": "num-xl"}]
    p90 = {"value": fmt_money(base_loss["p90"], currency, short=True), "cap": "Loss in a 1-in-10 year (p90)",
           "cls": "num-l"}
    if focus:
        focus_cost = focus_v.get("annual_cost")
        hero.append({"value": f"−{fmt_pct(focus['ale_reduction_mean'] / base_loss['mean'])}" if base_loss["mean"] else "—",
                     "cap": f"Mean loss with {focus_v['label']}", "cls": "num-l sig"})
        hero.append({"value": fmt_money(focus_cost["mean"], currency, short=True), "cap": f"Annual cost of {focus_v['label']}",
                     "cls": "num-l"} if focus_cost else p90)
    else:
        hero.append(p90)
        hero.append({"value": fmt_pct(story.base_chance),
                     "cap": f"Chance annual loss exceeds {fmt_money(story.threshold, currency, short=True)}",
                     "cls": "num-l"})
    return hero


def _cards(summary: dict, story: _Story) -> list[dict]:
    currency, base_loss, focus, cut = summary["currency"], story.base["annual_loss"], story.focus, story.cut
    chance = story.base_chance
    cards = [
        {"ix": "A1", "title": "Baseline expected annual loss (mean)", "value": fmt_money(base_loss["mean"], currency),
         "note": f"Average of {fmt_int(summary['n'])} simulated years with current controls.", "sig": False},
        {"ix": "A2", "title": "1-in-10-year loss (p90)", "value": fmt_money(base_loss["p90"], currency),
         "note": "One year in ten costs this much or more.", "sig": False},
        {"ix": "A3", "title": f"Chance annual loss exceeds {fmt_money(story.threshold, currency, short=True)}",
         "value": fmt_pct(chance),
         "note": "With current controls: " + ("more likely than not." if chance >= 0.5 else "less likely than not."),
         "sig": False},
    ]
    if cut:
        cards.append({"ix": "A4", "title": "Risk reduction, best variant",
                      "value": fmt_pct(cut["ale_reduction_mean"] / base_loss["mean"]) if base_loss["mean"] else "—",
                      "note": f"{story.cut_variant['label']}: mean loss falls by "
                              f"{fmt_money(cut['ale_reduction_mean'], currency)}.",
                      "sig": True})
    if focus and focus.get("return_on_control") is not None:
        focus_v = story.focus_variant
        cost = focus_v["annual_cost"]["mean"] if focus_v.get("annual_cost") else 0.0
        cards.append({"ix": "A5", "title": f"Return on control, {focus_v['label']}",
                      "value": fmt_rate(focus["return_on_control"]),
                      "note": f"{fmt_money(cost, currency)} a year avoids {fmt_money(focus['ale_reduction_mean'], currency)} "
                              f"of mean loss.", "sig": True})
    return cards


def _collect_next(summary: dict, profile: OrgProfile, *, scenario_type: str | None = None) -> list[dict]:
    ranked = quality.improvement_priority(summary["parameters"])[:3]
    top = ranked[0]["priority"] if ranked else 0.0
    rows = []
    for row in ranked:
        route = routing.resolve(row["path"], profile, scenario_type=scenario_type)[0]
        rows.append({
            "path": row["path"], "label": row["label"], "tier": _tier(row["tier"]),
            "priority": f"{row['priority']:.2f}", "priority_width": f"{100 * row['priority'] / top:.0f}" if top else "0",
            "ask": route.ask, "owner_role": route.owner_role,
            "system": route.systems[0].name if route.systems else route.system_kind,
            "person": route.people[0].name if route.people else None,
            "connectors": list(route.connectors),
        })
    return rows


def _provenance(summary: dict, inputs: dict) -> list[dict]:
    sources = {s["id"]: s for s in inputs.get("sources", [])}
    rows = []
    for i, p in enumerate(summary["parameters"], 1):
        rationale = estimate_at(inputs, p["path"]).get("provenance", {}).get("rationale")
        found = []
        for sid in p["source_ids"]:
            s = sources.get(sid, {"title": sid, "kind": ""})
            sub = [_SOURCE_KINDS.get(s["kind"], ""), f"owner: {s['owner_role']}" if s.get("owner_role") else "",
                   s.get("applicability_note", "")]
            url = s.get("url", "")
            found.append({"title": s["title"], "url": url if url.startswith("https://") else None,
                          "sub": " · ".join(x for x in sub if x)})
        if not found:
            found.append({"title": rationale or "No source recorded", "url": None, "sub": "Agent assumption"})
        unit = p["unit"]
        rows.append({
            "n": f"{i:02d}", "label": p["label"], "path": p["path"], "tier": _tier(p["tier"]),
            "pert": " / ".join(_fmt_estimate(p[k], unit) for k in ("min", "mode", "max")),
            "unit": _unit_text(unit), "sources": found,
        })
    return rows


def _drivers(summary: dict) -> tuple[list[dict], list[str]]:
    ranked = sorted(summary["parameters"], key=lambda p: -p["contribution"])
    top = max((p["contribution"] for p in ranked), default=0.0)
    axis_max = max(-(-round(top * 100) // 10) * 10, 10) / 100  # next whole 10% at or above the top share
    ticks = [f"{round(axis_max * 100 * k / 5)}%" for k in range(6)]
    rows, before = [], 0.0
    for i, p in enumerate(ranked, 1):
        rows.append({"rank": f"{i:02d}", "label": p["label"], "tier": _tier(p["tier"]),
                     "share": fmt_pct(p["contribution"]), "width": f"{100 * p['contribution'] / axis_max:.1f}",
                     "hi": before < 0.5})
        before += p["contribution"]
    return rows, ticks


def _variant_rows(summary: dict, story: _Story) -> list[dict]:
    currency = summary["currency"]
    deltas = {d["variant"]: d for d in summary["deltas"]}
    base = story.base["annual_loss"]["mean"]
    several = len(deltas) > 1
    rows = []
    for i, v in enumerate(summary["variants"]):
        d, cost = deltas.get(v["id"]), v.get("annual_cost")
        avoided = None
        if d:
            share = d["ale_reduction_mean"] / base if base else 0.0
            avoided = f"{fmt_money(d['ale_reduction_mean'], currency)} ({fmt_pct(share)})"
        rows.append({
            "label": v["label"], "swatch": svg.swatch(i),
            "cost": fmt_money(cost["mean"], currency) if cost else None,
            "mean": fmt_money(v["annual_loss"]["mean"], currency),
            "p90": fmt_money(v["annual_loss"]["p90"], currency), "avoided": avoided,
            "roc": fmt_rate(d["return_on_control"]) if d and d["return_on_control"] is not None else None,
            "flags": [name for name, pick in (("BEST RETURN", story.focus), ("LARGEST CUT", story.cut))
                      if several and d and pick and pick["variant"] == v["id"]],
        })
    return rows


def _headlines(summary: dict, story: _Story, *, org: str | None, provenance: list[dict],
               drivers: list[dict]) -> dict:
    currency, base, focus, cut = summary["currency"], story.base, story.focus, story.cut
    mean_s = fmt_money(base["annual_loss"]["mean"], currency, short=True)
    p90_s = fmt_money(base["annual_loss"]["p90"], currency, short=True)
    heads = {"summary": f"Expect about {mean_s} a year in losses, and {p90_s} or more in a bad one-in-ten year"}
    thr_s = fmt_money(story.threshold, currency, short=True)
    base_chance = fmt_pct(story.base_chance)
    if focus:
        heads["lec"] = (f"{story.focus_variant['label']} cuts the chance of a {thr_s}-plus year from {base_chance} "
                        f"to {fmt_pct(story.chance[focus['variant']])}")
    else:
        heads["lec"] = f"A {thr_s}-plus year has a {base_chance} chance with current controls"
    heads["distribution"] = (f"Today a typical year costs about {fmt_money(base['annual_loss']['median'], currency, short=True)}"
                             f", and one year in 100 passes {fmt_money(base['annual_loss']['p99'], currency, short=True)}")
    lead = drivers[:2]
    share = sum(r["contribution"] for r in sorted(summary["parameters"], key=lambda p: -p["contribution"])[:2])
    heads["drivers"] = (f"Two inputs drive {fmt_pct(share)} of the uncertainty: "
                        f"{lower_first(lead[0]['label'])} and {lower_first(lead[1]['label'])}"
                        if len(lead) > 1 else f"{lead[0]['label']} drives all of the uncertainty")
    if focus and focus.get("return_on_control") is not None:
        heads["variants"] = f"{story.focus_variant['label']} returns {fmt_rate(focus['return_on_control'])} its cost"
        if cut and cut["variant"] != focus["variant"]:
            heads["variants"] += f"; {story.cut_variant['label']} cuts more loss but returns less per dollar"
    elif focus:
        heads["variants"] = f"{story.focus_variant['label']} cuts mean loss the most of the controls modelled"
    else:
        heads["variants"] = "Only the current controls were modelled, so there is nothing to compare yet"
    row_tiers = [tiers.TIERS[p["tier"]] for p in summary["parameters"]]  # the provenance rows, in order
    own = sum(tier.is_own_data for tier in row_tiers)
    weak = sum(tier.is_fallback for tier in row_tiers)
    whose = f"{org}'s own systems" if org else "your organisation's own systems"
    total = len(provenance)
    lead_in = f"Only {own} of {total} inputs comes" if own == 1 else (
        f"None of the {total} inputs comes" if own == 0 else f"Only {own} of {total} inputs come")
    heads["provenance"] = f"{lead_in} from {whose}; {weak} rely on public benchmarks or assumptions"
    return heads


def _scenario(scenario: dict, *, org: str | None) -> dict:
    segment = scenario.get("segment") or {}
    facts = [("Threat actor", scenario["threat_actor"]["description"], scenario["threat_actor"]["category"].replace("_", " ")),
             ("Asset", scenario["asset"]["description"], ""),
             ("Method", scenario["method"]["description"], ""),
             ("Loss event", scenario["loss_event_definition"].strip(), ""),
             ("Controls today", scenario.get("controls_context", "").strip(), ""),
             ("Out of scope", "; ".join(scenario.get("out_of_scope", [])), "")]
    segment_note = " · ".join(str(x).replace("_", " ") for x in (segment.get("industry"), segment.get("size_band")) if x)
    return {"statement": " ".join(scenario["scenario_statement"].split()), "facts": facts,
            "org_note": f"Organisation: {org}" + (f" ({segment_note})" if segment_note else "") if org else
                        (f"Segment: {segment_note}" if segment_note else "")}


def _appendix(summary: dict, manifest: dict) -> dict:
    currency, variants = summary["currency"], summary["variants"]
    years = summary["analysis_period_years"]
    return {
        "facts": [("Simulated years (n)", fmt_int(summary["n"])), ("Seed", str(summary["seed"])),
                  ("Package version", manifest["package_version"]), ("NumPy version", manifest["numpy_version"]),
                  ("SciPy version", manifest["scipy_version"]), ("Inputs hash (SHA-256)", manifest["inputs_sha256"]),
                  ("PERT method", f"Beta-PERT, gamma = 4 ({manifest['pert_method']})"),
                  ("Currency / period", f"{currency} / {years:g} {'year' if years == 1 else 'years'}"),
                  ("Generated (UTC)", manifest["generated_at"])],
        "disclosure": DISCLOSURE,
        "columns": [v["label"] for v in variants],
        "stats": [(label, [fmt_money(v["annual_loss"][key], currency) for v in variants]) for label, key in _STATS]
                 + [("Chance of any loss", [fmt_pct(v["p_annual_loss_gt_0"]) for v in variants]),
                    ("Loss events a year (mean)", [f"{v['event_count']['mean']:.2f}" for v in variants])],
    }


def build_context(version_dir: Path, *, omit_narrative: bool = False) -> dict:
    """The view model of one version.

    Raises FileNotFoundError when a required file is absent, ``Rejected`` for a summary
    ``load_summary`` refuses, and ``NarrativeRejected`` for a stored narrative that fails the rule.
    """
    summary = load_summary(version_dir)
    manifest = json.loads((version_dir / "run_manifest.json").read_text(encoding="utf-8"))
    inputs = _snapshot(version_dir, "inputs.snapshot.yaml")
    scenario = _snapshot(version_dir, "scenario.snapshot.yaml")
    profile = orgprofile.from_snapshot(_snapshot(version_dir, "theme.snapshot.yaml"))

    currency, n, variants = summary["currency"], summary["n"], summary["variants"]
    story = _Story.of(summary)
    org = profile.display_name
    whose = f"{org}'s" if org else "your organisation's"
    route = manifest.get("route", "")

    takeaway = Markup(_takeaway(version_dir, summary, scenario, omit_narrative=omit_narrative))

    provenance = _provenance(summary, inputs)
    driver_rows, driver_ticks = _drivers(summary)
    lec_variants = [{"id": v["id"], "label": v["label"], "points": v["lec"]["points"]} for v in variants]
    chances = [{"label": v["label"], "swatch": svg.swatch(i), "value": fmt_pct(story.chance[v["id"]]),
                "width": f"{100 * story.chance[v['id']]:.1f}"} for i, v in enumerate(variants)]
    hists = [{"id": v["id"], "label": v["label"], "hidden": i > 0,
              "svg": svg.histogram_chart({"id": v["id"], "label": v["label"], "edges": v["histogram"]["edges"],
                                          "counts": v["histogram"]["counts"], "above": v["histogram"]["above"],
                                          "mean": v["annual_loss"]["mean"], "p90": v["annual_loss"]["p90"],
                                          "median": v["annual_loss"]["median"]}, currency, n)}
             for i, v in enumerate(variants)]

    return {
        "title": scenario["title"], "scenario_id": scenario["scenario_id"], "version": manifest["version"],
        "org": org, "whose": whose, "route": route, "route_label": route.upper() if route == "yolo" else route.capitalize(),
        "generated": manifest["generated_at"], "date": manifest["generated_at"][:10],
        "yolo_note": YOLO_NOTE.format(org=org or "your organisation") if route == "yolo" else None,
        "grade": {"letter": summary["quality"]["grade"], "score": f"{summary['quality']['score']:.2f}",
                  "note": _GRADE_NOTES[summary["quality"]["grade"]]},
        "takeaway": takeaway, "narrative_used": not omit_narrative and (version_dir / "narrative.md").is_file(),
        "hero": _hero(summary, story), "cards": _cards(summary, story),
        "heads": _headlines(summary, story, org=org, provenance=provenance, drivers=driver_rows),
        "lec_svg": svg.lec_chart(lec_variants, currency, story.threshold), "lec_n": fmt_int(n),
        "threshold_label": fmt_money(story.threshold, currency, short=True), "chances": chances,
        "hists": hists, "drivers": driver_rows, "driver_ticks": driver_ticks,
        "variant_rows": _variant_rows(summary, story),
        "scenario": _scenario(scenario, org=org),
        "provenance": provenance,
        "appendix": _appendix(summary, manifest),
        "collect_next": _collect_next(summary, profile, scenario_type=scenario.get("scenario_type")),
        "collect_lede": f"{whose} own data",
        "theme_css": Markup(theme.theme_css(profile)), "logo": Markup(theme.logo_html(profile)),
        # True when --omit-narrative replaced the stored narrative with the fixed sentence
        "narrative_omitted": omit_narrative,
    }
