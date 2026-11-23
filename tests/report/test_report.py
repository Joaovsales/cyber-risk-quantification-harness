"""Slice 13: the report renderer and static charts (AC21, AC22)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil

import pytest
import yaml
from html.parser import HTMLParser

from rqharness import cli, outcomes, quality
from rqharness.report import context, formatting, render, svg

from pathlib import Path

RUN_ID = "credential-phishing-bec"
SAMPLE = Path(__file__).resolve().parents[1] / "validate" / "fixtures" / "sample-run"

HOSTILE = "<script>alert(1)</script>"
SECTIONS = ["takeaway", "summary", "lec", "distribution", "drivers", "variants", "scenario",
            "provenance", "appendix", "collect"]


class Doc(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict]] = []
        self.sections: list[tuple[str, str, dict]] = []
        self.text: list[str] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "data-section" in a:
            self.sections.append((a["data-section"], tag, a))

    def handle_data(self, data):
        self.text.append(data)


def expected_csp(html: str) -> str:
    """The policy the page must carry: its one inline script allowed by hash, nothing else."""
    (body,) = re.findall(r"<script>(.*?)</script>", html, flags=re.S)
    digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("ascii")
    return (f"default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src 'sha256-{digest}'; "
            "base-uri 'none'; form-action 'none'")


def rendered(run) -> str:
    out = render.render_report(run)
    assert isinstance(out, render.Rendered), out
    return out.path.read_text(encoding="utf-8")


# AC21 -----------------------------------------------------------------------------------------

def test_self_contained(make_run):
    html = rendered(make_run())
    doc = Doc(html)
    csp = [a for t, a in doc.tags if t == "meta" and a.get("http-equiv") == "Content-Security-Policy"]
    assert [a["content"] for a in csp] == [expected_csp(html)]
    assert "unsafe-inline" not in csp[0]["content"].split("script-src")[1]
    for tag, attrs in doc.tags:
        assert tag != "link" and not (tag == "script" and "src" in attrs)
        assert not [name for name in attrs if name.startswith("on")], (tag, attrs)  # a hash allows no handler
        for name in ("src", "srcset", "href", "xlink:href"):
            value = (attrs.get(name) or "").strip()
            if value.startswith(("http:", "//", "https:")):
                assert tag == "a" and name == "href" and value.startswith("https://"), (tag, name, value)
                assert attrs.get("rel") == "noopener noreferrer"
    assert "@import" not in html
    for url in re.findall(r"url\(([^)]*)\)", html):
        assert url.strip("'\" ").startswith("data:")
    assert "https://www.verizon.com/business/resources/reports/dbir/" in html


def test_size_budget(full_html):
    assert len(full_html.encode("utf-8")) <= 1_000_000


def test_escapes_markup(make_run):
    def edit(name, text):
        if name == "scenario.yaml":
            return text.replace("title: Credential phishing leads to business email compromise",
                                "title: <script>alert(1)</script>")
        return text.replace("title: Verizon DBIR 2025, social engineering", "title: <img src=x onerror=alert(2)>")

    html = rendered(make_run(edit=edit))
    assert "<script>alert(1)" not in html and "<img src=x" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=alert(2)&gt;" in html
    assert not [t for t, _ in Doc(html).tags if t == "img"]


def test_reads_only_version_dir(make_run, tmp_path):
    run = make_run()
    first = rendered(run)
    for name in ("inputs.yaml", "scenario.yaml", "run.yaml"):
        (run / name).write_text("garbage: [", encoding="utf-8")
    (tmp_path / ".riskquant" / "org-profile.yaml").unlink()
    assert rendered(run) == first


def test_render_idempotent(make_run):
    run = make_run()
    first = rendered(run)
    first_bytes = (run / "v1" / "report.html").read_bytes()
    assert rendered(run) == first
    assert (run / "v1" / "report.html").read_bytes() == first_bytes


# AC22 -----------------------------------------------------------------------------------------

def test_section_order(make_run):
    doc = Doc(rendered(make_run()))
    assert [s for s, _, _ in doc.sections] == SECTIONS
    appendix = [(t, a) for s, t, a in doc.sections if s == "appendix"]
    assert appendix[0][0] == "details" and "open" not in appendix[0][1]
    text = " ".join(doc.text)
    assert "YOLO" in text
    assert "Not yet validated against Northwind's own data." in text  # the profile's display name


def test_yolo_banner_only_for_yolo_route(make_run):
    html = rendered(make_run(route="accuracy"))
    assert 'class="yolo"' not in html and "Not yet validated" not in html


def profile_with(*people: dict) -> str:
    """The routing fixture profile plus extra people (so the top-three owners have names)."""
    data = yaml.safe_load((Path(__file__).resolve().parents[1] / "routing" / "fixtures" / "org-profile.yaml")
                          .read_text(encoding="utf-8"))
    data["people"] += list(people)
    return yaml.safe_dump(data)


# The fixture profile already names the security awareness lead and the controller.
KNOWN = ({"name": "Ivy Chen", "role": "Incident response lead"},)
OWNERS = ["Priya Nair", "Sam Okafor", "Ivy Chen"]


def test_collect_section_top_three(make_run):
    run = make_run(profile=profile_with(*KNOWN))
    html = rendered(run)
    summary = json.loads((run / "v1" / "run_summary.json").read_text(encoding="utf-8"))
    top = quality.improvement_priority(summary["parameters"])[:3]
    block = html[html.index('data-section="collect"'):]
    assert re.findall(r'data-path="([^"]+)"', block) == [r["path"] for r in top]
    assert block.count('class="ck"') == 3
    assert "Owner" in block and "System of record" in block
    assert all(name in block for name in OWNERS)


def test_collect_without_profile_has_role_and_system_but_no_person(make_run):
    html = rendered(make_run(profile=False))
    block = html[html.index('data-section="collect"'):]
    assert "Owner" in block and "System of record" in block
    assert "Sam Okafor" not in block and "your organisation" in html


def test_context_collect_next_matches_priority(make_run):
    run = make_run(profile=profile_with(*KNOWN))
    ctx = context.build_context(run / "v1")
    summary = json.loads((run / "v1" / "run_summary.json").read_text(encoding="utf-8"))
    want = [r["path"] for r in quality.improvement_priority(summary["parameters"])[:3]]
    assert [c["path"] for c in ctx["collect_next"]] == want
    assert all(c["owner_role"] and c["system"] for c in ctx["collect_next"])
    assert [c["person"] for c in ctx["collect_next"]] == OWNERS


def test_collect_routes_prefer_the_scenario_type(make_run):
    """The business-email-compromise sample routes to the systems a BEC loss is evidenced in."""
    ctx = context.build_context(make_run(profile=False) / "v1")
    assert [(c["path"], c["system"], c["owner_role"]) for c in ctx["collect_next"]] == [
        ("vulnerability.probability", "Phishing simulation platform", "Security awareness lead"),
        ("primary_loss.replacement", "Finance ERP / treasury", "Controller"),
        ("secondary_loss.slef", "Incident tracker", "Incident response lead"),
    ]


def test_formatting_helpers():
    assert formatting.fmt_money(2_090_000, "USD") == "$2.09M"
    assert formatting.fmt_money(729_400, "USD") == "$729k"
    assert formatting.fmt_money(120_000, "EUR") == "€120k"
    assert formatting.fmt_money(5_000, "CHF") == "CHF 5k"
    assert formatting.fmt_pct(0.032) == "3.2%" and formatting.fmt_pct(0.45) == "45%"
    assert formatting.fmt_pct(0.0004) == "<0.1%"
    assert formatting.fmt_rate(10.39) == "10.4×" and formatting.fmt_int(50000) == "50,000"


def test_charts_are_static_svg_with_titles(make_run):
    html = rendered(make_run())
    svgs = re.findall(r"<svg [^>]*role=\"img\".*?</svg>", html, flags=re.S)
    assert len(svgs) >= 4  # the curve plus one histogram per variant
    for chart in svgs:
        assert "<title" in chart and "<desc" in chart and "aria-labelledby" in chart
    assert len(re.findall(r"<script\b", html)) == 1  # the one inline script (slice 15); the charts need none
    assert 'data-points="' in html


# CLI and narrative hook -----------------------------------------------------------------------

def test_cli_report_ok_and_missing(make_run, capsys):
    run = make_run()
    capsys.readouterr()
    assert cli.main(["report", run.name, "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["version"] == 1 and data["narrative_omitted"] is False and data["path"].endswith("report.html")
    assert cli.main(["report", run.name, "--version", "7"]) == 5
    assert cli.main(["report", "no-such-run"]) == 5


def test_report_before_finalize_is_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    assert cli.main(["init"]) == 0
    run = tmp_path / ".riskquant" / "runs" / RUN_ID
    run.mkdir(parents=True)
    shutil.copy(SAMPLE / "scenario.yaml", run / "scenario.yaml")
    with pytest.raises(outcomes.NotFound) as exc:
        render.render_report(run)
    assert exc.value.issues == [{"path": "v1", "rule": "missing", "message": "v1 is missing; run `rqh finalize` first"}]


def test_narrative_is_stored_and_shown_until_omitted(make_run, tmp_path):
    run = make_run()
    note = tmp_path / "n.md"
    note.write_text("Plain words about the estimate.", encoding="utf-8")
    out = render.render_report(run, narrative=note)
    assert isinstance(out, render.Rendered)
    assert (run / "v1" / "narrative.md").read_text(encoding="utf-8") == "Plain words about the estimate."
    assert "Plain words about the estimate." in out.path.read_text(encoding="utf-8")
    again = render.render_report(run)
    assert "Plain words about the estimate." in again.path.read_text(encoding="utf-8")
    omitted = render.render_report(run, omit_narrative=True)
    assert "Plain words" not in omitted.path.read_text(encoding="utf-8")


def test_takeaway_and_drivers_headline_read_like_the_concept(make_run):
    ctx = context.build_context(make_run(profile=False) / "v1")
    takeaway = str(ctx["takeaway"])
    assert takeaway.startswith("This scenario costs an estimated $")
    assert ctx["title"] not in takeaway
    assert "; phishing-resistant MFA would cut that by " in takeaway
    assert re.fullmatch(r"Two inputs drive \d+% of the uncertainty: [a-z].+ and [a-z].+", ctx["heads"]["drivers"])


def test_lower_first_keeps_acronyms():
    assert formatting.lower_first("Phishing-resistant MFA") == "phishing-resistant MFA"
    assert formatting.lower_first("MFA + mail sandboxing") == "MFA + mail sandboxing"


# a hostile run_summary.json (F-B2) and a stored narrative that no longer validates (F-C5) -----

def _set_currency(run, currency: str) -> None:
    path = run / "v1" / "run_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary["currency"] = currency
    path.write_text(json.dumps(summary), encoding="utf-8")


def test_a_script_tag_currency_in_the_summary_is_refused_and_writes_nothing(make_run, tmp_path, capsys):
    run = make_run()
    _set_currency(run, HOSTILE)
    note = tmp_path / "n.md"
    note.write_text("Plain words about the estimate.", encoding="utf-8")
    for kwargs in ({}, {"omit_narrative": True}, {"narrative": note}):
        with pytest.raises(outcomes.Rejected) as exc:
            render.render_report(run, **kwargs)
        assert [i["path"] for i in exc.value.issues] == ["v1/run_summary.json.currency"]
        assert HOSTILE not in str(exc.value)
    assert not (run / "v1" / "report.html").exists() and not (run / "v1" / "narrative.md").exists()
    with pytest.raises(outcomes.Rejected):
        context.build_context(run / "v1")
    capsys.readouterr()
    assert cli.main(["report", run.name, "--json"]) == 1


@pytest.mark.parametrize("currency", ["usd", "US", "USDX", "", 840, None])
def test_currency_must_be_three_capitals(make_run, currency):
    run = make_run()
    _set_currency(run, currency)
    with pytest.raises(outcomes.Rejected):
        render.render_report(run)


def test_chart_ticks_escape_the_currency():
    points = [[10.0 ** (k / 4), 1 - k / 40] for k in range(40)]
    lec = svg.lec_chart([{"id": "baseline", "label": "Base", "points": points}], HOSTILE, 1e4)
    hist = svg.histogram_chart({"id": "baseline", "label": "Base", "edges": [i * 1e5 for i in range(7)],
                                "counts": [5, 4, 3, 2, 1, 1], "above": 0, "mean": 2e5, "p90": 4e5,
                                "median": 1.5e5}, HOSTILE, 16)
    for chart in (lec, hist):
        assert "<script" not in chart and "&lt;script&gt;" in chart


def test_a_stored_narrative_that_no_longer_validates_is_refused_not_dropped(make_run, tmp_path, capsys):
    run = make_run()
    note = tmp_path / "n.md"
    note.write_text("Plain words about the estimate.", encoding="utf-8")
    render.render_report(run, narrative=note)
    page = run / "v1" / "report.html"
    before = page.read_bytes()
    (run / "v1" / "narrative.md").write_text("Plain words.\nIt costs $5 million.\n", encoding="utf-8")
    with pytest.raises(outcomes.NarrativeRejected) as exc:
        render.render_report(run)
    assert [(i["path"], i["rule"]) for i in exc.value.issues] == [("narrative.line.2", "literal_figure")]
    assert "v1/narrative.md" in exc.value.issues[0]["message"]
    assert page.read_bytes() == before
    capsys.readouterr()
    assert cli.main(["report", run.name, "--json"]) == 4
    assert page.read_bytes() == before
    capsys.readouterr()
    assert cli.main(["report", run.name, "--omit-narrative", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["narrative_omitted"] is True and "Narrative omitted" in page.read_text(encoding="utf-8")
    assert render.render_report(run, narrative=note).narrative_omitted is False  # a valid --narrative replaces it
    assert "Plain words about the estimate." in page.read_text(encoding="utf-8")
