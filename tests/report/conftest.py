"""Fixtures for the report renderer: a finalized sample run built through the real CLI."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from rqharness import cli

REPO = Path(__file__).resolve().parents[2]
SAMPLE = REPO / "tests" / "validate" / "fixtures" / "sample-run"
PROFILE = REPO / "tests" / "routing" / "fixtures" / "org-profile.yaml"
RUN_ID = "credential-phishing-bec"


def build_run(root: Path, *, route: str, n: int, profile: bool | str, edit=None) -> Path:
    """Init a workspace in `root`, confirm and finalize the sample run through the CLI."""
    assert cli.main(["init"]) == 0
    ws = root / ".riskquant"
    if profile:
        (ws / "org-profile.yaml").write_text(profile if isinstance(profile, str) else PROFILE.read_text(encoding="utf-8"), encoding="utf-8")
    run = ws / "runs" / RUN_ID
    run.mkdir(parents=True)
    for name in ("scenario.yaml", "inputs.yaml"):
        text = (SAMPLE / name).read_text(encoding="utf-8")
        if edit:
            text = edit(name, text)
        (run / name).write_text(text, encoding="utf-8")
    assert cli.main(["run", "confirm", RUN_ID, "--route", route, "--n", str(n), "--seed", "20261109"]) == 0
    assert cli.main(["finalize", RUN_ID]) == 0
    return run


@pytest.fixture
def make_run(tmp_path, monkeypatch):
    """Factory: returns the run dir of a finalized (v1) sample run."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)

    def build(*, route: str = "yolo", n: int = 3000, profile: bool | str = True, edit=None) -> Path:
        return build_run(tmp_path, route=route, n=n, profile=profile, edit=edit)

    return build


@pytest.fixture(scope="session")
def full_html(tmp_path_factory) -> str:
    """The sample rendered at n = 50,000 (one build for the size test)."""
    from rqharness.report import render

    root = tmp_path_factory.mktemp("full")
    cwd = os.getcwd()
    os.chdir(root)
    try:
        run = build_run(root, route="yolo", n=50000, profile=True)
        out = render.render_report(run)
        return out.path.read_text(encoding="utf-8")
    finally:
        os.chdir(cwd)
