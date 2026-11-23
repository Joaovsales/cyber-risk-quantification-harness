"""Supply-chain hygiene for the public repository: dependency floors, update bots and pinned images."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GITHUB = ROOT / ".github"
DOCKER = ROOT / "evals" / "docker"


def _workflow_steps():
    for workflow in sorted((GITHUB / "workflows").glob("*.yml")):
        config = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in config["jobs"].values():
            for step in job.get("steps", []):
                yield workflow.name, step


def _version(spec: str) -> tuple[int, ...]:
    return tuple(int(part) for part in spec.split("."))


def test_dependabot_watches_every_ecosystem_weekly():
    updates = yaml.safe_load((GITHUB / "dependabot.yml").read_text(encoding="utf-8"))["updates"]
    watched = {(u["package-ecosystem"], u["directory"]) for u in updates}
    assert {("github-actions", "/"), ("pip", "/"), ("docker", "/evals/docker")} <= watched
    assert all(u["schedule"]["interval"] == "weekly" for u in updates)


def test_runtime_floors_exclude_known_vulnerable_releases():
    """Jinja2 below 3.1.6 carries five advisories; MarkupSafe is imported directly by the report."""
    dependencies = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
    floors = {}
    for dependency in dependencies:
        match = re.fullmatch(r"(?P<name>[\w.-]+)>=(?P<floor>[\d.]+)", dependency)
        assert match, dependency
        floors[match["name"].lower()] = _version(match["floor"])
    assert floors["jinja2"] >= (3, 1, 6)
    assert floors["markupsafe"] >= (2, 1)


def test_checkout_never_persists_the_token():
    checkouts = [(name, step) for name, step in _workflow_steps() if step.get("uses", "").startswith("actions/checkout@")]
    assert checkouts
    for name, step in checkouts:
        assert step.get("with", {}).get("persist-credentials") is False, name


def test_pages_upload_is_on_a_major_that_pins_its_own_actions():
    """v3 calls actions/upload-artifact by tag; from v4 the inner action is pinned to a SHA."""
    text = (GITHUB / "workflows" / "pages.yml").read_text(encoding="utf-8")
    match = re.search(r"uses:\s*actions/upload-pages-artifact@[0-9a-f]{40}\s+#\s*v(\d+)", text)
    assert match
    assert int(match[1]) >= 4


def test_eval_base_image_is_pinned_by_digest():
    """The tag stays beside the digest: Dependabot follows the tag and bumps the digest with it."""
    images = re.findall(r"^FROM\s+(\S+)", (DOCKER / "Dockerfile").read_text(encoding="utf-8"), re.M)
    assert images
    for image in images:
        assert re.fullmatch(r"[\w./-]+:[\w.-]+@sha256:[0-9a-f]{64}", image), image


def test_eval_container_explains_the_unconfined_profiles():
    text = (DOCKER / "compose.yaml").read_text(encoding="utf-8")
    head = text[: text.index("security_opt:")]
    comment = " ".join(line.strip().lstrip("#").strip() for line in head.splitlines()[-6:] if line.strip().startswith("#"))
    assert "user namespaces" in comment
    assert re.search(r"\bdev(elopment)?[- ]only\b", comment, re.I), comment
