"""AC30: the YOLO route replayed through `rqh`, following `next_skill` between phases."""

from __future__ import annotations

import pytest
from replay_driver import Replay, load_verify


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    """One replay shared by the tests below: every `rqh` call starts a Python process."""
    run = Replay("yolo", tmp_path_factory.mktemp("yolo"))
    run.final = run.follow(run.script["phases"])
    run.rejected_report = run.report_path(1).read_text(encoding="utf-8")
    return run


def test_yolo_ends_with_a_banner_report_when_the_narrative_is_rejected_twice(replay):
    assert [skill for skill, _ in replay.seen] == ["scope-scenario", "collect-data", "simulate", "report", None]
    assert replay.final["next_skill"] is None
    assert replay.final["status"] == "finalized" and replay.final["latest_version"] == 1
    checks = load_verify().check_report(replay.report_path(1), "yolo")
    assert all(c["pass"] for c in checks), [c for c in checks if not c["pass"]]
    assert "Not yet validated" in replay.rejected_report
    assert "five million" not in replay.rejected_report


def test_yolo_happy_path_renders_the_accepted_narrative_with_the_banner(replay):
    replay.run_ops(replay.script["accepted_report"])
    report = replay.report_path(1)
    checks = load_verify().check_report(report, "yolo")
    assert all(c["pass"] for c in checks), [c for c in checks if not c["pass"]]
    text = report.read_text(encoding="utf-8")
    assert "In a bad year the loss reaches" in text  # a sentence of the accepted narrative
    assert "{{" not in text  # every placeholder was filled by rqh


def test_the_driver_rejects_a_step_the_status_did_not_name(tmp_path):
    fresh = Replay("yolo", tmp_path)
    with pytest.raises(AssertionError, match="status named 'scope-scenario'"):
        fresh.follow([fresh.script["phases"][1]])
