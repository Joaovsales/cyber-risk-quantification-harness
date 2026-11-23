"""Reader-facing figures: how the report, its charts and the narrative placeholders print numbers.

Also picks the variants a sentence talks about, since the headlines, the fixed takeaway and the
narrative must agree on them. ``assets/report.js`` mirrors ``fmt_money`` and ``fmt_pct`` for the
editable figures; ``tests/report_assets`` holds the two to the same output.
"""

from __future__ import annotations

_CURRENCY_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}


def _prefix(currency: str) -> str:
    return _CURRENCY_SYMBOLS.get(currency) or f"{currency} "


def lower_first(label: str) -> str:
    """Lower-case a label's first letter for use mid-sentence, leaving acronyms ("MFA ...") alone."""
    if len(label) > 1 and label[0].isupper() and label[1].islower():
        return label[0].lower() + label[1:]
    return label


def fmt_money(value: float, currency: str, *, short: bool = False) -> str:
    """`$2.09M`, `$729k`, `$850`; `short` keeps one decimal in millions (`$2.1M`)."""
    sign = "−" if value < 0 else ""
    a, p = abs(value), _prefix(currency)
    if a >= 1e9:
        num, unit = a / 1e9, "B"
    elif round(a / 1e3) >= 1000:
        num, unit = a / 1e6, "M"
    elif round(a) >= 1000:
        return f"{sign}{p}{round(a / 1e3)}k"
    else:
        return f"{sign}{p}{round(a)}"
    text = f"{num:.1f}".removesuffix(".0") if short else f"{num:.2f}"
    return f"{sign}{p}{text}{unit}"


def fmt_pct(p: float) -> str:
    """Whole percentages, one decimal below 10%, `<0.1%` for the tiny ones."""
    a = abs(p) * 100
    if a == 0:
        return "0%"
    if a < 0.05:
        return "<0.1%"
    return f"{a:.1f}%" if round(a, 1) < 10 else f"{round(a)}%"


def fmt_rate(x: float) -> str:
    """Return on control, `10.3×`."""
    return f"{'−' if x < 0 else ''}{abs(x):.1f}×"


def fmt_int(x: float) -> str:
    return f"{round(x):,}"


def pick_focus(summary: dict) -> dict | None:
    """The delta the story centres on: best return on control, else the largest cut; None without variants."""
    deltas = summary.get("deltas", [])
    returns = [d for d in deltas if d.get("return_on_control") is not None]
    if returns:
        return max(returns, key=lambda d: d["return_on_control"])
    return largest_cut(summary)


def largest_cut(summary: dict) -> dict | None:
    """The delta with the largest cut in mean annual loss; None without variants."""
    return max(summary.get("deltas", []), key=lambda d: d["ale_reduction_mean"], default=None)
