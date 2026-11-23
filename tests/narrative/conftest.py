"""A finalized sample run built through the real CLI, reusing the report tests' builder."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPORT_CONFTEST = Path(__file__).resolve().parents[1] / "report" / "conftest.py"
_spec = importlib.util.spec_from_file_location("report_conftest", _REPORT_CONFTEST)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)


@pytest.fixture
def make_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    return lambda: _module.build_run(tmp_path, route="yolo", n=2000, profile=True)
