"""The narrative: placeholders resolved from the run summary, and the literal-figure rule.

A narrative may carry no figure of its own: every reader-facing number is a placeholder that rqh
resolves from `run_summary.json`. Prose that states a figure is rejected with its line and token.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from rqharness.outcomes import NarrativeRejected, issue
from rqharness.report.formatting import fmt_int, fmt_money, fmt_pct, fmt_rate, lower_first, pick_focus

_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}")
_FORMATS = ("money", "pct", "rate", "int")
_METRICS = ("annual_loss", "lef", "event_count", "annual_cost", "return_on_control")

# literal rule: a digit next to a currency, percent, magnitude, multiplier or ratio, or a spelled number
_NUM = r"\d+(?:[,.]\d+)*"
_ISO = r"(?:USD|EUR|GBP|JPY|CAD|AUD|CHF|CNY|INR|BRL|MXN|SEK|NOK|DKK|NZD|SGD|HKD)"
_MAGNITUDE = r"(?:k|m|bn|million|billion)(?![A-Za-z])"
_ONES = "two|three|four|five|six|seven|eight|nine"
_TEENS = "ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
_TENS = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
_SPELLED = rf"(?:(?:{_TENS})(?:[- ](?:one|{_ONES}))?|{_TEENS}|{_ONES})"
_WORD_NUM = rf"(?:{_SPELLED}|one)"
_LITERALS = [re.compile(p, re.IGNORECASE) for p in (
    rf"[$€£¥]\s?{_NUM}(?:\s?{_MAGNITUDE})?",
    rf"{_NUM}\s?[$€£¥]",
    rf"\b{_ISO}\s?{_NUM}(?:\s?{_MAGNITUDE})?",
    rf"{_NUM}\s?{_ISO}\b",
    rf"{_NUM}\s?%",
    rf"{_NUM}\s?(?:percent|per cent|dollars?|euros?|pounds?)\b",
    rf"{_NUM}\s?{_MAGNITUDE}",
    rf"{_NUM}[x×](?![A-Za-z])",
    rf"\b(?:{_NUM}|one)\s+in\s+(?:{_NUM}|{_WORD_NUM})\b",
    rf"\bevery\s+(?:{_NUM}|{_WORD_NUM})\s+(?:years?|months?|weeks?|days?|quarters?)\b",
    rf"\b{_SPELLED}\b",
    r"\b(?:hundred|thousand|million|billion)s?\b",
)]


@dataclass(frozen=True)
class Rejection:
    """Why a narrative breaks the literal rule; ``render_report`` raises it as ``outcomes.NarrativeRejected``."""

    line: int
    token: str
    reason: str

    def error(self, *, stored: str | None = None) -> NarrativeRejected:
        """The failure to raise; `stored` names the stored ``narrative.md`` the rejection came from."""
        message = f"{self.reason}: {self.token}"
        if stored:
            message += f" (in the stored {stored}; pass a new --narrative or --omit-narrative)"
        return NarrativeRejected([issue(f"narrative.line.{self.line}", self.reason, message)])


@dataclass(frozen=True)
class NarrativeResult:
    html: str | None
    rejected: Rejection | None


class _Unknown(Exception):
    pass


def _stat_value(summary: dict, variant: str, metric: str, stat: str) -> float:
    row = next((v for v in summary["variants"] if v["id"] == variant), None)
    if row is None:
        raise _Unknown
    if metric == "annual_cost":
        cost = row.get("annual_cost")
        if not cost or stat != "mean":
            raise _Unknown
        return cost["mean"]
    block = row.get(metric)
    if not isinstance(block, dict) or stat == "currency" or stat not in block:
        raise _Unknown
    return block[stat]


def _delta_value(summary: dict, variant: str, metric: str, stat: str) -> float:
    """Baseline minus variant; the summary's own delta row where it carries the figure."""
    row = next((d for d in summary.get("deltas", []) if d["variant"] == variant), None)
    if row is None:
        raise _Unknown
    if metric == "return_on_control":
        if stat != "mean" or row.get("return_on_control") is None:
            raise _Unknown
        return row["return_on_control"]
    if metric == "annual_loss" and stat in ("mean", "p90"):
        return row[f"ale_reduction_{stat}"]
    if metric == "annual_cost":
        raise _Unknown
    return _stat_value(summary, "baseline", metric, stat) - _stat_value(summary, variant, metric, stat)


def _default_format(metric: str) -> str:
    return "money" if metric in ("annual_loss", "annual_cost") else "rate" if metric == "return_on_control" else "dp2"


def _resolve(body: str, summary: dict, *, short: bool = False) -> str:
    """The text of one placeholder body (`mfa.annual_loss.mean|money`); raises _Unknown."""
    path, _, fmt = (part.strip() for part in body.partition("|"))
    parts = path.split(".")
    if parts == ["quality", "grade"] and not fmt:
        return summary["quality"]["grade"]
    delta = parts[:1] == ["delta"]
    if delta:
        parts = parts[1:]
    if len(parts) != 3 or parts[1] not in _METRICS or (fmt and fmt not in _FORMATS):
        raise _Unknown
    variant, metric, stat = parts
    value = _delta_value(summary, variant, metric, stat) if delta else _stat_value(summary, variant, metric, stat)
    fmt = fmt or _default_format(metric)
    currency = summary["currency"]
    if fmt == "money":
        return fmt_money(value, currency, short=short)
    if fmt == "pct":
        if delta:  # the reduction relative to the baseline's same statistic
            base = _stat_value(summary, "baseline", metric, stat)
            value = value / base if base else 0.0
        return fmt_pct(value)
    if fmt == "rate":
        return fmt_rate(value)
    return fmt_int(value) if fmt == "int" else f"{value:.2f}"


def _literal(line: str) -> str | None:
    """The leftmost, then longest, figure the prose states; None for clean prose."""
    found = [m for pattern in _LITERALS if (m := pattern.search(line))]
    return min(found, key=lambda m: (m.start(), -len(m.group(0)))).group(0) if found else None


def _reject(line: int, token: str, reason: str) -> NarrativeResult:
    return NarrativeResult(None, Rejection(line, token, reason))


def render_narrative(text: str, summary: dict) -> NarrativeResult:
    """Resolve placeholders and apply the literal rule; the HTML is escaped paragraphs of prose."""
    paragraphs: list[list[str]] = [[]]
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            if paragraphs[-1]:
                paragraphs.append([])
            continue
        pieces: list[str] = []
        prose: list[str] = []
        last = 0
        for m in _PLACEHOLDER.finditer(line):
            try:
                figure = _resolve(m.group(1), summary)
            except _Unknown:
                return _reject(number, m.group(0), "unknown_placeholder")
            prose.append(line[last:m.start()])
            pieces.append(html.escape(line[last:m.start()]) + f'<span class="num">{html.escape(figure)}</span>')
            last = m.end()
        prose.append(line[last:])
        pieces.append(html.escape(line[last:]))
        outside = "\x00".join(prose)  # a placeholder never glues digits to the prose around it
        stray = re.search(r"\{\{|\}\}", outside)
        if stray:
            return _reject(number, stray.group(0), "unknown_placeholder")
        token = _literal(outside)
        if token is not None:
            return _reject(number, token, "literal_figure")
        paragraphs[-1].append("".join(pieces).strip())
    return NarrativeResult("".join(f"<p>{' '.join(p)}</p>" for p in paragraphs if p), None)


def fixed_takeaway(summary: dict, scenario: dict) -> str:
    """The one-sentence takeaway used when no narrative is stored, as escaped HTML."""
    def figure(body: str) -> str:
        return html.escape(_resolve(body, summary, short=True))

    head = f"This scenario costs an estimated {figure('baseline.annual_loss.mean')} a year"
    delta = pick_focus(summary)
    if delta is None:
        return f"{head}. One year in ten costs {figure('baseline.annual_loss.p90')} or more."
    variant = next(v for v in summary["variants"] if v["id"] == delta["variant"])
    vid = variant["id"]
    sentence = (f"{head}; {html.escape(lower_first(variant['label']))} would cut that by "
                f"{figure('delta.' + vid + '.annual_loss.mean|pct')}")
    if variant.get("annual_cost"):
        sentence += f" for {figure(vid + '.annual_cost.mean|money')} a year"
    return sentence + "."
