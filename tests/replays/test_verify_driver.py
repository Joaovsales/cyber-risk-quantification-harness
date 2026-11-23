"""The verify-rqh driver: its report checks catch a broken report, and a browser fault keeps the evidence."""

from __future__ import annotations

import json
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest
from replay_driver import ROOT, load_verify

verify = load_verify()
PROFILE = ROOT / "tests" / "routing" / "fixtures" / "org-profile.yaml"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> dict[str, Path]:
    """The sample run rendered twice by `rqh`: without and with the fixture org profile."""
    reports = {}
    for name, profile in (("plain", None), ("profile", PROFILE)):
        ws = tmp_path_factory.mktemp(name)
        assert verify.rqh(["init"], ws)["exit"] == 0
        if profile:
            shutil.copy2(profile, ws / ".riskquant" / "org-profile.yaml")
        shutil.copytree(verify.SAMPLE, ws / ".riskquant" / "runs" / verify.RUN_ID)
        for argv in (["run", "confirm", verify.RUN_ID, "--route", "yolo", "--n", "2000", "--seed", "7"],
                     ["finalize", verify.RUN_ID], ["report", verify.RUN_ID]):
            assert verify.rqh(argv, ws)["exit"] == 0, argv
        reports[name] = ws / ".riskquant" / "runs" / verify.RUN_ID / "v1" / "report.html"
    return reports


def _checks(path: Path, **expect) -> dict[str, dict]:
    return {c["check"]: c for c in verify.check_report(path, "yolo", **expect)}


def _edited(tmp_path: Path, source: Path, old: str, new: str, count: int = 1) -> Path:
    text = source.read_text(encoding="utf-8")
    assert old in text, old
    target = tmp_path / "report.html"
    target.write_text(text.replace(old, new, count), encoding="utf-8")
    return target


def test_the_sample_report_passes_every_check_with_the_sample_counts(rendered):
    checks = _checks(rendered["plain"], charts=verify.SAMPLE_CHARTS, requests=verify.SAMPLE_REQUESTS)
    assert {"static_charts_present", "section_numbers", "title_suffix", "collect_requests"} <= set(checks)
    assert all(c["pass"] for c in checks.values()), [c for c in checks.values() if not c["pass"]]
    assert checks["static_charts_present"]["detail"] == {"svg_img": 4, "histograms": 3}


def test_a_lost_histogram_chart_fails_the_chart_check(rendered, tmp_path):
    # the old `>= 2` passed a report that had lost one of its three histograms
    broken = _edited(tmp_path, rendered["plain"], 'id="hist-mfa" data-variant="mfa"><svg', 'id="hist-mfa" data-variant="mfa"><div')
    assert not _checks(broken)["static_charts_present"]["pass"]


def test_a_chart_count_other_than_the_samples_fails(rendered):
    assert not _checks(rendered["plain"], charts=5)["static_charts_present"]["pass"]


def test_section_numbers_must_run_01_to_09(rendered, tmp_path):
    broken = _edited(tmp_path, rendered["plain"], 'aria-hidden="true">07<', 'aria-hidden="true">7<')
    check = _checks(broken)["section_numbers"]
    assert not check["pass"] and "7" in check["detail"]


def test_the_page_title_needs_the_risk_report_suffix(rendered, tmp_path):
    broken = _edited(tmp_path, rendered["plain"], " / risk report</title>", "</title>")
    check = _checks(broken)["title_suffix"]
    assert not check["pass"] and check["detail"].startswith("Credential phishing")


def test_the_collect_section_needs_the_samples_three_requests_each_with_owner_and_system(rendered, tmp_path):
    text = rendered["plain"].read_text(encoding="utf-8")
    first = text.index('<li class="ck"')
    dropped = tmp_path / "dropped.html"
    dropped.write_text(text[:first] + text[text.index("</li>", first) + len("</li>"):], encoding="utf-8")
    assert not _checks(dropped, requests=3)["collect_requests"]["pass"]
    no_owner = _edited(tmp_path, rendered["plain"], "<dt>Owner</dt>", "<dt>Team</dt>")
    assert not _checks(no_owner)["collect_requests"]["pass"]


def test_the_profile_check_finds_the_profiles_display_name(rendered, tmp_path):
    assert verify.check_profile(rendered["profile"], PROFILE)["pass"]
    assert not verify.check_profile(rendered["plain"], PROFILE)["pass"]
    other = tmp_path / "org-profile.yaml"
    other.write_text(PROFILE.read_text(encoding="utf-8").replace("display_name: Northwind", "display_name: Fabrikam"),
                     encoding="utf-8")
    check = verify.check_profile(rendered["profile"], other)
    assert not check["pass"] and check["detail"]["display_name"] == "Fabrikam"


def test_a_browser_that_outlives_its_timeout_still_counts_the_png_it_wrote(tmp_path, monkeypatch):
    target = tmp_path / "shot.png"

    def hangs(argv, **kwargs):
        target.write_bytes(b"\x89PNG fake")
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    monkeypatch.setattr(verify.subprocess, "run", hangs)
    assert verify.screenshot("browser", "file:///x", target, 100, 100, tmp_path / "profile") is True


def _fake_rqh(report_html: str):
    def fake(args: list[str], cwd: Path) -> dict:
        if args[0] == "init":
            (cwd / ".riskquant").mkdir()
        if args[0] == "report":
            (cwd / ".riskquant" / "runs" / verify.RUN_ID / "v1").mkdir(exist_ok=True)
            (cwd / ".riskquant" / "runs" / verify.RUN_ID / "v1" / "report.html").write_text(report_html, encoding="utf-8")
        data = {"n": 10, "seed": 1, "status": "finalized", "latest_version": 1, "next_skill": None}
        return {"argv": ["rqh", *args, "--json"], "exit": 0, "envelope": {"ok": True, "data": data}, "stderr": ""}
    return fake


def test_a_browser_crash_keeps_steps_json_and_removes_the_mobile_frame(tmp_path, monkeypatch, rendered):
    seen = {}

    def crashes(browser, url, target, width, height, profile):
        seen["steps_written"] = (target.parent / "steps.json").is_file()
        raise OSError("browser fault")

    monkeypatch.setattr(verify, "rqh", _fake_rqh(rendered["plain"].read_text(encoding="utf-8")))
    monkeypatch.setattr(verify, "find_browser", lambda: "browser")
    monkeypatch.setattr(verify, "screenshot", crashes)
    args = Namespace(out=str(tmp_path), route="yolo", n=10, seed=1, profile=None)
    with pytest.raises(OSError):
        verify.cmd_run(args)
    run_dir = next(tmp_path.iterdir())
    assert seen["steps_written"]
    assert [s["name"] for s in json.loads((run_dir / "evidence" / "steps.json").read_text(encoding="utf-8"))][0] == "init"
    assert not (run_dir / "mobile-frame.html").exists()


def test_cleanup_removes_a_mobile_frame_a_crashed_run_left(tmp_path, capsys):
    (tmp_path / "ws").mkdir()
    (tmp_path / "evidence").mkdir()
    (tmp_path / "mobile-frame.html").write_text("<iframe>", encoding="utf-8")
    assert verify.cmd_cleanup(Namespace(run_dir=str(tmp_path))) == 0
    assert not (tmp_path / "mobile-frame.html").exists()
    capsys.readouterr()
