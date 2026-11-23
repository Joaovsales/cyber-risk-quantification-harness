"""Fixtures for the report's script and theme: finalized sample runs rendered with and without a themed profile."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rqharness import cli
from rqharness.report import render

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "tests" / "validate" / "fixtures" / "sample-run"
PROFILE = REPO / "tests" / "routing" / "fixtures" / "org-profile.yaml"
RUN_ID = "credential-phishing-bec"


def profile_text(*, theme: str | None) -> str:
    """The routing fixture profile with its `theme:` block replaced by `theme` (a YAML mapping body, or none)."""
    text = PROFILE.read_text(encoding="utf-8")
    text = re.sub(r"(?ms)^theme:.*?(?=^\S|\Z)", "", text)
    return text.rstrip("\n") + ("\n" + theme if theme else "") + "\n"


def _render(root: Path, monkeypatch, *, profile: str, n: int = 3000, omit: bool = False) -> str:
    monkeypatch.chdir(root)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    assert cli.main(["init"]) == 0
    ws = root / ".riskquant"
    (ws / "org-profile.yaml").write_text(profile, encoding="utf-8")
    run = ws / "runs" / RUN_ID
    run.mkdir(parents=True)
    for name in ("scenario.yaml", "inputs.yaml"):
        (run / name).write_text((SAMPLE / name).read_text(encoding="utf-8"), encoding="utf-8")
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo", "--n", str(n), "--seed", "20261109"]) == 0
    assert cli.main(["finalize", RUN_ID]) == 0
    out = render.render_report(run, omit_narrative=omit)
    return out.path.read_text(encoding="utf-8")


@pytest.fixture
def render_with(tmp_path, monkeypatch):
    """Factory: render the sample under a profile built from `theme` (YAML text) in a fresh workspace."""
    count = iter(range(100))

    def build(theme: str | None, **kw) -> str:
        root = tmp_path / f"ws{next(count)}"
        root.mkdir()
        return _render(root, monkeypatch, profile=profile_text(theme=theme), **kw)

    return build
