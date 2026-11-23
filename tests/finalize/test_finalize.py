"""Slice 8: finalize and versioning (AC13)."""

from __future__ import annotations

import contextvars
import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from rqharness import cli, engine, finalize as fin, model, outcomes, runstate, validate, workspace
from rqharness.commands.run import DEFAULT_N

SAMPLE = Path(__file__).parent.parent / "validate" / "fixtures" / "sample-run"
RUN_ID = "credential-phishing-bec"
FILES = {"inputs.snapshot.yaml", "scenario.snapshot.yaml", "theme.snapshot.yaml",
         "run_manifest.json", "run_summary.json", "draws.npz"}
PROFILE = {
    "schema_version": "1", "org_name": "Acme",
    "theme": {"accent": "#112233", "display_name": "Acme Risk"},
    "people": [{"name": "Ada", "role": "CISO"}],
    "systems": [{"id": "idp", "kind": "identity", "name": "Okta", "owner_role": "IT"}],
}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    return tmp_path / ".riskquant"


@pytest.fixture
def run_dir(ws):
    assert cli.main(["init"]) == 0
    d = ws / "runs" / RUN_ID
    d.mkdir(parents=True)
    for name in ("scenario.yaml", "inputs.yaml"):
        shutil.copy(SAMPLE / name, d / name)
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo", "--n", "2000", "--seed", "7"]) == 0
    return d


def run_of(run_dir: Path) -> workspace.Run:
    """The Run a command would resolve for this directory."""
    return cli.resolve_run(str(run_dir))


def again(run_dir, **kw):
    runstate.apply(run_dir, "reopen")
    return fin.finalize(run_of(run_dir), **kw)


def tree(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def rqh(*argv, capsys):
    capsys.readouterr()
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr().out
    return code, (json.loads(out) if out.strip() else None)


def test_finalize_creates_next_version_with_snapshots(run_dir):
    first = fin.finalize(run_of(run_dir))
    assert isinstance(first, fin.Finalized) and first.version == 1
    assert {p.name for p in (run_dir / "v1").iterdir()} == FILES
    second = again(run_dir)
    assert second.version == 2 and second.path == run_dir / "v2"
    assert {p.name for p in (run_dir / "v2").iterdir()} == FILES
    assert (run_dir / "v2" / "inputs.snapshot.yaml").read_bytes() == (run_dir / "inputs.yaml").read_bytes()
    assert (run_dir / "v2" / "scenario.snapshot.yaml").read_bytes() == (run_dir / "scenario.yaml").read_bytes()
    assert runstate.status_of(run_dir) == "finalized"
    assert fin.latest_version(run_dir) == 2
    summary = json.loads((run_dir / "v2" / "run_summary.json").read_text("utf-8"))
    assert list(summary)[-1] == "quality" and summary["quality"]["grade"] in "ABCD"
    manifest = json.loads((run_dir / "v2" / "run_manifest.json").read_text("utf-8"))
    assert manifest["version"] == 2 and manifest["route"] == "yolo"
    assert manifest["inputs_sha256"] == hashlib.sha256((run_dir / "inputs.yaml").read_bytes()).hexdigest()
    with np.load(run_dir / "v2" / "draws.npz") as draws:
        assert "baseline.annual_loss" in draws.files and len(draws["baseline.lef"]) == 2000
        assert "baseline.event_count" in draws.files


@pytest.mark.parametrize("edit", ["valid", "invalid"])
def test_a_write_after_validation_never_reaches_the_version(run_dir, monkeypatch, edit):
    """Finalize snapshots, simulates and hashes exactly the bytes it validated."""
    validated = {name: (run_dir / name).read_bytes() for name in ("inputs.yaml", "scenario.yaml")}
    edited = {
        "valid": {"inputs.yaml": validated["inputs.yaml"].replace(b"Incident response per event", b"Edited label"),
                  "scenario.yaml": validated["scenario.yaml"] + b"# edited\n"},
        "invalid": {"inputs.yaml": b"not: [valid", "scenario.yaml": b"not: [valid"},
    }[edit]
    real_latest = fin.latest_version

    def write_behind_the_lock(run_dir_arg):  # runs after validation, before the snapshot
        for name, data in edited.items():
            (run_dir / name).write_bytes(data)
        return real_latest(run_dir_arg)

    monkeypatch.setattr(fin, "latest_version", write_behind_the_lock)
    fin.finalize(run_of(run_dir))
    assert (run_dir / "inputs.yaml").read_bytes() == edited["inputs.yaml"]
    assert (run_dir / "v1" / "inputs.snapshot.yaml").read_bytes() == validated["inputs.yaml"]
    assert (run_dir / "v1" / "scenario.snapshot.yaml").read_bytes() == validated["scenario.yaml"]
    manifest = json.loads((run_dir / "v1" / "run_manifest.json").read_text("utf-8"))
    assert manifest["inputs_sha256"] == hashlib.sha256(validated["inputs.yaml"]).hexdigest()
    assert "Edited label" not in (run_dir / "v1" / "run_summary.json").read_text("utf-8")


def test_theme_snapshot_without_and_with_profile(run_dir, ws):
    fin.finalize(run_of(run_dir))
    assert workspace.read_yaml(run_dir / "v1" / "theme.snapshot.yaml") == {
        "schema_version": "1", "org_name": None, "theme": {}, "people": [], "systems": []}
    workspace.write_yaml(ws / "org-profile.yaml", PROFILE)
    again(run_dir)
    assert workspace.read_yaml(run_dir / "v2" / "theme.snapshot.yaml") == {
        "schema_version": "1", "org_name": "Acme",
        "theme": {"accent": "#112233", "display_name": "Acme Risk"},
        "people": [{"name": "Ada", "role": "CISO"}],
        "systems": [{"id": "idp", "kind": "identity", "name": "Okta", "owner_role": "IT"}]}


def test_earlier_versions_untouched(run_dir, ws):
    workspace.write_yaml(ws / "org-profile.yaml", PROFILE)
    fin.finalize(run_of(run_dir))
    (run_dir / "v1" / "report.html").write_text("<html>rendered</html>", encoding="utf-8")
    before = tree(run_dir / "v1")
    text = (run_dir / "inputs.yaml").read_text("utf-8").replace("Incident response per event", "Edited label")
    (run_dir / "inputs.yaml").write_text(text, encoding="utf-8")
    workspace.write_yaml(ws / "org-profile.yaml", {**PROFILE, "org_name": "Renamed", "people": []})
    assert again(run_dir).version == 2
    assert tree(run_dir / "v1") == before
    assert "Renamed" in (run_dir / "v2" / "theme.snapshot.yaml").read_text("utf-8")


def test_stale_tmp_cleaned(run_dir):
    fin.finalize(run_of(run_dir))
    leftover = run_dir / "v2.tmp"
    leftover.mkdir()
    (leftover / "junk.txt").write_text("x", encoding="utf-8")
    (run_dir / "v9.tmp").mkdir()
    assert again(run_dir).version == 2
    assert not list(run_dir.glob("v*.tmp"))
    assert {p.name for p in (run_dir / "v2").iterdir()} == FILES


def test_reuses_run_seed(run_dir):
    result = fin.finalize(run_of(run_dir))
    assert (result.n, result.seed) == (2000, 7)
    manifest = json.loads((result.path / "run_manifest.json").read_text("utf-8"))
    assert (manifest["n"], manifest["seed"]) == (2000, 7)


def test_seed_override_recorded_in_manifest_only(run_dir):
    result = fin.finalize(run_of(run_dir), seed=99, n=1000)
    manifest = json.loads((result.path / "run_manifest.json").read_text("utf-8"))
    assert (manifest["n"], manifest["seed"]) == (1000, 99)
    state = runstate.read_state(run_dir)
    assert (state["n"], state["seed"]) == (2000, 7)


def test_same_seed_and_n_give_identical_summary(run_dir):
    a = fin.finalize(run_of(run_dir))
    b = again(run_dir)
    assert (a.path / "run_summary.json").read_bytes() == (b.path / "run_summary.json").read_bytes()


def test_lock_held_exit_1(run_dir, capsys):
    lock = run_dir / ".lock"
    lock.write_text("1 2026-01-01T00:00:00Z", encoding="utf-8")
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 1 and env["issues"][0]["rule"] == "lock_held"
    assert env["issues"][0]["path"] == "run.lock"
    assert lock.exists()  # the holder's lock is not ours to release
    assert not list(run_dir.glob("v*")) and runstate.status_of(run_dir) == "collecting"


def test_stale_lock_is_retaken(run_dir):
    lock = run_dir / ".lock"
    lock.write_text("1 old", encoding="utf-8")
    old = time.time() - 11 * 60
    os.utime(lock, (old, old))
    assert isinstance(fin.finalize(run_of(run_dir)), fin.Finalized)
    assert not lock.exists()


def test_lock_released_after_success_and_rejection(run_dir):
    fin.finalize(run_of(run_dir))
    assert not (run_dir / ".lock").exists()
    (run_dir / "inputs.yaml").write_text("not: [valid", encoding="utf-8")
    runstate.apply(run_dir, "reopen")
    with pytest.raises(outcomes.Rejected) as exc:
        fin.finalize(run_of(run_dir))
    assert exc.value.issues
    assert not (run_dir / ".lock").exists()
    assert not list(run_dir.glob("v*.tmp")) and fin.latest_version(run_dir) == 1


def test_illegal_from_scoping_writes_nothing(ws, capsys):
    assert cli.main(["init"]) == 0
    d = ws / "runs" / RUN_ID
    d.mkdir(parents=True)
    shutil.copy(SAMPLE / "scenario.yaml", d / "scenario.yaml")
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 3 and env["issues"][0]["rule"] == "illegal_transition"
    assert env["issues"][0]["path"] == "run.status"
    assert sorted(p.name for p in d.iterdir()) == ["scenario.yaml"]


def test_illegal_from_finalized_until_reopened(run_dir, capsys):
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 0 and env["data"]["version"] == 1 and env["data"]["seed"] == 7
    before = tree(run_dir)
    code, _ = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 3 and tree(run_dir) == before
    assert cli.main(["run", "reopen", RUN_ID]) == 0
    code, env = rqh("finalize", RUN_ID, "--n", "500", "--seed", "5", capsys=capsys)
    assert code == 0 and env["data"]["version"] == 2 and env["data"]["n"] == 500


@pytest.mark.parametrize("frm", [None, "scoping", "finalized"])
def test_illegal_finalize_envelope_is_pinned(run_dir, frm, capsys):
    if frm is None:
        (run_dir / "run.yaml").unlink()
    else:
        workspace.write_yaml(run_dir / "run.yaml", {**workspace.read_yaml(run_dir / "run.yaml"), "status": frm})
    before = tree(run_dir)
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 3 and env["issues"] == [{
        "path": "run.status", "rule": "illegal_transition",
        "message": f"cannot finalize a run that is {frm or 'scoping'}"}]
    assert tree(run_dir) == before


def crash_finalize(run_dir, monkeypatch, *, when):
    """Run finalize and kill it at ``when``: before the status write, or after it but before the journal is removed."""
    real_apply, real_unlink = runstate.apply, Path.unlink

    def apply(d, trigger, **changes):
        if when == "status" and trigger == "finalize":
            raise KeyboardInterrupt
        return real_apply(d, trigger, **changes)

    def unlink(path, *a, **k):
        if when == "journal" and path.name == runstate.PENDING_NAME:
            raise KeyboardInterrupt
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(runstate, "apply", apply)
    monkeypatch.setattr(Path, "unlink", unlink)
    with pytest.raises(KeyboardInterrupt):
        fin.finalize(run_of(run_dir))
    monkeypatch.setattr(runstate, "apply", real_apply)
    monkeypatch.setattr(Path, "unlink", real_unlink)


def test_crash_between_rename_and_status_leaves_complete_version(run_dir, monkeypatch):
    crash_finalize(run_dir, monkeypatch, when="status")
    assert FILES == {p.name for p in (run_dir / "v1").iterdir()}
    assert fin.latest_version(run_dir) == 1 and not (run_dir / ".lock").exists()


def test_a_version_whose_status_write_was_lost_counts_as_finalized(run_dir, monkeypatch, capsys):
    """F-C2: the crash is rolled forward, so the router asks for its report and no duplicate v2 is simulated."""
    crash_finalize(run_dir, monkeypatch, when="status")
    assert runstate.status_of(run_dir) == "finalized"
    code, env = rqh("status", RUN_ID, capsys=capsys)
    assert code == 0 and (env["data"]["status"], env["data"]["next_skill"], env["data"]["latest_version"]) == (
        "finalized", "report", 1)
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 3 and fin.latest_version(run_dir) == 1
    assert runstate.read_state(run_dir)["status"] == "finalized"  # the next locked write recorded it
    assert not (run_dir / runstate.PENDING_NAME).exists()
    assert again(run_dir).version == 2  # reopen-then-finalize still makes the next version


def test_reopen_after_a_crash_that_left_only_the_journal_still_finalizes_the_next_version(run_dir, monkeypatch):
    """F-C2: a journal left after the status write is spent; it never turns a reopened run back to finalized."""
    crash_finalize(run_dir, monkeypatch, when="journal")
    assert (run_dir / runstate.PENDING_NAME).exists() and runstate.status_of(run_dir) == "finalized"
    assert cli.main(["run", "reopen", RUN_ID]) == 0
    assert runstate.status_of(run_dir) == "collecting" and not (run_dir / runstate.PENDING_NAME).exists()
    assert fin.finalize(run_of(run_dir)).version == 2


def test_finalize_checks_the_status_under_the_run_lock(run_dir, monkeypatch):
    """F-C2: the status check and the status write both happen while finalize holds the lock."""
    held = []
    real_check = runstate.check

    def check(d, trigger):
        held.append((d / runstate.LOCK_NAME).exists())
        return real_check(d, trigger)

    monkeypatch.setattr(runstate, "check", check)
    fin.finalize(run_of(run_dir))
    assert held == [True]


def in_another_writer(*argv) -> int:
    """``rqh <argv>`` from a second writer: a new thread holds none of this one's locks."""
    codes: list[int] = []
    thread = threading.Thread(target=lambda: codes.append(cli.main(list(argv))))
    thread.start()
    thread.join()
    return codes[0]


def test_a_status_change_while_finalize_runs_is_refused_with_lock_held(run_dir, monkeypatch):
    """F-C2: a rescope during the simulation is refused (exit 1), so finalize never exits 3 after writing v1."""
    real_simulate, codes = engine.simulate, []

    def simulate(*a, **k):
        codes.append(in_another_writer("run", "rescope", RUN_ID))
        return real_simulate(*a, **k)

    monkeypatch.setattr(engine, "simulate", simulate)
    assert fin.finalize(run_of(run_dir)).version == 1
    assert codes == [1] and runstate.status_of(run_dir) == "finalized"


def test_a_live_holder_keeps_the_lock_past_the_stale_age(run_dir, monkeypatch):
    """F-C4: the holder refreshes the lock while it works, so a long finalize is never taken over."""
    monkeypatch.setattr(runstate, "LOCK_STALE_SECONDS", 0.5)
    monkeypatch.setattr(runstate, "LOCK_REFRESH_SECONDS", 0.05)
    with runstate.locked(run_dir):
        time.sleep(1.2)
        assert in_another_writer("run", "rescope", RUN_ID) == 1
    assert runstate.status_of(run_dir) == "collecting"


def test_a_holder_never_releases_a_lock_it_does_not_hold(run_dir):
    """F-C4: release deletes only the lock this process created."""
    lock = run_dir / runstate.LOCK_NAME
    with runstate.locked(run_dir):
        lock.write_text("another holder\n", encoding="utf-8")
    assert lock.read_text(encoding="utf-8") == "another holder\n"


def test_two_writers_breaking_one_stale_lock_never_both_hold_it(run_dir, monkeypatch):
    """F-C4: the stale check is repeated under a break guard, so a lock retaken meanwhile is left alone."""
    lock = run_dir / runstate.LOCK_NAME
    lock.write_text("dead holder\n", encoding="utf-8")
    old = time.time() - 11 * 60
    os.utime(lock, (old, old))
    real_is_stale, raced = runstate._is_stale, []

    def other_writer_breaks_it_first(path):
        stale = real_is_stale(path)
        if stale and path == lock and not raced:
            raced.append(True)
            assert runstate._take_lock(lock, "other-writer")
        return stale

    monkeypatch.setattr(runstate, "_is_stale", other_writer_breaks_it_first)
    assert runstate._take_lock(lock, "this-writer") is False
    assert "other-writer" in lock.read_text(encoding="utf-8")


def test_a_lock_released_between_the_create_and_the_stale_check_is_taken(run_dir, monkeypatch):
    """Review 2: a lock that vanishes after the failed exclusive create is retried, never refused."""
    lock = run_dir / runstate.LOCK_NAME
    real_open, raced = os.open, []

    def holder_releases_it_meanwhile(path, flags, *a, **k):
        if Path(path) == lock and not raced:
            raced.append(True)
            raise FileExistsError(path)  # the holder's lock existed for the create, and is gone for the stat
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(runstate.os, "open", holder_releases_it_meanwhile)
    assert runstate._take_lock(lock, "this-writer")
    assert "this-writer" in lock.read_text(encoding="utf-8")


def test_a_brief_holder_is_waited_for_not_refused(run_dir):
    """Review 2: a writer waits a short while for the lock before it exits 1."""
    started, release = threading.Event(), threading.Event()

    def hold():
        with runstate.locked(run_dir):
            started.set()
            release.wait(10)

    holder = threading.Thread(target=hold)
    holder.start()
    started.wait(10)
    threading.Timer(0.5, release.set).start()
    assert in_another_writer("run", "rescope", RUN_ID) == 0
    holder.join()
    assert runstate.status_of(run_dir) == "scoping"


WRITER = """import pathlib, sys, time
from rqharness import cli
go, ready = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
ready.write_text("ready", encoding="utf-8")
while not go.exists():
    time.sleep(0.005)
sys.exit(cli.main(sys.argv[3:]))
"""


def test_parallel_writers_all_succeed_and_none_is_lost(run_dir, tmp_path):
    """Review 2: eight `rqh requests add` processes started together each add their request."""
    go = tmp_path / "go"
    env = {k: v for k, v in os.environ.items() if k != "RQH_WORKSPACE"}
    ready = [tmp_path / f"ready-{i}" for i in range(8)]
    writers = [subprocess.Popen(
        [sys.executable, "-c", WRITER, str(go), str(ready[i]), "requests", "add", RUN_ID, "--parameter", "primary_loss.response",
         "--owner-role", f"role-{i}", "--ask", "Cost?", "--draft", "Hi", "--json"],
        cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(8)]
    deadline = time.time() + 120
    while not all(p.exists() for p in ready) and time.time() < deadline:  # every writer has imported rqh
        time.sleep(0.05)
    go.write_text("go", encoding="utf-8")
    results = [(w.wait(120), *w.communicate()) for w in writers]
    assert [code for code, _, _ in results] == [0] * 8, results
    stored = workspace.read_yaml(run_dir / "requests.yaml")["requests"]
    assert sorted(r["target"]["owner_role"] for r in stored) == sorted(f"role-{i}" for i in range(8))
    assert sorted(r["id"] for r in stored) == sorted(f"req-{i}" for i in range(1, 9))


def test_a_journal_a_reader_holds_open_does_not_fail_finalize(run_dir, monkeypatch):
    """Review 3: the status is written, so a journal the filesystem will not delete yet is spent, not an error."""
    real_unlink = Path.unlink

    def held_open(path, *a, **k):
        if path.name == runstate.PENDING_NAME:
            raise PermissionError(13, "the file is open in another process", str(path))
        return real_unlink(path, *a, **k)

    monkeypatch.setattr(Path, "unlink", held_open)
    assert fin.finalize(run_of(run_dir)).version == 1
    assert runstate.status_of(run_dir) == "finalized"
    assert cli.main(["run", "reopen", RUN_ID]) == 0
    assert runstate.status_of(run_dir) == "collecting"  # the journal left behind never reads as finalized again
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert fin.finalize(run_of(run_dir)).version == 2
    assert not (run_dir / runstate.PENDING_NAME).exists()


def test_a_thread_that_inherits_the_context_still_takes_the_lock(run_dir, monkeypatch):
    """Review 7: re-entrancy is per thread, even for a thread started with the holder's context."""
    monkeypatch.setattr(runstate, "LOCK_WAIT_SECONDS", 0.1)
    outcome: list[str] = []

    def second_writer():
        try:
            with runstate.locked(run_dir):
                outcome.append("entered")
        except outcomes.Rejected as exc:
            outcome.append(exc.issues[0]["rule"])

    with runstate.locked(run_dir):
        thread = threading.Thread(target=contextvars.copy_context().run, args=(second_writer,))
        thread.start()
        thread.join()
    assert outcome == ["lock_held"]


def stale(path: Path) -> None:
    old = time.time() - 11 * 60
    os.utime(path, (old, old))


def test_a_breaker_never_removes_a_break_guard_it_does_not_hold(run_dir, monkeypatch):
    """Review 8: the break guard carries a token, so a breaker deletes only its own."""
    lock = run_dir / runstate.LOCK_NAME
    guard = lock.with_name(lock.name + ".break")
    lock.write_text("dead holder\n", encoding="utf-8")
    stale(lock)
    real_is_stale, checks = runstate._is_stale, []

    def guard_replaced_while_breaking(path):
        result = real_is_stale(path)
        if path == lock:
            checks.append(True)
            if len(checks) == 2:  # the re-check under the guard: another breaker has replaced it meanwhile
                guard.write_text("other-breaker\n", encoding="utf-8")
        return result

    monkeypatch.setattr(runstate, "_is_stale", guard_replaced_while_breaking)
    runstate._take_lock(lock, "this-writer")
    assert guard.read_text(encoding="utf-8") == "other-breaker\n"


def test_a_stale_break_guard_is_broken_and_the_lock_taken(run_dir):
    """Review 8: a guard left by a breaker that died is broken, and the stale lock is then retaken."""
    lock = run_dir / runstate.LOCK_NAME
    guard = lock.with_name(lock.name + ".break")
    lock.write_text("dead holder\n", encoding="utf-8")
    guard.write_text("dead-breaker\n", encoding="utf-8")
    stale(lock)
    stale(guard)
    with runstate.locked(run_dir):
        assert "dead holder" not in lock.read_text(encoding="utf-8")
    assert not lock.exists() and not guard.exists()


def test_the_heartbeat_outlives_a_transient_error_and_stops_when_the_lock_is_gone(tmp_path, monkeypatch):
    """Review 9: only a lock that no longer exists ends the refresh."""
    lock = tmp_path / runstate.LOCK_NAME
    lock.write_text("holder\n", encoding="utf-8")
    real_utime, calls = os.utime, []

    def utime(path, *a, **k):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError(13, "the file is busy", str(path))
        return real_utime(path, *a, **k)

    monkeypatch.setattr(runstate, "LOCK_REFRESH_SECONDS", 0.01)
    monkeypatch.setattr(runstate.os, "utime", utime)
    stop = threading.Event()
    beat = threading.Thread(target=runstate._keep_fresh, args=(lock, stop), daemon=True)
    beat.start()
    deadline = time.time() + 10
    while len(calls) < 3 and time.time() < deadline:
        time.sleep(0.01)
    assert len(calls) >= 3 and beat.is_alive()
    lock.unlink()
    beat.join(5)
    assert not beat.is_alive()
    stop.set()


def link_dir(target: Path, link: Path) -> None:
    """A directory symlink, or a junction on Windows without the symlink privilege."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        import _winapi
        _winapi.CreateJunction(str(target), str(link))


def test_a_leftover_tmp_that_is_a_link_is_unlinked_not_emptied(run_dir, tmp_path):
    """F-B12: finalize removes the link, never the files it points at."""
    precious = tmp_path / "precious"
    precious.mkdir()
    (precious / "keep.txt").write_text("keep", encoding="utf-8")
    link_dir(precious, run_dir / "v2.tmp")
    assert fin.finalize(run_of(run_dir)).version == 1
    assert (precious / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert not os.path.lexists(run_dir / "v2.tmp")


def test_finalize_never_deletes_a_leftover_through_a_linked_run_directory(run_dir, tmp_path, capsys):
    """F-B12: a run directory that links elsewhere still finalizes, but its leftovers are not rmtree'd."""
    elsewhere = tmp_path / "elsewhere"
    shutil.move(str(run_dir), str(elsewhere))
    link_dir(elsewhere, run_dir)
    leftover = elsewhere / "v3.tmp"
    leftover.mkdir()
    (leftover / "keep.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(outcomes.Rejected) as exc:
        fin._remove_leftovers(run_of(run_dir).dir)
    assert [(i["path"], i["rule"]) for i in exc.value.issues] == [("run.dir", "linked_run")]
    assert (leftover / "keep.txt").exists()
    try:
        os.close(os.open(run_dir / "probe", os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        os.unlink(run_dir / "probe")
    except FileExistsError:  # seen with junctions under a sandboxed Windows shell
        pytest.skip("this filesystem refuses an exclusive create through a directory link, so no lock can be taken")
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 1 and [(i["path"], i["rule"]) for i in env["issues"]] == [("run.dir", "linked_run")]
    assert (leftover / "keep.txt").exists() and fin.latest_version(elsewhere) is None
    shutil.rmtree(leftover)
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 0 and (elsewhere / "v1" / "run_manifest.json").is_file()


def test_confirm_without_run_yaml_takes_n_and_seed_from_the_latest_version(run_dir, capsys):
    """F-C3 (2): a run that lost run.yaml but has versions is never re-confirmed with a fresh seed."""
    assert fin.finalize(run_of(run_dir)).version == 1
    (run_dir / "run.yaml").unlink()
    code, env = rqh("run", "confirm", RUN_ID, "--route", "accuracy", capsys=capsys)
    assert code == 0 and (env["data"]["n"], env["data"]["seed"]) == (2000, 7)
    assert fin.finalize(run_of(run_dir)).seed == 7
    (run_dir / "run.yaml").unlink()
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", "--n", "900", "--seed", "3", capsys=capsys)
    assert code == 0 and (env["data"]["n"], env["data"]["seed"]) == (900, 3)


def test_confirm_with_n_and_seed_never_reads_an_unreadable_manifest(run_dir, capsys):
    """Review 4: explicit --n and --seed are the way out the unreadable-manifest refusal names."""
    assert fin.finalize(run_of(run_dir)).version == 1
    (run_dir / "run.yaml").unlink()
    (run_dir / "v1" / "run_manifest.json").write_text("not json", encoding="utf-8")
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", "--n", "900", capsys=capsys)
    assert code == 1 and [(i["path"], i["rule"]) for i in env["issues"]] == [("v1.run_manifest", "unreadable")]
    code, env = rqh("run", "confirm", RUN_ID, "--route", "yolo", "--n", "900", "--seed", "3", capsys=capsys)
    assert code == 0 and (env["data"]["n"], env["data"]["seed"]) == (900, 3)


def test_latest_version_ignores_tmp_and_other_names(tmp_path):
    for name in ("v1", "v3", "v10", "v2.tmp", "v0", "vx", "v04"):
        (tmp_path / name).mkdir()
    (tmp_path / "v99").write_text("a file", encoding="utf-8")
    assert fin.latest_version(tmp_path) == 10
    assert fin.latest_version(tmp_path / "missing") is None


@pytest.mark.parametrize("argv", [["--n", "0"], ["--n", "20000000"], ["--seed", "-1"]])
def test_finalize_rejects_out_of_range_n_and_seed_with_exit_2(argv, tmp_path, monkeypatch, capsys):
    from rqharness import cli

    monkeypatch.chdir(tmp_path)
    code = cli.main(["finalize", "any-run", *argv, "--json"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["issues"][0]["rule"] == "range"


def test_finalize_refuses_a_copied_run_outside_runs(run_dir, tmp_path, capsys):
    """A run copied out of `runs/` never takes the org profile two levels above it."""
    unrelated = tmp_path / "unrelated-org"
    copy = unrelated / "copies" / RUN_ID
    shutil.copytree(run_dir, copy)
    workspace.write_yaml(unrelated / "org-profile.yaml", {**PROFILE, "org_name": "Some Other Org"})
    code, env = rqh("finalize", str(copy), capsys=capsys)
    assert code == cli.EXIT_USAGE
    assert [(i["path"], i["rule"]) for i in env["issues"]] == [("run", "outside_workspace")]
    assert str(tmp_path / ".riskquant" / "runs") in env["issues"][0]["message"]
    assert not list(copy.glob("v*")), "a refused run is not finalized"


def test_finalize_validates_before_the_engine_runs(run_dir, monkeypatch, capsys):
    """D30: the engine trusts validated documents, so `rqh finalize` must reject first."""
    from rqharness import model

    def engine_reached(*_a, **_k):
        raise AssertionError("the engine was handed an unvalidated document")
    monkeypatch.setattr(model, "load_model_inputs", engine_reached)
    inputs = workspace.read_yaml(run_dir / "inputs.yaml")
    inputs["parameters"]["frequency"]["tef"]["min"] = 500  # above the mode
    inputs["parameters"]["analysis_period_years"] = 0
    workspace.write_yaml(run_dir / "inputs.yaml", inputs)
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == cli.EXIT_REJECTED
    assert ("inputs.parameters.analysis_period_years", "exclusiveMinimum") in {
        (i["path"], i["rule"]) for i in env["issues"]}
    assert not list(run_dir.glob("v*")) and runstate.status_of(run_dir) == "collecting"


def test_finalize_rejects_a_run_without_inputs(run_dir, capsys):
    """A run with no inputs.yaml is rejected by name, not a TypeError; `rqh validate` stays lenient."""
    (run_dir / "inputs.yaml").unlink()
    code, env = rqh("validate", RUN_ID, capsys=capsys)
    assert code == 0 and env["ok"]
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == cli.EXIT_REJECTED
    assert env["issues"] == [{"path": "inputs.document", "rule": "missing",
                              "message": f"inputs.yaml is missing from {run_of(run_dir).dir}"}]
    assert sorted(p.name for p in run_dir.iterdir()) == ["run.yaml", "scenario.yaml"]
    assert runstate.status_of(run_dir) == "collecting"


# --- one readiness rule for `rqh status` and `rqh finalize` ------------------------


def _replace(run_dir: Path, name: str, old: str, new: str) -> None:
    path = run_dir / name
    path.write_text(path.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")


DOCUMENT_STATES = {
    "valid": lambda d: None,
    "inputs_missing": lambda d: (d / "inputs.yaml").unlink(),
    "inputs_malformed": lambda d: (d / "inputs.yaml").write_text("{: bad", encoding="utf-8"),
    "inputs_schema_invalid": lambda d: _replace(d, "inputs.yaml", 'schema_version: "1"', 'schema_version: "9"'),
    "inputs_scenario_id_mismatch": lambda d: _replace(d, "inputs.yaml", f"scenario_id: {RUN_ID}", "scenario_id: other"),
    "scenario_missing": lambda d: (d / "scenario.yaml").unlink(),
    "scenario_invalid": lambda d: _replace(d, "scenario.yaml", "scenario_type:", "scenario_kind:"),
}


@pytest.mark.parametrize("state", DOCUMENT_STATES)
def test_status_says_simulate_exactly_when_finalize_accepts_the_documents(run_dir, state, capsys):
    """A collecting run with no pending candidate: `rqh status` and `rqh finalize` read one readiness rule."""
    DOCUMENT_STATES[state](run_dir)
    code, status = rqh("status", RUN_ID, capsys=capsys)
    assert code == 0
    code, finalized = rqh("finalize", RUN_ID, capsys=capsys)
    if code != 0:
        assert code == cli.EXIT_REJECTED
        documents = {i["path"].split(".")[0] for i in finalized["issues"]}
        assert documents <= {"scenario", "inputs"}, "rejected on the documents"
    assert (status["data"]["next_skill"] == "simulate") == (code == 0) == (state == "valid")


def test_status_and_finalize_both_take_readiness_from_the_report(run_dir, capsys, monkeypatch):
    """A stricter rule in the report changes both commands, so neither keeps its own copy of the rule."""
    refusal = outcomes.issue("inputs.document", "not_ready", "a stricter readiness rule refuses this run")
    real = validate.validate_run

    def stricter(run):
        return dataclasses.replace(real(run), readiness=[refusal])
    monkeypatch.setattr(validate, "validate_run", stricter)
    monkeypatch.setattr(fin, "validate_run", stricter)
    code, status = rqh("status", RUN_ID, capsys=capsys)
    assert code == 0 and status["data"]["next_skill"] == "collect-data"
    code, finalized = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == cli.EXIT_REJECTED and finalized["issues"] == [refusal]


# --- memory budget (D32) -----------------------------------------------------------


def _refuse_simulation(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("engine.simulate ran on a run over the memory budget")
    monkeypatch.setattr(fin.engine, "simulate", refuse)


def _high_frequency_run(ws, *, slef: dict | None = None):
    """The sample run with tef raised 100-fold (still inside the expected_events cap), confirmed at the default n."""
    assert cli.main(["init"]) == 0
    run_dir = ws / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    shutil.copy(SAMPLE / "scenario.yaml", run_dir / "scenario.yaml")
    inputs = workspace.read_yaml(SAMPLE / "inputs.yaml")
    inputs["parameters"]["frequency"]["tef"].update(min=20_000, mode=40_000, max=80_000)
    if slef:
        inputs["parameters"]["secondary_loss"]["slef"].update(slef)
    workspace.write_yaml(run_dir / "inputs.yaml", inputs)
    assert cli.main(["run", "confirm", RUN_ID, "--route", "yolo"]) == 0
    assert runstate.read_state(run_dir)["n"] == DEFAULT_N
    return run_dir


def _budget_rejection(run_dir, env, *, n: str, source: str) -> tuple[str, engine.EventBudget]:
    [found] = env["issues"]
    assert (found["path"], found["rule"]) == ("inputs.parameters", "memory_budget")
    assert f"n = {n}" in found["message"] and source in found["message"]
    assert not list(run_dir.glob("v*")) and not (run_dir / ".lock").exists()
    assert runstate.status_of(run_dir) == "collecting"
    return found["message"], engine.event_budget(model.load_model_inputs(workspace.read_yaml(run_dir / "inputs.yaml")))


def test_finalize_over_the_memory_budget_exits_1_and_suggests_a_lower_n(run_dir, capsys, monkeypatch):
    _refuse_simulation(monkeypatch)
    code, env = rqh("finalize", RUN_ID, "--n", "10000000", capsys=capsys)
    assert code == 1
    message, budget = _budget_rejection(run_dir, env, n="10,000,000", source="--n")
    assert budget.max_n >= 1 and f"rerun with --n {budget.max_n:,} or lower" in message


def test_high_frequency_run_confirmed_at_the_default_n_is_rejected_at_finalize(ws, capsys, monkeypatch):
    run_dir = _high_frequency_run(ws)
    _refuse_simulation(monkeypatch)
    code, env = rqh("finalize", RUN_ID, capsys=capsys)
    assert code == 1
    message, budget = _budget_rejection(run_dir, env, n=f"{DEFAULT_N:,}", source="run.yaml")
    assert f"rerun with --n {budget.max_n:,} or lower" in message


def test_run_over_the_budget_at_n_1_asks_for_fewer_events(ws, capsys, monkeypatch):
    run_dir = _high_frequency_run(ws, slef={"min": 30_000, "mode": 40_000, "max": 60_000})
    _refuse_simulation(monkeypatch)
    code, env = rqh("finalize", RUN_ID, "--n", "1", capsys=capsys)
    assert code == 1
    message, budget = _budget_rejection(run_dir, env, n="1", source="--n")
    assert budget.max_n == 0 and "lower the frequency estimates or secondary_loss.slef" in message


def test_run_within_the_memory_budget_still_finalizes(run_dir):
    assert isinstance(fin.finalize(run_of(run_dir)), fin.Finalized)


def test_finalize_loads_the_validated_inputs_once(run_dir, monkeypatch):
    """The memory-budget check and the simulation share one parse of the validated bytes."""
    loads = []
    real = model.load_model_inputs

    def counting(inputs):
        loads.append(inputs)
        return real(inputs)
    monkeypatch.setattr(model, "load_model_inputs", counting)
    fin.finalize(run_of(run_dir))
    assert len(loads) == 1


def test_finalize_reads_and_parses_each_document_once(run_dir, document_io):
    """Validation hands finalize the documents it read and parsed; nothing reads or parses them again."""
    fin.finalize(run_of(run_dir))
    for name in ("scenario.yaml", "inputs.yaml"):
        assert (document_io.reads[name], document_io.parses[name]) == (1, 1), name
