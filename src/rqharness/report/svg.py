"""Static inline SVG charts drawn as technical drawings: hairline axes, mono ticks, direct labels.

Pure functions from numbers to SVG strings. Every label passes through ``html.escape`` and every
coordinate is formatted deterministically, so equal inputs give equal bytes.
"""

from __future__ import annotations

import bisect
import html
import json
import math

from rqharness.report.formatting import fmt_int, fmt_money, fmt_pct

# Marker shapes per variant index; the CSS classes v0..v4 / m0..m4 / dl0..dl4 carry colour and dash.
_SHAPES = ("circle", "square", "triangle", "diamond", "cross")
_STYLES = len(_SHAPES)
_LABEL_TARGETS = (0.45, 0.21, 0.31, 0.12, 0.6)  # where along the curve each direct label sits
_NICE = (1.0, 2.0, 2.5, 5.0, 10.0)

# loss exceedance chart frame (viewBox 760 x 470)
_LW, _LH, _LML, _LPW, _LMT, _LPH = 760, 470, 58, 686, 14, 410
# histogram frame (viewBox 760 x 300)
_HW, _HH, _HML, _HPW, _HMT, _HPH = 760, 300, 62, 682, 30, 226


def _n(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def _nice_step(span: float, max_steps: int) -> float:
    """The smallest 1/2/2.5/5 x 10^k step that covers `span` in at most `max_steps` steps."""
    if span <= 0:
        return 1.0
    exponent = math.floor(math.log10(span / max_steps))
    for scale in (10.0**exponent, 10.0 ** (exponent + 1)):
        for base in _NICE:
            if span / (base * scale) <= max_steps + 1e-9:
                return base * scale
    return span  # pragma: no cover - unreachable: the next decade always fits


def exceedance(points: list[list[float]], x: float) -> float:
    """P(annual loss > x) interpolated linearly between the curve points; 0 past the last one."""
    if not points:
        return 0.0
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return 0.0
    i = bisect.bisect_right([p[0] for p in points], x)
    (x0, p0), (x1, p1) = points[i - 1], points[i]
    return p0 + (p1 - p0) * (x - x0) / (x1 - x0)


def _marker(index: int, cx: float, cy: float, extra: str = "") -> str:
    shape = _SHAPES[index % _STYLES]
    cls = f"mk m{index % _STYLES}{extra}"
    if shape == "circle":
        return f'<circle class="{cls}" cx="{_n(cx)}" cy="{_n(cy)}" r="4"/>'
    if shape == "square":
        return f'<rect class="{cls}" x="{_n(cx - 4)}" y="{_n(cy - 4)}" width="8" height="8"/>'
    if shape == "triangle":
        return f'<path class="{cls}" d="M{_n(cx)} {_n(cy - 5)}L{_n(cx + 5)} {_n(cy + 4)}L{_n(cx - 5)} {_n(cy + 4)}Z"/>'
    if shape == "diamond":
        return (f'<path class="{cls}" d="M{_n(cx)} {_n(cy - 5)}L{_n(cx + 5)} {_n(cy)}'
                f'L{_n(cx)} {_n(cy + 5)}L{_n(cx - 5)} {_n(cy)}Z"/>')
    return (f'<path class="{cls}" d="M{_n(cx - 2)} {_n(cy - 5)}H{_n(cx + 2)}V{_n(cy - 2)}H{_n(cx + 5)}V{_n(cy + 2)}'
            f'H{_n(cx + 2)}V{_n(cy + 5)}H{_n(cx - 2)}V{_n(cy + 2)}H{_n(cx - 5)}V{_n(cy - 2)}H{_n(cx - 2)}Z"/>')


def swatch(index: int) -> str:
    """The line-and-marker key used beside a variant name in tables."""
    i = index % _STYLES
    return (f'<svg class="sw" viewBox="0 0 30 12" aria-hidden="true"><line class="v{i}" x1="1" y1="6" x2="29" y2="6"/>'
            f'{_marker(index, 15, 6)}</svg>')


def _curve_point(points: list[list[float]], target: float) -> tuple[float, float]:
    """The first curve point whose exceedance has fallen to `target` (the last one if it never does)."""
    for x, p in points:
        if p <= target and x > 0:
            return x, p
    return points[-1][0], points[-1][1]


def lec_chart(variants: list[dict], currency: str, threshold: float | None = None) -> str:
    """All variants' loss exceedance curves overlaid on a log x axis.

    `variants`: dicts with `id`, `label` and `points` ([[loss, P(exceed)], ...]). `threshold`, when
    given, draws the static threshold marker. The curve points ride along as `data-points` JSON.
    """
    xs = [x for v in variants for x, _ in v["points"] if x > 0]
    lo_exp = math.floor(math.log10(min(xs))) if xs else 4
    hi_exp = max(math.ceil(math.log10(max(xs))) if xs else 6, lo_exp + 2)
    lo, span = 10.0**lo_exp, float(hi_exp - lo_exp)

    def px(x: float) -> float:
        return _LML + _LPW * (math.log10(max(x, lo)) - lo_exp) / span

    def py(p: float) -> float:
        return _LMT + _LPH * (1 - p)

    base = _LMT + _LPH
    right = _LML + _LPW
    out = []
    for p in (0, 0.25, 0.5, 0.75, 1):
        out.append(f'<line class="grid" x1="{_LML}" x2="{right}" y1="{_n(py(p))}" y2="{_n(py(p))}"/>'
                   f'<text class="tick" x="{_LML - 7}" y="{_n(py(p) + 4)}" text-anchor="end">{int(p * 100)}%</text>')
    for exp in range(lo_exp, hi_exp + 1):
        x = px(10.0**exp)
        out.append(f'<line class="grid maj" x1="{_n(x)}" x2="{_n(x)}" y1="{_LMT}" y2="{base}"/>'
                   f'<text class="tick" x="{_n(x)}" y="{base + 18}" text-anchor="middle">{_e(fmt_money(10.0**exp, currency, short=True))}</text>')
        if exp < hi_exp:
            for m in range(2, 10):
                mx = px(m * 10.0**exp)
                out.append(f'<line class="minor" x1="{_n(mx)}" x2="{_n(mx)}" y1="{base}" y2="{base + 4}"/>')
    out.append(f'<line class="axis" x1="{_LML}" x2="{_LML}" y1="{_LMT}" y2="{base}"/>'
               f'<line class="axis" x1="{_LML}" x2="{right}" y1="{base}" y2="{base}"/>'
               f'<text class="axt" x="{_n(_LML + _LPW / 2)}" y="{base + 40}" text-anchor="middle">'
               f'ANNUAL LOSS, {_e(currency)} (LOG SCALE)</text>'
               f'<text class="axt" transform="translate(13 {_n(_LMT + _LPH / 2)}) rotate(-90)" text-anchor="middle">'
               f'PROBABILITY OF EXCEEDING</text>'
               f'<line class="ref" x1="{_LML}" x2="{right}" y1="{_n(py(0.1))}" y2="{_n(py(0.1))}"/>'
               f'<text class="ann" x="{_LML + 6}" y="{_n(py(0.1) - 5)}">1 IN 10 YEARS</text>')
    labels = []
    for i, v in enumerate(variants):
        d = "".join(f"{'M' if k == 0 else 'L'}{_n(px(x))} {_n(py(p))}" for k, (x, p) in enumerate(v["points"]))
        out.append(f'<path class="curve v{i % _STYLES}" d="{d}"/>')
        first_p = v["points"][0][1] if v["points"] else 0.0
        mx, mp = _curve_point(v["points"], min(_LABEL_TARGETS[i % _STYLES], first_p * 0.9))
        cx, cy = px(mx), py(mp)
        text = _e(v["label"].upper()[:26])
        fits = cx + 10 + len(text) * 6.6 < right
        anchor = "" if fits else ' text-anchor="end"'
        labels.append(_marker(i, cx, cy)
                      + f'<text class="dl dl{i % _STYLES}" x="{_n(cx + 10 if fits else cx - 10)}" y="{_n(cy + 4)}"'
                        f'{anchor}>{text}</text>')
    out.extend(labels)
    chances = []
    if threshold is not None:
        tx = px(threshold)
        group = [f'<line class="thr" x1="{_n(tx)}" x2="{_n(tx)}" y1="{_LMT}" y2="{base}"/>'
                 f'<text class="thrt" id="lec-thr-l" x="{_n(tx + 5)}" y="{_LMT + 11}">THRESHOLD {_e(fmt_money(threshold, currency, short=True).upper())}</text>']
        for i, v in enumerate(variants):
            p = exceedance(v["points"], threshold)
            chances.append(f"{fmt_pct(p)} with {v['label']}")
            group.append(f'<circle class="tc tc{i % _STYLES}" id="tc{i}" cx="{_n(tx)}" cy="{_n(py(p))}" r="5.5"/>')
        out.append(f'<g id="lec-thr">{"".join(group)}</g>')
    out.append(f'<line id="lec-hv" class="hv" x1="0" x2="0" y1="{_LMT}" y2="{base}" visibility="hidden"/>'
               f'<rect id="lec-hit" x="{_LML}" y="{_LMT}" width="{_LPW}" height="{_LPH}" fill="transparent"/>')
    desc = (f"Probability that annual loss exceeds a given amount, log scale from {fmt_money(lo, currency)} "
            f"to {fmt_money(10.0**hi_exp, currency)}.")
    if threshold is not None:
        desc += f" At {fmt_money(threshold, currency)} the chance is {', '.join(chances)}."
    points = {v["id"]: [[round(x, 2), round(p, 5)] for x, p in v["points"]] for v in variants}
    return (f'<svg id="lec" class="chart" viewBox="0 0 {_LW} {_LH}" role="img" aria-labelledby="lec-t lec-d" '
            f'data-ml="{_LML}" data-pw="{_LPW}" data-mt="{_LMT}" data-ph="{_LPH}" data-xmin="{_n(lo)}" '
            f'data-xmax="{_n(10.0**hi_exp)}" data-currency="{_e(currency)}" '
            f'data-points="{_e(json.dumps(points, separators=(",", ":")))}">'
            f'<title id="lec-t">Loss exceedance curves for {len(variants)} control variant{"s" if len(variants) != 1 else ""}</title>'
            f'<desc id="lec-d">{_e(desc)}</desc>{"".join(out)}</svg>')


def histogram_chart(variant: dict, currency: str, n: int) -> str:
    """Histogram of one variant's annual loss with mean and p90 markers; the worst 10% of years in signal red.

    `variant`: `id`, `label`, `edges`, `counts`, `above`, `mean`, `median`, `p90`; `n` is the simulated years.
    """
    edges, counts = variant["edges"], variant["counts"]
    vid = _e(variant["id"])
    top_count = max(counts) if counts else 1
    step = _nice_step(top_count, 5)
    top = max(math.ceil(top_count / step), 1) * step
    base = _HMT + _HPH
    right = _HML + _HPW
    out = []
    for k in range(int(round(top / step)) + 1):
        y = base - _HPH * (k * step) / top
        out.append(f'<line class="grid" x1="{_HML}" x2="{right}" y1="{_n(y)}" y2="{_n(y)}"/>'
                   f'<text class="tick" x="{_HML - 7}" y="{_n(y + 4)}" text-anchor="end">{fmt_int(k * step)}</text>')
    nb = len(counts)
    slot = _HPW / nb
    for i, c in enumerate(counts):
        height = _HPH * c / top
        tail = " tail" if edges[i] >= variant["p90"] else ""
        out.append(f'<rect class="bar{tail}" x="{_n(_HML + i * slot + 0.5)}" y="{_n(base - height)}" '
                   f'width="{_n(slot * 0.915)}" height="{_n(height)}"><title>{_e(fmt_money(edges[i], currency))} to '
                   f'{_e(fmt_money(edges[i + 1], currency))}: {fmt_int(c)} simulated years</title></rect>')
    extent = edges[-1] or 1.0
    xstep = _nice_step(extent, 6)
    for k in range(int(extent // xstep) + 1):
        x = _HML + _HPW * (k * xstep) / extent
        out.append(f'<line class="axis" x1="{_n(x)}" x2="{_n(x)}" y1="{base}" y2="{base + 4}"/>'
                   f'<text class="tick" x="{_n(x)}" y="{base + 18}" text-anchor="middle">{_e(fmt_money(k * xstep, currency, short=True))}</text>')
    out.append(f'<line class="axis" x1="{_HML}" x2="{right}" y1="{base}" y2="{base}"/>'
               f'<line class="axis" x1="{_HML}" x2="{_HML}" y1="{_HMT}" y2="{base}"/>')
    mean_x = _HML + _HPW * min(variant["mean"] / extent, 1.0)
    p90_x = _HML + _HPW * min(variant["p90"] / extent, 1.0)
    p90_text = f"P90 {fmt_money(variant['p90'], currency)} (1 IN 10 YEARS)"
    flip = p90_x + 5 + len(p90_text) * 6.4 > _HW - 4
    anchor = ' text-anchor="end"' if flip else ""
    out.append(f'<line class="mk-mean" x1="{_n(mean_x)}" x2="{_n(mean_x)}" y1="16" y2="{base}"/>'
               f'<text class="ann b" x="{_n(mean_x - 5)}" y="24" text-anchor="end">MEAN {_e(fmt_money(variant["mean"], currency))}</text>'
               f'<line class="mk-p90" x1="{_n(p90_x)}" x2="{_n(p90_x)}" y1="16" y2="{base}"/>'
               f'<text class="ann b sig" x="{_n(p90_x - 5 if flip else p90_x + 5)}" y="{38 if flip else 24}"'
               f'{anchor}>{_e(p90_text)}</text>'
               f'<text class="axt" x="{_n(_HML + _HPW / 2)}" y="{_HH - 6}" text-anchor="middle">'
               f'ANNUAL LOSS, {_e(currency)} (BAND WIDTH {_e(fmt_money(edges[1] - edges[0], currency).upper())})</text>'
               f'<text class="axt" transform="translate(13 {_n(_HMT + _HPH / 2)}) rotate(-90)" text-anchor="middle">'
               f'SIMULATED YEARS PER BAND</text>')
    desc = (f"{variant['label']}: mean {fmt_money(variant['mean'], currency)}, 90th percentile "
            f"{fmt_money(variant['p90'], currency)}, median {fmt_money(variant['median'], currency)}. Bars show the "
            f"number of simulated years, out of {fmt_int(n)}, in each loss band.")
    if variant["above"]:
        desc += f" {fmt_int(variant['above'])} years above {fmt_money(extent, currency)} are not drawn."
    return (f'<svg class="chart hchart" viewBox="0 0 {_HW} {_HH}" role="img" aria-labelledby="h-{vid}-t h-{vid}-d">'
            f'<title id="h-{vid}-t">Histogram of annual loss, {_e(variant["label"])}</title>'
            f'<desc id="h-{vid}-d">{_e(desc)}</desc>{"".join(out)}</svg>')
