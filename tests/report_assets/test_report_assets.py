"""AC24 (static SVG, inline script with its hooks) and AC25 (theme = custom properties + logo, dark mode)."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import subprocess
from html import unescape
from importlib import resources

import pytest

from rqharness import orgprofile
from rqharness.report import formatting, theme


def _css(snapshot: dict) -> str:
    """The theme CSS of the profile a theme snapshot froze."""
    return theme.theme_css(orgprofile.from_snapshot(snapshot))


def _logo(snapshot: dict) -> str:
    return theme.logo_html(orgprofile.from_snapshot(snapshot))


PNG_URI = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
THEMED = f'theme:\n  accent: "#1F6FEB"\n  display_name: Northwind Analytics\n  logo_data_uri: "{PNG_URI}"\n'
PLAIN = "theme:\n  display_name: Northwind Analytics\n"
SCRIPT = re.compile(r"<script\b[^>]*>.*?</script>", re.S)
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")  # generated_at differs between two renders
JS_PATH =resources.files("rqharness.report") / "assets" / "report.js"


@pytest.fixture
def themed(render_with) -> str:
    return render_with(THEMED)


# --- AC24 --------------------------------------------------------------------------------------

def test_static_svg_without_script(render_with):
    page = SCRIPT.sub("", render_with(PLAIN))
    assert "<script" not in page
    lec = re.search(r'<svg id="lec".*?</svg>', page, re.S).group(0)
    assert lec.count('<path class="curve') == 3 and "data-points=" in lec
    hists = re.findall(r'<div class="hist[^"]*" id="hist-[^"]+" data-variant="[^"]+">(.*?)</div>', page, re.S)
    assert len(hists) == 3 and all("<svg" in h and 'class="bar' in h for h in hists)
    assert page.count("class=\"hist is-hidden\"") == 2  # only the baseline histogram is drawn without scripting
    appendix = page[page.index('data-section="appendix"'):]
    assert appendix.count('<th scope="col" class="num">') == 3  # every variant tabulated
    assert '<div class="thr-form"' not in page and "html:not(.js)" in page  # script-only controls hide themselves


def test_script_inlined_with_threshold_hooks(render_with):
    page = render_with(PLAIN)
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", page, re.S)
    assert len(scripts) == 1 and "src" not in scripts[0][0]
    body = scripts[0][1]
    assert body.strip() == JS_PATH.read_text(encoding="utf-8").strip()
    for hook in ("thr-in", "data-points", "hv-toggle", "lec-hit", "lec-cursor", "thr-lbl"):
        assert hook in body
        assert f'id="{hook}"' in page or f'{hook}=' in page
    assert re.search(r'<svg id="lec"[^>]*data-points="', page)
    digest = base64.b64encode(hashlib.sha256(body.encode("utf-8")).digest()).decode("ascii")
    assert (f'content="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; '
            f'script-src \'sha256-{digest}\'; base-uri \'none\'; form-action \'none\'"') in page
    for forbidden in ("eval(", "fetch(", "XMLHttpRequest", "localStorage", "sessionStorage", "new Function"):
        assert forbidden not in body


def test_threshold_form_needs_no_inline_handler(render_with):
    """A hashed script-src blocks inline handlers, so report.js itself keeps the form from submitting."""
    page = render_with(PLAIN)
    assert '<form class="thr-form">' in page and "onsubmit" not in page
    js = JS_PATH.read_text(encoding="utf-8")
    assert 'input.form.addEventListener("submit", function (e) { e.preventDefault(); });' in js


def test_script_adds_js_class_and_the_toggle_swaps_variants_in_markup(render_with):
    page = render_with(PLAIN)
    assert 'id="hv-toggle"' in page and len(re.findall(r'name="hv"', page)) == 3
    assert 'classList.add("js")' in JS_PATH.read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_script_formatting_and_interpolation_match_python(tmp_path):
    cases_money = [(0, "USD"), (850, "USD"), (999.5, "USD"), (2500, "USD"), (729_400, "USD"), (999_500, "USD"),
                   (1_250_000, "USD"), (1_500_000, "USD"), (2_090_000, "EUR"), (3.2e9, "GBP"), (-4200, "USD"),
                   (750_000, "CAD")]
    cases_pct = [0, 0.0004, 0.0005, 0.0123, 0.0995, 0.1005, 0.25, 0.555, 1.0]
    points = [[10_000.0, 0.9], [100_000.0, 0.4], [1_000_000.0, 0.05], [5_000_000.0, 0.001]]
    xs = [0, 10_000.0, 55_000.0, 750_000.0, 4_000_000.0, 5_000_000.0, 9e9]
    script = (f"const r=require({json.dumps(str(JS_PATH))});const out={{money:[],short:[],pct:[],exc:[],parse:[]}};"
              f"for(const [v,c] of {json.dumps(cases_money)}){{out.money.push(r.fmtMoney(v,c,false));out.short.push(r.fmtMoney(v,c,true));}}"
              f"for(const p of {json.dumps(cases_pct)})out.pct.push(r.fmtPct(p));"
              f"for(const x of {json.dumps(xs)})out.exc.push(r.exceedance({json.dumps(points)},x));"
              f"for(const t of ['750k','1.5M','2000000','$1M',' 1,500,000 ','abc','','-5','1.5.2'])out.parse.push(r.parseAmount(t));"
              f"console.log(JSON.stringify(out));")
    got = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert got["money"] == [formatting.fmt_money(v, c) for v, c in cases_money]
    assert got["short"] == [formatting.fmt_money(v, c, short=True) for v, c in cases_money]
    assert got["pct"] == [formatting.fmt_pct(p) for p in cases_pct]
    from rqharness.report import svg
    assert got["exc"] == pytest.approx([svg.exceedance(points, x) for x in xs])
    assert got["parse"] == [750_000, 1_500_000, 2_000_000, 1_000_000, 1_500_000, None, None, None, None]


# --- AC25 --------------------------------------------------------------------------------------

def test_theme_changes_only_custom_properties(render_with):
    plain = render_with(PLAIN)
    themed_page = render_with(THEMED)
    css = _css({"theme": {"accent": "#1F6FEB"}})
    logo = _logo({"theme": {"logo_data_uri": PNG_URI, "display_name": "Northwind Analytics"}})
    assert css in themed_page and logo in themed_page and "--sig:#1F6FEB" in themed_page
    assert css not in plain and "<img" not in plain
    assert re.fullmatch(r"(:root\{(--[a-z0-9-]+:#[0-9A-F]{6};?)+\}\s*|@media \(prefers-color-scheme:dark\)\{:root\{(--[a-z0-9-]+:#[0-9A-F]{6};?)+\}\})+",
                        css.replace("\n", ""))
    assert STAMP.sub("T", themed_page.replace(css, "").replace(logo, "")) == STAMP.sub("T", plain)


def test_display_name_changes_only_the_org_text(render_with):
    named = render_with("theme:\n  display_name: Contoso Labs\n")
    plain = render_with(PLAIN)
    assert "Contoso Labs" in named
    assert STAMP.sub("T", named.replace("Contoso Labs", "Northwind Analytics")) == STAMP.sub("T", plain)


def test_dark_mode_media_query(themed):
    base = resources.files("rqharness.report").joinpath("assets/report.css").read_text(encoding="utf-8")
    dark = re.search(r"@media \(prefers-color-scheme:dark\)\{\s*:root\{([^}]*)\}", base).group(1)
    assert "--bg:" in dark and "--ink:" in dark
    assert re.search(r"@media \(prefers-color-scheme:dark\)\{:root\{--sigtxt:#[0-9A-F]{6};--v1:#[0-9A-F]{6}\}\}", themed)
    assert themed.count("prefers-color-scheme:dark") >= 2  # the base palette and the themed accent


@pytest.mark.parametrize("accent", ["red;}body{display:none", "#12345", "#GGGGGG", "url(x)", "#1F6FEB;}", 123, None])
def test_hostile_accent_is_never_emitted(accent):
    assert _css({"theme": {"accent": accent}}) == ""


@pytest.mark.parametrize("uri", ["javascript:alert(1)", "data:text/html;base64,PHNjcmlwdD4=",
                                 'data:image/png;base64,AAAA" onerror="x', "data:image/png;base64,AAAA\n<script>",
                                 "https://example.com/x.png", None])
def test_hostile_logo_is_never_emitted(uri):
    assert _logo({"theme": {"logo_data_uri": uri}}) == ""


def test_logo_alt_text_is_escaped():
    html = _logo({"theme": {"logo_data_uri": PNG_URI, "display_name": 'A"><script>'}})
    assert html.startswith('<img class="logo" alt="A&quot;&gt;&lt;script&gt; logo" src="data:image/png;base64,')
    assert "<script" not in html


def test_no_theme_means_no_css_and_no_logo():
    assert _css({}) == "" and _logo({}) == ""
    assert _css({"theme": None}) == "" and _logo({"theme": {}}) == ""


def test_narrative_omitted_note(render_with):
    assert "Narrative omitted" in unescape(render_with(PLAIN, omit=True))
    assert "Narrative omitted" not in render_with(PLAIN)


def test_accent_also_recolours_the_first_variant_curve():
    """report.css draws the first non-baseline variant in the signal colour (--v1), in both schemes."""
    css = _css({"theme": {"accent": "#1f6feb"}})
    light, dark = css.split("@media")
    assert "--sig:#1F6FEB" in light and "--v1:#1F6FEB" in light
    assert "--v1:#1F6FEB" in dark  # the dark palette's --v1 would otherwise stay red


def test_chart_captions_name_no_colour(render_with):
    page = render_with(None)
    assert "Red bars" not in page and "Highlighted bars: worst 10% of years" in page
