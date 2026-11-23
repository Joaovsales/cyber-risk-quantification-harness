"""Drive `rqh` through a recorded route sequence, following `next_skill` between phases.

The recorded sequence lives in `evals/replays/<route>/steps.yaml`. The driver does what the
router skill does: run `rqh status`, check which skill it names, run the recorded step for that
skill, and ask `rqh status` again. No network and no Claude are involved.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPLAYS = ROOT / "evals" / "replays"
RUN_ID = "credential-phishing-bec"
_VERIFY = ROOT / ".agents" / "skills" / "verify-rqh" / "scripts" / "verify.py"


def load_verify():
    """The report checks verify-rqh uses (CSP, section order, size, no external references)."""
    spec = importlib.util.spec_from_file_location("verify_rqh", _VERIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Replay:
    def __init__(self, route: str, workspace: Path) -> None:
        self.fixtures = REPLAYS / route
        self.script = yaml.safe_load((self.fixtures / "steps.yaml").read_text(encoding="utf-8"))
        self.cwd = workspace
        self.run_dir = workspace / ".riskquant" / "runs" / RUN_ID
        self.seen: list[tuple[str | None, list[str]]] = []
        self.rqh(["init"])
        self.run_dir.mkdir(parents=True)

    def rqh(self, args: list[str], *, expect: int = 0) -> dict:
        env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
        env.pop("RQH_WORKSPACE", None)
        proc = subprocess.run([sys.executable, "-m", "rqharness", *args, "--json"], cwd=self.cwd, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=120)
        assert proc.returncode == expect, f"rqh {args}: exit {proc.returncode}, wanted {expect}\n{proc.stdout}{proc.stderr}"
        return json.loads(proc.stdout)

    def status(self) -> dict:
        data = self.rqh(["status", RUN_ID])["data"]
        self.seen.append((data["next_skill"], data["waiting_on"]))
        return data

    def _fill(self, value: object) -> str:
        setup = self.script["setup"]
        return str(value).format(run=RUN_ID, run_dir=self.run_dir, n=setup["n"], seed=setup["seed"])

    def _ops(self, ops: list[dict]) -> None:
        for op in ops:
            if "install" in op:
                spec = op["install"]
                base = self.run_dir if spec["to"] == "run" else self.cwd / ".riskquant"
                shutil.copyfile(self.fixtures / spec["from"], base / spec.get("as", Path(spec["from"]).name))
            else:
                self.rqh([self._fill(a) for a in op["rqh"]], expect=op.get("exit", 0))

    def follow(self, phases: list[dict]) -> dict:
        """Run each recorded phase when `rqh status` names it; fail when status names another."""
        for phase in phases:
            data = self.status()
            assert data["next_skill"] == phase["skill"], (
                f"status named {data['next_skill']!r} ({data['reason']}), the recording runs {phase['skill']!r}")
            if "waiting_on" in phase:
                assert data["waiting_on"] == phase["waiting_on"]
            self._ops(phase["ops"])
        return self.status()

    def run_ops(self, ops: list[dict]) -> None:
        self._ops(ops)

    def report_path(self, version: int) -> Path:
        return self.run_dir / f"v{version}" / "report.html"
