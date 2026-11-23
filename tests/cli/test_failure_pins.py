"""Every command's representative failures, pinned byte for byte.

Each case builds a fresh workspace, runs one failing command twice (``--json`` and plain) and
compares the exit code, the envelope and the plain stderr with ``fixtures/failure_pins.json``.
Paths under the test's temporary directory read as ``<tmp>`` with forward slashes, so the pins
hold on every OS. Re-record deliberately with ``RQH_RECORD_PINS=1`` and review the diff.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from rqharness import cli

SAMPLE = Path(__file__).parent.parent / "validate" / "fixtures" / "sample-run"
PINS = Path(__file__).parent / "fixtures" / "failure_pins.json"
RECORD = os.environ.get("RQH_RECORD_PINS") == "1"
R, S = "r", "s"  # r: confirmed (collecting); s: scoped files, never confirmed (scoping)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _workspace(tmp: Path) -> Path:
    assert cli.main(["init"]) == 0
    ws = tmp / ".riskquant"
    for run_id in (R, S):
        (ws / "runs" / run_id).mkdir(parents=True)
        for name in ("scenario.yaml", "inputs.yaml"):
            shutil.copy(SAMPLE / name, ws / "runs" / run_id / name)
    assert cli.main(["run", "confirm", R, "--route", "accuracy", "--n", "200", "--seed", "7"]) == 0
    return ws


def _finalized(tmp: Path) -> Path:
    ws = _workspace(tmp)
    assert cli.main(["finalize", R]) == 0
    return ws


def _with_request(tmp: Path) -> Path:
    ws = _workspace(tmp)
    assert cli.main(["requests", "add", R, "--parameter", "primary_loss.response", "--owner-role", "IR lead",
                     "--ask", "cost?", "--draft", "hello"]) == 0
    return ws


def _with_candidate(tmp: Path) -> Path:
    ws = _workspace(tmp)
    assert cli.main(["candidates", "add", R, "--parameter", "primary_loss.response", "--min", "1", "--mode", "2",
                     "--max", "3", "--unit", "USD", "--evidence", "measured", "--origin", "connector:x"]) == 0
    return ws


def _none(tmp: Path) -> None:
    return None


BAD = "schema_version: '1'\n"
SHIPPED_ID = "ransomware-recovery-cost-sophos-2025"  # a shipped benchmark the workspace overrides


def _invalid_memory_override(ws: Path) -> None:
    """Run ``s`` cites a shipped benchmark's id whose memory override is broken."""
    _write(ws / "library" / "override.yaml", f"{BAD}entry_id: {SHIPPED_ID}\n")
    inputs = ws / "runs" / S / "inputs.yaml"
    source = f"  - {{id: mem, kind: memory, title: Override, library_entry_id: {SHIPPED_ID}}}\n"
    inputs.write_text(inputs.read_text(encoding="utf-8").replace("sources:\n", "sources:\n" + source, 1),
                      encoding="utf-8")


# name -> (setup, extra setup on the workspace, argv)
CASES: dict[str, tuple] = {
    "argv_no_command": (_none, None, []),
    "argv_missing_argument": (_none, None, ["run", "confirm"]),
    "status_no_workspace": (_none, None, ["status", R]),
    "status_missing_run": (_workspace, None, ["status", "nope"]),
    "status_outside_workspace": (_workspace, lambda ws: (ws.parent / "copy").mkdir(), ["status", "<tmp>/copy"]),
    "status_invalid_run_yaml": (_workspace, lambda ws: _write(ws / "runs" / R / "run.yaml", BAD), ["status", R]),
    "validate_unknown_kind": (_workspace, lambda ws: _write(ws.parent / "doc.yaml", BAD), ["validate", "<tmp>/doc.yaml"]),
    "validate_invalid_run": (_workspace, lambda ws: _write(ws / "runs" / S / "inputs.yaml", BAD), ["validate", S]),
    "validate_invalid_memory_entry": (_workspace, _invalid_memory_override, ["validate", S]),
    "confirm_invalid_scenario": (_workspace, lambda ws: _write(ws / "runs" / S / "scenario.yaml", BAD),
                                 ["run", "confirm", S, "--route", "yolo"]),
    "confirm_n_out_of_range": (_workspace, None, ["run", "confirm", S, "--route", "yolo", "--n", "0"]),
    "confirm_seed_out_of_range": (_workspace, None, ["run", "confirm", S, "--route", "yolo", "--seed", "-1"]),
    "route_unknown_path": (_workspace, None, ["run", "route", R, "bogus.path", "yolo"]),
    "route_while_scoping": (_workspace, None, ["run", "route", S, "primary_loss.response", "yolo"]),
    "pause_guard": (_workspace, None, ["run", "pause", R]),
    "resume_illegal": (_workspace, None, ["run", "resume", R]),
    "finalize_n_out_of_range": (_workspace, None, ["finalize", R, "--n", "0"]),
    "finalize_seed_out_of_range": (_workspace, None, ["finalize", R, "--seed", "-1"]),
    "finalize_scoping": (_workspace, None, ["finalize", S]),
    "finalize_invalid_inputs": (_workspace, lambda ws: _write(ws / "runs" / R / "inputs.yaml", BAD), ["finalize", R]),
    "finalize_no_inputs": (_workspace, lambda ws: (ws / "runs" / R / "inputs.yaml").unlink(), ["finalize", R]),
    "finalize_invalid_profile": (_workspace, lambda ws: _write(ws / "org-profile.yaml", BAD), ["finalize", R]),
    "finalize_lock_held": (_workspace, lambda ws: _write(ws / "runs" / R / ".lock", "1\n"), ["finalize", R]),
    "report_no_version": (_workspace, None, ["report", R]),
    "report_missing_narrative_file": (_finalized, None, ["report", R, "--narrative", "<tmp>/none.md"]),
    "report_narrative_rejected": (_finalized, lambda ws: _write(ws.parent / "n.md", "Loss is $5m a year.\n"),
                                  ["report", R, "--narrative", "<tmp>/n.md"]),
    "requests_add_rejected": (_workspace, None, ["requests", "add", R, "--parameter", "primary_loss.bogus",
                                                 "--owner-role", "IR", "--ask", "a", "--draft", "d"]),
    "requests_add_file_outside": (_workspace, lambda ws: _write(ws.parent / "ask.txt", "a"),
                                  ["requests", "add", R, "--parameter", "primary_loss.response", "--owner-role", "IR",
                                   "--ask-file", "<tmp>/ask.txt", "--draft", "d"]),
    "requests_update_not_found": (_workspace, None, ["requests", "update", R, "req-9", "--status", "sent"]),
    "requests_update_illegal": (_with_request, None, ["requests", "update", R, "req-1", "--status", "answered"]),
    "requests_update_incomplete_value": (_with_request, None, ["requests", "update", R, "req-1", "--status", "sent",
                                                               "--min", "1"]),
    "requests_update_answer_status": (_with_request, None, ["requests", "update", R, "req-1", "--status",
                                                            "withdrawn", "--note", "n"]),
    "candidates_confirm_not_found": (_workspace, None, ["candidates", "confirm", R, "cand-9"]),
    "candidates_confirm_no_inputs": (_with_candidate, lambda ws: (ws / "runs" / R / "inputs.yaml").unlink(),
                                     ["candidates", "confirm", R, "cand-1"]),
    "candidates_reject_illegal": (_with_candidate, lambda ws: cli.main(["candidates", "confirm", R, "cand-1"]),
                                  ["candidates", "reject", R, "cand-1"]),
    "library_list_no_workspace": (_none, None, ["library", "list"]),
    "library_add_missing_file": (_workspace, None, ["library", "add", "<tmp>/none.yaml"]),
    "library_add_invalid": (_workspace, lambda ws: _write(ws.parent / "e.yaml", BAD), ["library", "add", "<tmp>/e.yaml"]),
    "library_remove_missing": (_workspace, None, ["library", "remove", "nope"]),
    "library_validate_invalid": (_workspace, lambda ws: _write(ws / "library" / "bad.yaml", BAD), ["library", "validate"]),
    "search_no_key": (_none, None, ["search", "q"]),
}


HELP_CASES = {"argv_no_command"}  # cases whose stderr is argparse's full help


def _normal(value, tmp: Path):
    """``value`` with the temporary directory as ``<tmp>`` and the separators in its paths as ``/``."""
    if isinstance(value, list):
        return [_normal(v, tmp) for v in value]
    if isinstance(value, dict):
        return {k: _normal(v, tmp) for k, v in value.items()}
    for spelling in sorted({str(tmp.resolve()), str(tmp)}, key=len, reverse=True):
        value = value.replace(spelling, "<tmp>")
    return re.sub(r"<tmp>[^\s'\";,]*", lambda m: m.group(0).replace("\\", "/"), value)


def _observe(name: str, tmp: Path, capsys) -> dict:
    setup, extra, argv = CASES[name]
    ws = setup(tmp)
    if extra is not None:
        extra(ws if ws is not None else tmp / ".riskquant")
    argv = [a.replace("<tmp>", str(tmp)) for a in argv]
    capsys.readouterr()
    code = cli.main([*argv, "--json"])
    envelope = json.loads(capsys.readouterr().out)
    plain_code = cli.main(argv)
    plain = capsys.readouterr()
    assert plain_code == code
    stderr = _normal(plain.err, tmp)
    if name in HELP_CASES:
        # argparse's help layout differs between Python versions; pin that help was printed, not its bytes
        assert stderr.startswith("usage: rqh") and "<command>" in stderr
        stderr = "<argparse help>"
    return {"exit": code, "issues": _normal(envelope["issues"], tmp),
            "ok": envelope["ok"], "stderr": stderr}


@pytest.fixture
def tmp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setenv("COLUMNS", "80")  # argparse wraps the help it prints for `rqh` alone
    return tmp_path


@pytest.mark.parametrize("name", sorted(CASES))
def test_failure_is_pinned(name, tmp, capsys):
    seen = _observe(name, tmp, capsys)
    pins = json.loads(PINS.read_text(encoding="utf-8")) if PINS.is_file() else {}
    if RECORD:
        pins[name] = seen
        PINS.parent.mkdir(exist_ok=True)
        PINS.write_text(json.dumps(dict(sorted(pins.items())), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8", newline="\n")
        return
    assert seen == pins[name]
    assert seen["exit"] != 0 and not seen["ok"]


def test_every_pin_has_a_case():
    assert sorted(json.loads(PINS.read_text(encoding="utf-8"))) == sorted(CASES)
