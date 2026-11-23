"""AC33: the release gate refuses a version without a passing, current live-eval record."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from replay_driver import ROOT

sys.path.insert(0, str(ROOT / "evals"))
import check_record  # noqa: E402


def passing_case(name: str = "yolo-one-question") -> dict:
    return {"name": name, "arms": {"with": [{"graders": [{"passed": True}]}, {"graders": [{"passed": True}]},
                                           {"graders": [{"passed": False}]}]}}


@pytest.fixture
def evals_dir(tmp_path: Path) -> Path:
    (tmp_path / "live" / "yolo" / "case").mkdir(parents=True)
    (tmp_path / "live" / "yolo" / "case" / "prompt.md").write_text("---\nname: yolo-one-question\n---\nask\n", encoding="utf-8")
    (tmp_path / "records").mkdir()
    return tmp_path


def write_record(evals: Path, version: str = "0.1.0", **overrides) -> Path:
    record = {"plugin_version": version, "suite_sha256": check_record.suite_sha256(evals), "threshold": 0.66,
              "cases": [passing_case()], **overrides}
    path = evals / "records" / f"{version}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_a_current_passing_record_passes(evals_dir):
    write_record(evals_dir)
    assert check_record.check("0.1.0", evals_dir) == []


def test_a_record_that_skips_a_case_directory_fails(evals_dir):
    skipped = evals_dir / "live" / "skills" / "simulate" / "trigger"
    skipped.mkdir(parents=True)
    (skipped / "prompt.md").write_text("---\nname: skill-simulate-trigger\n---\nrun it\n", encoding="utf-8")
    write_record(evals_dir)
    assert any("skill-simulate-trigger" in p for p in check_record.check("0.1.0", evals_dir))


def test_a_missing_record_fails(evals_dir):
    assert "no live-eval record" in check_record.check("0.1.0", evals_dir)[0]


def test_a_record_for_another_version_fails(evals_dir):
    path = write_record(evals_dir, "0.1.0")
    path.rename(evals_dir / "records" / "0.2.0.json")
    assert any("not '0.2.0'" in p for p in check_record.check("0.2.0", evals_dir))


def test_a_case_below_the_threshold_fails(evals_dir):
    failing = {"name": "bad", "arms": {"with": [{"graders": [{"passed": False}]}] * 3}}
    write_record(evals_dir, cases=[passing_case(), failing])
    problems = check_record.check("0.1.0", evals_dir)
    assert len(problems) == 1 and "bad" in problems[0]


def test_two_of_three_trials_meet_the_two_thirds_threshold_but_not_one(evals_dir):
    write_record(evals_dir, threshold=1.0)
    assert check_record.check("0.1.0", evals_dir)


def test_a_record_with_no_cases_fails(evals_dir):
    write_record(evals_dir, cases=[])
    assert "no cases" in check_record.check("0.1.0", evals_dir)[0]


def test_a_stale_record_fails_after_a_case_changes(evals_dir):
    write_record(evals_dir)
    (evals_dir / "live" / "yolo" / "case" / "prompt.md").write_text("---\nname: yolo-one-question\n---\nask differently\n", encoding="utf-8")
    assert any("stale" in p for p in check_record.check("0.1.0", evals_dir))


def test_results_under_live_do_not_change_the_suite_hash(evals_dir):
    before = check_record.suite_sha256(evals_dir)
    (evals_dir / "live" / "aggregate-result.json").write_text("{}", encoding="utf-8")
    assert check_record.suite_sha256(evals_dir) == before


def test_the_command_exits_non_zero_without_a_record():
    proc = subprocess.run([sys.executable, str(ROOT / "evals" / "check_record.py"), "9.9.9"],
                          capture_output=True, text=True)
    assert proc.returncode == 1 and "no live-eval record" in proc.stderr


def test_the_release_workflow_gates_publishing_on_the_checker():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers == {"push": {"tags": ["v*"]}}
    jobs = workflow["jobs"]
    gate, build, publish = jobs["gate"], jobs["build"], jobs["publish"]
    assert build["needs"] == "gate" and publish["needs"] == "build" and jobs["github-release"]["needs"] == "publish"
    assert "permissions" not in build  # the job that runs repo code holds no write token
    assert publish["permissions"] == {"id-token": "write"}
    assert "python evals/check_record.py" in "\n".join(s.get("run", "") for s in gate["steps"])
    assert publish["environment"] == "pypi"
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "pypa/gh-action-pypi-publish" in text and not re.search(r"secrets\.", text)


def test_ci_runs_the_replays_with_the_rest_of_the_tests():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python -m pytest" in ci
    assert 'testpaths = ["tests"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_a_record_goes_stale_when_a_skill_changes(evals_dir):
    skill = evals_dir.parent / "skills" / "simulate" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: simulate\n---\nrun rqh finalize\n", encoding="utf-8")
    write_record(evals_dir)
    assert check_record.check("0.1.0", evals_dir) == []
    skill.write_text("---\nname: simulate\n---\nrun rqh finalize and send the result\n", encoding="utf-8")
    assert any("stale" in p for p in check_record.check("0.1.0", evals_dir))


def test_bytecode_caches_do_not_change_the_hash(evals_dir):
    before = check_record.suite_sha256(evals_dir)
    cache = evals_dir.parent / "src" / "rqharness" / "__pycache__" / "x.cpython-313.pyc"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"\x00")
    assert check_record.suite_sha256(evals_dir) == before


def test_an_ungraded_trial_counts_as_failed(evals_dir):
    names = sorted(check_record.suite_case_names(evals_dir))
    cases = [{"name": n, "arms": {"with": [{"graders": []}, {"graders": []}, {"graders": []}]}} for n in names]
    write_record(evals_dir, cases=cases)
    assert any("scored 0.0" in p for p in check_record.check("0.1.0", evals_dir))


def test_a_record_from_a_failed_eval_run_fails(evals_dir):
    write_record(evals_dir, eval_exit_code=1)
    assert any("exited 1" in p for p in check_record.check("0.1.0", evals_dir))


def _all_cases(evals_dir, passed: list[bool]) -> list[dict]:
    trials = {"arms": {"with": [{"passed": p} for p in passed]}}
    return [{"name": n, **trials} for n in sorted(check_record.suite_case_names(evals_dir))]


@pytest.mark.parametrize("claimed", [0, 0.3])
def test_a_record_cannot_lower_its_own_bar(claimed, evals_dir):
    write_record(evals_dir, threshold=claimed, cases=_all_cases(evals_dir, [True, False, False]))
    problems = check_record.check("0.1.0", evals_dir)
    assert problems and all("below 0.66" in p for p in problems)


def test_a_record_can_raise_its_own_bar(evals_dir):
    write_record(evals_dir, threshold=0.9, cases=_all_cases(evals_dir, [True, True, False]))
    problems = check_record.check("0.1.0", evals_dir)
    assert problems and all("below 0.9" in p for p in problems)


@pytest.mark.parametrize("claimed", ["high", [1], True])
def test_a_non_numeric_threshold_is_a_problem_not_a_crash(claimed, evals_dir):
    write_record(evals_dir, threshold=claimed)
    assert any("is not a number" in p for p in check_record.check("0.1.0", evals_dir))


def test_run_live_uses_the_checker_threshold():
    import run_live

    assert run_live.THRESHOLD == check_record.THRESHOLD == 0.66


def _one_case(evals_dir, **fields) -> list[dict]:
    (name,) = check_record.suite_case_names(evals_dir)
    return [{"name": name, **fields}]


def test_the_pass_rate_comes_from_the_case_aggregates(evals_dir):
    # `claude plugin eval` reports `aggregates.passRate` (share of passing trials) beside
    # `aggregates.score` (mean share of graders passed); only the pass rate is "two of three".
    cases = _one_case(evals_dir, aggregates={"score": 0.9, "passRate": 1 / 3},
                      arms={"with": [{"passed": True}] * 3})
    write_record(evals_dir, cases=cases)
    assert any("scored 0.333" in p for p in check_record.check("0.1.0", evals_dir))


def test_the_mean_grader_score_never_stands_in_for_the_pass_rate(evals_dir):
    failed = {"with": [{"passed": False, "graders": [{"passed": True}, {"passed": True}, {"passed": False}]}] * 3}
    for fields in ({"aggregates": {"score": 0.67}, "arms": failed}, {"score": 1.0, "arms": failed}):
        write_record(evals_dir, cases=_one_case(evals_dir, **fields))
        assert any("scored 0.0" in p for p in check_record.check("0.1.0", evals_dir)), fields


def test_run_live_passes_scaffold_and_the_stubbed_search_flags(tmp_path):
    import run_live

    command = run_live.eval_command(tmp_path / "aggregate-result.json", "35")
    assert command[:4] == ["claude", "plugin", "eval", str(run_live.REPO)]
    for flag in ("--scaffold", "--trust-plugin", "--no-publish"):
        assert flag in command
    # Write and Edit are gated like Bash: without the grant every case runs with them withheld.
    assert command[command.index("--allow-tools") + 1:][:3] == ["Bash", "Write", "Edit"]
    assert command[command.index("--eval-dir") + 1] == "evals/live"
    assert command[command.index("--disallow-tools") + 1:][:2] == ["WebSearch", "WebFetch"]
    assert command[command.index("--max-cost-usd") + 1] == "35"
    assert command[command.index("--threshold") + 1] == str(check_record.THRESHOLD)
    # 84 runs one at a time is 2 to 3.5 hours; four at once share one rate limit.
    assert command[command.index("--concurrency") + 1] == "4"
    # The default judge (the background model) failed a correct one-question reply 6 of 6 votes,
    # reading its "Confirm, YOLO route" option as a claim; sonnet passed it 3/3 and still failed a
    # second question and a false "confirmed" claim 3/3 each (0.1.0 probe).
    assert command[command.index("--judge-model") + 1] == "sonnet"


def test_the_container_provides_the_linux_sandbox_backend():
    docker = ROOT / "evals" / "docker"
    dockerfile = (docker / "Dockerfile").read_text(encoding="utf-8")
    for package in ("bubblewrap", "socat", "python3-venv", "@anthropic-ai/claude-code@"):
        assert package in dockerfile, package
    assert re.search(r"^USER node$", dockerfile, re.MULTILINE)  # never run the agent as root
    service = yaml.safe_load((docker / "compose.yaml").read_text(encoding="utf-8"))["services"]["eval"]
    assert "seccomp=unconfined" in service["security_opt"]  # bubblewrap needs user namespaces
    assert "../..:/work" in service["volumes"]
    assert "TAVILY_API_KEY" not in yaml.dump(service)
    assert "evals/docker" in (ROOT / "evals" / "live" / "README.md").read_text(encoding="utf-8")


def test_the_container_keeps_run_folders_out_of_tmp_and_hides_the_host_venv():
    # The eval's Bash sandbox allows writes under the run's home but denies all of /tmp; on Linux
    # the deny wins, so a run folder under /tmp leaves the working directory read-only (0.1.0 smoke:
    # `rqh init` failed with EROFS). And the eval reads the whole plugin folder before each run;
    # over the Windows mount a host .venv (6,000 files) cost about 6 minutes per run.
    docker = ROOT / "evals" / "docker"
    dockerfile = (docker / "Dockerfile").read_text(encoding="utf-8")
    [tmpdir] = re.findall(r"TMPDIR=(\S+)", dockerfile)
    assert tmpdir.startswith("/") and not tmpdir.startswith(("/tmp", "/var/tmp", "/work"))
    assert re.search(rf"mkdir -p [^\n]*{re.escape(tmpdir)}", dockerfile)
    service = yaml.safe_load((docker / "compose.yaml").read_text(encoding="utf-8"))["services"]["eval"]
    assert "/work/.venv" in service["volumes"]


def test_run_live_refuses_native_windows(monkeypatch, capsys):
    import run_live

    monkeypatch.setattr(run_live.sys, "platform", "win32")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(run_live.subprocess, "run", lambda *a, **k: pytest.fail("ran claude on Windows"))
    assert run_live.main([]) == 2
    assert "evals/docker" in capsys.readouterr().err


def _auth_status(logged_in: bool):
    def run(args, *a, **k):
        if list(args[:3]) != ["claude", "auth", "status"]:
            pytest.fail(f"ran {args[:3]} before checking the login")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"loggedIn": logged_in}), stderr="")
    return run


def test_run_live_refuses_to_start_logged_out(monkeypatch, capsys):
    # A logged-out run fails every case with "Not logged in" after waiting out each one (28 minutes
    # for one YOLO case on the 0.1.0 smoke), so the runner checks before it launches anything.
    import run_live

    monkeypatch.setattr(run_live.sys, "platform", "linux")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(run_live.subprocess, "run", _auth_status(False))
    assert run_live.main([]) == 2
    assert "setup-token" in capsys.readouterr().err


def test_an_unreadable_auth_status_counts_as_logged_out(monkeypatch):
    import run_live

    monkeypatch.setattr(run_live.subprocess, "run",
                        lambda args, *a, **k: subprocess.CompletedProcess(args, 1, stdout="not json", stderr=""))
    assert run_live.logged_in() is False
    monkeypatch.setattr(run_live.subprocess, "run", _auth_status(True))
    assert run_live.logged_in() is True


def test_the_container_reads_the_login_token_from_outside_the_repository():
    docker = ROOT / "evals" / "docker"
    service = yaml.safe_load((docker / "compose.yaml").read_text(encoding="utf-8"))["services"]["eval"]
    [env_file] = service["env_file"]
    assert env_file["required"] is False  # the image still builds and runs without a token
    assert not env_file["path"].startswith(("..", ".", "/work"))  # never inside the mounted repo
    assert "setup-token" in (docker / "README.md").read_text(encoding="utf-8")


def test_run_live_keeps_each_run_trace_where_git_and_the_hash_ignore_it(tmp_path):
    # Four times on 0.1.0 a failed grader could not be explained because the run's trace was gone
    # with the container, so the runner keeps the temp dirs and copies each trace out.
    import run_live

    assert "--keep-temp" in run_live.eval_command(tmp_path / "r.json", "35")
    kept = tmp_path / "claude-eval-abc"
    (kept / "out").mkdir(parents=True)
    (kept / "out" / "trace.jsonl").write_text('{"type": "result"}\n', encoding="utf-8")
    result = {"cases": [{"name": "case-a", "arms": {"with": [
        {"tracePath": str(kept / "out" / "trace.jsonl")}, {"tracePath": str(tmp_path / "gone.jsonl")}, {}]}}]}
    dest = tmp_path / "traces"
    dest.mkdir()
    (dest / "stale-1.jsonl").write_text("old", encoding="utf-8")
    assert run_live.keep_traces(result, dest) == 1
    assert sorted(f.name for f in dest.iterdir()) == ["case-a-1.jsonl"]
    assert (dest / "case-a-1.jsonl").read_text(encoding="utf-8") == '{"type": "result"}\n'
    assert run_live.TRACES.relative_to(check_record.EVALS / "live" / "results")
    assert subprocess.run(["git", "check-ignore", "-q", str(run_live.TRACES / "x.jsonl")], cwd=ROOT).returncode == 0
