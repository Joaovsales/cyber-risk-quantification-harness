"""AC23: narrative placeholders resolve from the summary; figures typed into prose are rejected."""

from __future__ import annotations

import hashlib
import json

import pytest

from rqharness import cli
from rqharness.report.formatting import fmt_int, fmt_money, fmt_pct, fmt_rate
from rqharness.report.narrative import fixed_takeaway, render_narrative

SUMMARY = {
    "currency": "USD",
    "quality": {"grade": "B", "score": 0.65},
    "variants": [
        {"id": "baseline", "label": "Current controls", "annual_cost": None,
         "annual_loss": {"currency": "USD", "mean": 2_090_000.0, "median": 900_000.0, "p10": 5_000.0, "p25": 100_000.0,
                         "p75": 2_000_000.0, "p90": 4_800_000.0, "p95": 7_000_000.0, "p99": 12_000_000.0},
         "lef": {"mean": 1.5, "median": 1.0, "p90": 3.0}, "event_count": {"mean": 1.6, "median": 1.0, "p90": 3.0}},
        {"id": "mfa-sandbox", "label": "MFA + mail sandboxing", "annual_cost": {"currency": "USD", "mean": 120_000.0},
         "annual_loss": {"currency": "USD", "mean": 730_000.0, "median": 300_000.0, "p10": 1_000.0, "p25": 40_000.0,
                         "p75": 700_000.0, "p90": 2_500_000.0, "p95": 3_000_000.0, "p99": 6_000_000.0},
         "lef": {"mean": 0.5, "median": 0.25, "p90": 1.5}, "event_count": {"mean": 0.6, "median": 0.0, "p90": 1.0}},
    ],
    "deltas": [{"variant": "mfa-sandbox", "currency": "USD", "ale_reduction_mean": 1_360_000.0,
                "ale_reduction_p90": 2_300_000.0, "return_on_control": 11.3}],
}


def figure(body: str) -> str:
    result = render_narrative("{{ " + body + " }}", SUMMARY)
    assert result.rejected is None, result.rejected
    return result.html.removeprefix('<p><span class="num">').removesuffix("</span></p>")


@pytest.mark.parametrize("body,expected", [
    ("baseline.annual_loss.mean", fmt_money(2_090_000, "USD")),
    ("baseline.annual_loss.p99", fmt_money(12_000_000, "USD")),
    ("mfa-sandbox.annual_loss.p10", fmt_money(1_000, "USD")),
    ("baseline.lef.mean", "1.50"),
    ("baseline.lef.p90", "3.00"),
    ("mfa-sandbox.event_count.median", "0.00"),
    ("mfa-sandbox.annual_cost.mean", fmt_money(120_000, "USD")),
    ("delta.mfa-sandbox.annual_loss.mean", fmt_money(1_360_000, "USD")),
    ("delta.mfa-sandbox.annual_loss.p90", fmt_money(2_300_000, "USD")),
    ("delta.mfa-sandbox.annual_loss.median", fmt_money(600_000, "USD")),
    ("delta.mfa-sandbox.lef.mean", "1.00"),
    ("delta.mfa-sandbox.event_count.p90", "2.00"),
    ("delta.mfa-sandbox.return_on_control.mean", fmt_rate(11.3)),
    ("quality.grade", "B"),
])
def test_placeholders_resolve(body, expected):
    assert figure(body) == expected


@pytest.mark.parametrize("body,expected", [
    ("baseline.annual_loss.mean|int", fmt_int(2_090_000)),
    ("baseline.lef.mean|money", fmt_money(1.5, "USD")),
    ("baseline.lef.mean|rate", fmt_rate(1.5)),
    ("baseline.lef.mean|pct", fmt_pct(1.5)),
    ("delta.mfa-sandbox.annual_loss.mean|pct", fmt_pct(1_360_000 / 2_090_000)),
    ("baseline.annual_loss.mean | money", fmt_money(2_090_000, "USD")),
])
def test_formats(body, expected):
    assert figure(body) == expected


def test_prose_is_escaped_and_figures_wrapped():
    out = render_narrative("Loss is {{baseline.annual_loss.mean}} <script>x</script>.\n\nSecond one.", SUMMARY)
    assert out.html == (f'<p>Loss is <span class="num">{fmt_money(2_090_000, "USD")}</span> '
                        '&lt;script&gt;x&lt;/script&gt;.</p><p>Second one.</p>')


@pytest.mark.parametrize("body", [
    "nope.annual_loss.mean", "baseline.revenue.mean", "baseline.annual_loss.p50",
    "baseline.annual_loss.mean|euro", "delta.baseline.annual_loss.mean", "quality.score",
])
def test_unknown_placeholder_exit_4(body):
    out = render_narrative("Fine line.\nValue {{" + body + "}} here.", SUMMARY)
    assert out.html is None
    assert (out.rejected.line, out.rejected.token, out.rejected.reason) == (2, "{{" + body + "}}", "unknown_placeholder")


def test_unclosed_placeholder_rejected():
    assert render_narrative("Value {{ baseline.annual_loss.mean", SUMMARY).rejected.reason == "unknown_placeholder"


@pytest.mark.parametrize("prose,token", [
    ("It costs $2M a year", "$2M"),
    ("It costs $2.5 million", "$2.5 million"),
    ("About 2 million at stake", "2 million"),
    ("A 40% chance", "40%"),
    ("A 40 percent chance", "40 percent"),
    ("A 40 per cent chance", "40 per cent"),
    ("Cost rises 3x overall", "3x"),
    ("Cost rises 3× overall", "3×"),
    ("A 1 in 20 event", "1 in 20"),
    ("It is one in ten", "one in ten"),
    ("Happens every 5 years", "every 5 years"),
    ("Happens every five years", "every five years"),
    ("We saw two hundred cases", "two"),
    ("Roughly twenty-five cases", "twenty-five"),
    ("Thousands of cases", "Thousands"),
    ("Budget USD 5 only", "USD 5"),
    ("Budget 5 EUR only", "5 EUR"),
    ("Budget 5k only", "5k"),
    ("Budget 5 bn only", "5 bn"),
    ("Pay 300 dollars", "300 dollars"),
    ("Pay €300 now", "€300"),
])
def test_literal_figure_exit_4_names_line(prose, token):
    out = render_narrative(f"Clean opening line.\n\n{prose}.", SUMMARY)
    assert out.html is None
    assert (out.rejected.line, out.rejected.token, out.rejected.reason) == (3, token, "literal_figure")


@pytest.mark.parametrize("prose", [
    "In 2025 the top 3 inputs drive the result.",
    "One of the inputs matters most, and one can see why.",
    "Version 2.1 of the model, section 4, page 12.",
    "The 90th percentile is shown; {{baseline.annual_loss.p90}} sits there.",
    "Cost {{baseline.annual_loss.mean}}k is not glued: {{baseline.lef.mean}}x.",
    "Often we see skim, kmart and mx only as words.",
])
def test_plain_digits_pass(prose):
    out = render_narrative(prose, SUMMARY)
    assert out.rejected is None and out.html.startswith("<p>")


def test_fixed_takeaway_shape():
    assert fixed_takeaway(SUMMARY, {}) == (
        "This scenario costs an estimated $2.1M a year; MFA + mail sandboxing would cut that by 65% for $120k a year.")
    assert fixed_takeaway({**SUMMARY, "deltas": []}, {}).startswith("This scenario costs an estimated $2.1M a year. ")


def test_fixed_takeaway_escapes_its_figures():
    """The fixed sentence is shown as markup, so a figure carrying markup must reach it escaped (F-B2)."""
    hostile = json.loads(json.dumps(SUMMARY).replace('"USD"', '"<b>X</b>"'))
    for summary in (hostile, {**hostile, "deltas": []}):
        sentence = fixed_takeaway(summary, {})
        assert "<b>" not in sentence and "&lt;b&gt;X&lt;/b&gt;" in sentence


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_rejects_bad_narrative_and_writes_nothing(make_run, tmp_path, capsys):
    run = make_run()
    assert cli.main(["report", run.name]) == 0
    html_before = _sha(run / "v1" / "report.html")
    bad = tmp_path / "bad.md"
    bad.write_text("Opening line.\nThis costs $2M a year.\n", encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["report", run.name, "--narrative", str(bad), "--json"]) == 4
    payload = capsys.readouterr().out
    assert "narrative.line.2" in payload and "$2M" in payload and "literal_figure" in payload
    assert not (run / "v1" / "narrative.md").exists()
    assert _sha(run / "v1" / "report.html") == html_before


def test_cli_good_narrative_is_stored_and_shown(make_run, tmp_path):
    run = make_run()
    summary = json.loads((run / "v1" / "run_summary.json").read_text(encoding="utf-8"))
    mean = fmt_money(summary["variants"][0]["annual_loss"]["mean"], summary["currency"])
    good = tmp_path / "good.md"
    good.write_text("Expected yearly loss is {{ baseline.annual_loss.mean }}, graded {{ quality.grade }}.\n", encoding="utf-8")
    assert cli.main(["report", run.name, "--narrative", str(good)]) == 0
    assert (run / "v1" / "narrative.md").read_text(encoding="utf-8") == good.read_text(encoding="utf-8")
    assert mean in (run / "v1" / "report.html").read_text(encoding="utf-8")


def test_cli_omit_narrative_uses_fixed_takeaway(make_run, capsys):
    run = make_run()
    capsys.readouterr()
    assert cli.main(["report", run.name, "--omit-narrative", "--json"]) == 0
    assert '"narrative_omitted": true' in capsys.readouterr().out.replace('":true', '": true')
    assert "This scenario costs an estimated" in (run / "v1" / "report.html").read_text(encoding="utf-8")
