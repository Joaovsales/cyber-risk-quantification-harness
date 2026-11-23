"""AC31: the Accuracy route replayed through `rqh` with a fixture org profile and canned answers."""

from __future__ import annotations

import json

import pytest
from replay_driver import Replay, load_verify


@pytest.fixture(scope="module")
def replay(tmp_path_factory):
    """One replay shared by the tests below: every `rqh` call starts a Python process."""
    run = Replay("accuracy", tmp_path_factory.mktemp("accuracy"))
    run.final = run.follow(run.script["phases"])
    return run


def _load(replay: Replay, version: int, name: str) -> dict:
    return json.loads((replay.run_dir / f"v{version}" / name).read_text(encoding="utf-8"))


def test_accuracy_pauses_resumes_confirms_and_finalizes_v2_with_a_higher_score(replay):
    assert [skill for skill, _ in replay.seen] == [
        "scope-scenario", "collect-data", None, "simulate", "report", None, "collect-data", "simulate", "report", None]
    assert replay.seen[2] == (None, ["req-1", "req-2"])  # paused: null, with the open requests in waiting_on
    assert replay.final["next_skill"] is None
    assert replay.final["latest_version"] == replay.script["final"]["latest_version"]

    seed = replay.script["setup"]["seed"]
    assert _load(replay, 1, "run_manifest.json")["seed"] == _load(replay, 2, "run_manifest.json")["seed"] == seed
    assert _load(replay, 2, "run_summary.json")["quality"]["score"] > _load(replay, 1, "run_summary.json")["quality"]["score"]


def test_the_confirmed_candidate_is_the_only_input_that_changed(replay):
    def values(version: int) -> dict:
        return {p["path"]: (p["min"], p["mode"], p["max"], p["tier"])
                for p in _load(replay, version, "run_summary.json")["parameters"]}

    v1, v2 = values(1), values(2)
    assert [path for path in v1 if v1[path] != v2[path]] == ["primary_loss.response"]
    assert v2["primary_loss.response"] == (6000, 18000, 60000, "internal_data")


def test_requests_come_from_the_skills_request_file_and_the_legacy_flags(replay):
    # req-1 is added the way accuracy.md says (one --request-file); req-2 keeps the per-field flags working
    targets = {r["id"]: r["target"] for r in replay.rqh(["requests", "list", "credential-phishing-bec"])["data"]["requests"]}
    assert targets == {"req-1": {"owner_role": "Incident response lead", "person": "Dana O'Reyes"},
                       "req-2": {"owner_role": "Email security lead"}}


def test_accuracy_reports_are_valid_and_carry_no_yolo_banner(replay):
    verify = load_verify()
    for version in (1, 2):
        checks = verify.check_report(replay.report_path(version), "accuracy")
        assert all(c["pass"] for c in checks), [c for c in checks if not c["pass"]]
