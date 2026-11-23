"""AC32: the launch kit (examples, workflows, community docs) is present and working."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

from rqharness import cli

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "credential-phishing-bec"
WORKFLOWS = ROOT / ".github" / "workflows"

LAUNCH_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    ".github/CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE/benchmark_entry.md",
    ".github/workflows/pages.yml",
    ".github/workflows/linkcheck.yml",
    "examples/credential-phishing-bec/README.md",
    "examples/credential-phishing-bec/scenario.yaml",
    "examples/credential-phishing-bec/inputs.yaml",
    "examples/credential-phishing-bec/org-profile.yaml",
]


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _step(workflow: dict, fragment: str) -> dict:
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            if fragment in step.get("name", ""):
                return step
    raise AssertionError(f"no step named like {fragment!r}")


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash not available")
    return found


def test_launch_files_present():
    for rel in LAUNCH_FILES:
        path = ROOT / rel
        assert path.is_file() and path.stat().st_size > 0, rel
    template = (ROOT / LAUNCH_FILES[5]).read_text(encoding="utf-8").lower()
    for needle in ("https://", "citation", "applicability", "rqh library validate", "linkcheck"):
        assert needle in template, needle
    assert "* @Joaovsales" in (ROOT / ".github/CODEOWNERS").read_text(encoding="utf-8")
    assert "private vulnerability reporting" in (ROOT / "SECURITY.md").read_text(encoding="utf-8").lower()


def test_example_matches_fixtures():
    for name, src in (
        ("scenario.yaml", ROOT / "tests/validate/fixtures/sample-run/scenario.yaml"),
        ("inputs.yaml", ROOT / "tests/validate/fixtures/sample-run/inputs.yaml"),
        ("org-profile.yaml", ROOT / "tests/routing/fixtures/org-profile.yaml"),
    ):
        assert (EXAMPLE / name).read_bytes() == src.read_bytes(), name
    assert not list(EXAMPLE.glob("*.html"))


def test_pages_workflow_builds_sample(tmp_path):
    workflow = _workflow("pages.yml")
    triggers = _triggers(workflow)
    assert "workflow_dispatch" in triggers and triggers["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}  # the build job runs repo code: no write token
    deploy = workflow["jobs"]["deploy"]["permissions"]
    assert deploy["pages"] == "write" and deploy["id-token"] == "write"
    text = (WORKFLOWS / "pages.yml").read_text(encoding="utf-8")
    assert "actions/upload-pages-artifact@" in text and "actions/deploy-pages@" in text
    assert "github-pages" in text

    build = _step(workflow, "Build the sample report")["run"]
    for needle in ("examples/credential-phishing-bec", "finalize", "report", "sample-report.html", "index.html"):
        assert needle in build, needle

    site = tmp_path / "site"
    shim = tmp_path / "bin" / "rqh"
    shim.parent.mkdir()
    shim.write_bytes(f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" -m rqharness "$@"\n'.encode())
    shim.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{shim.parent.as_posix()}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT / "src"),
        "RQH": "rqh",
        "N": "2000",
        "REPO_DIR": ROOT.as_posix(),
        "SITE_DIR": site.as_posix(),
        "WORK_DIR": (tmp_path / "work").as_posix(),
    }
    done = subprocess.run([_bash(), "-e", "-c", build], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    for name in ("index.html", "sample-report.html"):
        assert "<html" in (site / name).read_text(encoding="utf-8").lower()


def test_linkcheck_scans_benchmarks(tmp_path):
    workflow = _workflow("linkcheck.yml")
    triggers = _triggers(workflow)
    cron = triggers["schedule"][0]["cron"].split()
    assert len(cron) == 5 and cron[4] != "*"  # weekly: a fixed weekday
    assert "workflow_dispatch" in triggers

    extract = _step(workflow, "Extract benchmark URLs")["run"]
    out = tmp_path / "urls.txt"
    script = tmp_path / "extract.py"
    script.write_text(extract.split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0], encoding="utf-8")
    env = {**os.environ, "URLS_FILE": str(out)}
    done = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, cwd=ROOT)
    assert done.returncode == 0, done.stdout + done.stderr
    found = out.read_text(encoding="utf-8").split()

    entries = sorted((ROOT / "src/rqharness/data/benchmarks").rglob("*.yaml"))
    expected = [yaml.safe_load(p.read_text(encoding="utf-8"))["source"]["url"] for p in entries]
    assert len(expected) == 18
    assert sorted(found) == sorted(set(expected))
    assert all(u.startswith("https://") for u in found)
    assert "urllib" in _step(workflow, "Check every URL")["run"]


def test_readme_commands_exist():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    parser = cli.build_parser()
    action = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
    commands = set(action.choices)
    pattern = r"^\s*rqh (\w[\w-]*)"
    used = set(re.findall(pattern, readme, re.M))
    used |= set(re.findall(pattern, (EXAMPLE / "README.md").read_text(encoding="utf-8"), re.M))
    assert {"init", "run", "finalize", "report"} <= used
    assert used <= commands, used - commands
    for name in commands:
        assert re.search(rf"^\s+{name}\s", readme, re.M), name


# Words that must not appear, kept as SHA-256 digests of the lowercased word so this file does
# not spell them out: names that do not belong in a public repo, and the retired estimate wording.
_NAME_DIGESTS = {
    "6237df484bdcdce15759bb1e56e989fb3f090c854844e7d6fa601dabca586c1d": 8,
    "3f145ac104cd7a5e0c4b982195480305b4d1085e58f3556dc21aba06c444b28b": 9,
    "76cd21db00b2a3eee39dff599ad245a3c5088395388942fde3d2363da968bc1a": 8,
    "2ee9347bd0596e010218b2aaa7fb8a05fc7cb10fec1d669ee7284649cc7a97ad": 19,
}
_WORDING_DIGESTS = {"712985cc1194dffe8b30127444e0c92fe214420a84a5b2d28abe6684f4540409": 4}
_TOKEN = re.compile(r"\w+")


def _digest_hits(text: str, digests: dict[str, int]) -> set[str]:
    """Digests of every window of a banned word's length, inside a word token, that match."""
    lengths = set(digests.values())
    hits: set[str] = set()
    for token in set(_TOKEN.findall(text.lower())):
        for n in lengths:
            for i in range(len(token) - n + 1):
                digest = hashlib.sha256(token[i : i + n].encode("utf-8")).hexdigest()
                if digest in digests:
                    hits.add(digest)
    return hits


def _exported_paths() -> list[str]:
    """Tracked paths `git archive` would ship, honouring the working tree's .gitattributes."""
    if not (ROOT / ".git").exists() or shutil.which("git") is None:
        pytest.skip("needs a git checkout")
    archive = subprocess.run(
        ["git", "archive", "--worktree-attributes", "HEAD"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        return [m.name for m in tar.getmembers() if m.isfile()]


def test_privacy_scan():
    banned = re.compile(r"\.claude/worktrees|C:\\Users", re.I)
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for rel in LAUNCH_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not banned.search(text), rel
        assert not _digest_hits(text, _NAME_DIGESTS | _WORDING_DIGESTS), rel
        assert not email.search(text), rel


def test_conduct_reports_go_to_the_private_channel_only():
    """Discussions is off for the repository, so the code of conduct must not offer it."""
    text = (ROOT / "CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
    enforcement = " ".join(text.split("## Enforcement\n", 1)[1].split("\n## ", 1)[0].split())
    assert "Report a vulnerability" in enforcement
    assert "discussion" not in enforcement.lower()


def test_export_leaves_out_session_bookkeeping():
    paths = _exported_paths()
    assert "README.md" in paths
    assert not [p for p in paths if p.startswith("tasks/")]


def test_no_exported_file_names_what_must_stay_private():
    for rel in _exported_paths():
        path = ROOT / rel
        if not path.is_file():  # deleted in the working tree since HEAD
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore")
        assert not _digest_hits(text, _NAME_DIGESTS), rel


def test_every_action_is_pinned_to_a_commit_sha():
    """A moved tag must not run new code with the release or Pages tokens (quality gate, 2026-11-11)."""
    import re

    for workflow in sorted(WORKFLOWS.glob("*.yml")):
        for ref in re.findall(r"uses:\s*(\S+)", workflow.read_text(encoding="utf-8")):
            assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), f"{workflow.name}: {ref}"
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" in line:  # the tag comment is what Dependabot bumps and a reader recognises
                assert re.search(r"@[0-9a-f]{40}\s+#\s*v\d", line), f"{workflow.name}: {line.strip()}"


def test_dependabot_keeps_the_action_pins_current():
    config = yaml.safe_load((WORKFLOWS.parent / "dependabot.yml").read_text(encoding="utf-8"))
    assert any(u["package-ecosystem"] == "github-actions" for u in config["updates"])


def test_pages_publishes_every_schema_at_its_id(tmp_path):
    """Each schema `$id` resolves once Pages deploys: the site holds the schema under `schemas/`."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    base = re.search(r"\[See a sample report\]\((https://[^)]+/)\)", readme).group(1)
    schemas = sorted((ROOT / "src" / "rqharness" / "schemas").glob("*.v1.json"))
    assert schemas
    for path in schemas:
        assert json.loads(path.read_text(encoding="utf-8"))["$id"] == f"{base}schemas/{path.name}", path.name

    publish = _step(_workflow("pages.yml"), "Publish the schemas")["run"]
    site = tmp_path / "site"
    env = {**os.environ, "REPO_DIR": ROOT.as_posix(), "SITE_DIR": site.as_posix()}
    done = subprocess.run([_bash(), "-e", "-c", publish], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert sorted(p.name for p in (site / "schemas").iterdir()) == [p.name for p in schemas]
    for path in schemas:
        assert (site / "schemas" / path.name).read_bytes() == path.read_bytes(), path.name
