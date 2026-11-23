"""One readiness rule ("both documents present, and the run validates") and one missing-document issue."""

from __future__ import annotations

import dataclasses
import re
import shutil
from pathlib import Path

import pytest

from rqharness import cli, model, validate, workspace
from rqharness.outcomes import Rejected
from rqharness.validate import ReadyRun, ValidationReport, missing_document, validate_run

SAMPLE = Path(__file__).parent / "fixtures" / "sample-run"
SAMPLE_ID = "credential-phishing-bec"
SRC = Path(validate.__file__).parent


@pytest.fixture
def sample_run(tmp_path, monkeypatch) -> workspace.Run:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(cli.WORKSPACE_ENV, raising=False)
    ws = tmp_path / ".riskquant"
    shutil.copytree(SAMPLE, ws / "runs" / SAMPLE_ID)
    return workspace.Run(ws, ws / "runs" / SAMPLE_ID)


def refusal(report: ValidationReport) -> list[dict]:
    """The issues ready() raises, which are the report's readiness_issues."""
    with pytest.raises(Rejected) as refused:
        report.ready()
    assert refused.value.issues == report.readiness_issues
    return refused.value.issues


def test_missing_document_names_the_file_and_the_run_directory(tmp_path):
    assert missing_document(tmp_path / "inputs.yaml") == {
        "path": "inputs.document", "rule": "missing", "message": f"inputs.yaml is missing from {tmp_path}"}
    assert missing_document(tmp_path / "scenario.yaml")["message"] == f"scenario.yaml is missing from {tmp_path}"


def test_a_valid_run_is_ready_with_every_document_it_validated(sample_run):
    report = validate_run(sample_run)
    ready = report.ready()
    assert isinstance(ready, ReadyRun) and report.readiness_issues == []
    assert ready.scenario_bytes == report.contents.scenario == (sample_run.dir / "scenario.yaml").read_bytes()
    assert ready.inputs_bytes == report.contents.inputs == (sample_run.dir / "inputs.yaml").read_bytes()
    assert ready.inputs == report.inputs
    assert isinstance(ready.inputs_model, model.ModelInputs)
    assert ready.inputs_model is ready.inputs_model, "loaded once"


def test_a_run_without_inputs_validates_but_is_not_ready(sample_run):
    """`rqh validate` stays lenient about a run still collecting its inputs; readiness is not."""
    (sample_run.dir / "inputs.yaml").unlink()
    report = validate_run(sample_run)
    assert report.ok
    assert refusal(report) == [missing_document(sample_run.dir / "inputs.yaml")]


def test_a_run_missing_both_documents_names_both_scenario_first(sample_run):
    for name in ("scenario.yaml", "inputs.yaml"):
        (sample_run.dir / name).unlink()
    assert refusal(validate_run(sample_run)) == [missing_document(sample_run.dir / "scenario.yaml"),
                                                 missing_document(sample_run.dir / "inputs.yaml")]


def test_an_invalid_run_is_not_ready_and_names_every_issue(sample_run):
    text = (sample_run.dir / "inputs.yaml").read_text(encoding="utf-8")
    (sample_run.dir / "inputs.yaml").write_text(text.replace(f"scenario_id: {SAMPLE_ID}", "scenario_id: other"),
                                                encoding="utf-8")
    report = validate_run(sample_run)
    assert not report.ok
    assert refusal(report) == report.issues


def test_only_a_ready_run_carries_a_model():
    """The model lives on ReadyRun, whose fields cannot be None, so no caller can ask an unready report for one."""
    assert not hasattr(ValidationReport, "inputs_model")


def test_the_missing_document_issue_is_built_in_one_place():
    spelled = {path.relative_to(SRC).as_posix(): len(re.findall(r"is missing from", path.read_text(encoding="utf-8")))
               for path in SRC.rglob("*.py")}
    assert {path: count for path, count in spelled.items() if count} == {"validate.py": 1}


def test_a_report_cannot_say_not_ready_without_a_reason(sample_run):
    """An empty list of reasons would let `rqh status` say simulate while `rqh finalize` rejects."""
    with pytest.raises(ValueError):
        dataclasses.replace(validate_run(sample_run), readiness=[])
