from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import N, SEED, summarise
from rqharness import manifest, pert, summary

ROOT = Path(__file__).parents[2]
SAMPLE = ROOT / "tests" / "validate" / "fixtures" / "sample-run" / "inputs.yaml"
STATS = ["mean", "median", "p10", "p25", "p75", "p90", "p95", "p99"]


def test_summary_fields_and_currency(sample_summary, sample_doc):
    s = sample_summary
    assert list(s)[0] == "schema_version" and s["schema_version"] == "1"
    assert (s["currency"], s["n"], s["seed"], s["analysis_period_years"]) == ("USD", N, SEED, 1)
    ids = [v["id"] for v in s["variants"]]
    assert ids[0] == "baseline" and len(ids) == 1 + len(sample_doc["variants"])
    assert s["variants"][0]["label"] == "Current controls"
    for v in s["variants"]:
        assert set(v["annual_loss"]) == {"currency", *STATS}
        assert 0 <= v["p_annual_loss_gt_0"] <= 1
        for k in ("lef", "event_count"):
            assert set(v[k]) == {"mean", "median", "p90"}
        assert len(v["lec"]["points"]) <= 200
        ps = [p for _, p in v["lec"]["points"]]
        assert all(a >= b for a, b in zip(ps, ps[1:]))
        h = v["histogram"]
        assert len(h["counts"]) == 60 and len(h["edges"]) == 61
        assert sum(h["counts"]) + h["above"] == N
    assert s["sensitivity_fallback"] is False
    assert s["parameters"][0]["path"] == "frequency.tef"
    p0 = s["parameters"][0]
    assert {"label", "min", "mode", "max", "unit", "tier", "source_ids", "contribution"} <= set(p0)
    assert p0["tier"] == "internal_data" and p0["label"].startswith("Phishing")
    assert sum(p["contribution"] for p in s["parameters"]) == pytest.approx(1.0, abs=1e-12)


def test_currency_on_every_amount(sample_summary):
    seen = 0
    for v in sample_summary["variants"]:
        for key in ("annual_loss", "annual_cost", "lec", "histogram"):
            if v[key] is not None:
                assert v[key]["currency"] == "USD"
                seen += 1
    assert seen >= 4 * len(sample_summary["variants"]) - 1
    assert all(d["currency"] == "USD" for d in sample_summary["deltas"])


def test_return_on_control(sample_summary):
    by = {v["id"]: v for v in sample_summary["variants"]}
    base = by["baseline"]["annual_loss"]
    assert by["baseline"]["annual_cost"] is None
    assert len(sample_summary["deltas"]) == len(by) - 1
    for d in sample_summary["deltas"]:
        v = by[d["variant"]]
        red = base["mean"] - v["annual_loss"]["mean"]
        assert d["ale_reduction_mean"] == red
        assert d["ale_reduction_p90"] == base["p90"] - v["annual_loss"]["p90"]
        cost = v["annual_cost"]
        if cost is None:
            assert d["return_on_control"] is None
        else:
            assert d["return_on_control"] == (red - cost["mean"]) / cost["mean"]
    mfa = by["mfa"]["annual_cost"]
    assert mfa["mean"] == pytest.approx(120_000)
    assert mfa["mean"] == pytest.approx((mfa["min"] + 4 * mfa["mode"] + mfa["max"]) / 6)


def test_roc_null_without_cost(sample_doc):
    doc = copy.deepcopy(sample_doc)
    for v in doc["variants"]:
        v.pop("annual_cost", None)
    s = summarise(doc, n=2000)
    assert all(d["return_on_control"] is None for d in s["deltas"])
    assert all(v["annual_cost"] is None for v in s["variants"])


def test_summary_byte_identical(sample_doc, sample_summary):
    text = summary.dumps(sample_summary)
    assert summary.dumps(summarise(sample_doc)) == text
    assert text.endswith("\n") and json.loads(text)["schema_version"] == "1"
    code = (
        "import sys,yaml;sys.path.insert(0,'tests/summary');"
        "from conftest import summarise;from rqharness import summary;"
        f"d=yaml.safe_load(open(r'{SAMPLE}',encoding='utf-8'));"
        "sys.stdout.buffer.write(summary.dumps(summarise(d)).encode('utf-8'))"
    )
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, check=True).stdout
    assert out.decode("utf-8") == text


def test_manifest(tmp_path):
    f = tmp_path / "a.yaml"
    f.write_bytes(b"abc")
    sha = manifest.sha256_file(f)
    assert sha == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    m = manifest.build_manifest(
        scenario_id="s", version=2, n=10, seed=3, inputs_sha256=sha, generated_at="2026-01-01T00:00:00Z",
        route="yolo",
    )
    from rqharness import __version__

    assert m["schema_version"] == "1" and m["package_version"] == __version__
    assert (m["scenario_id"], m["version"], m["n"], m["seed"]) == ("s", 2, 10, 3)
    assert m["pert_method"] == pert.PERT_METHOD and m["pert_parameterization"] == "beta_pert_gamma_4"
    assert m["secondary_loss_rule_version"] == "v1_poisson_per_primary"
    assert m["stream_rule"].startswith("philox4x32-10; key=blake2b(name)[0:16]")
    for k in ("numpy_version", "scipy_version", "python_version", "platform"):
        assert m[k]
    assert m["inputs_sha256"] == sha and m["generated_at"] == "2026-01-01T00:00:00Z"
    assert json.loads(manifest.dumps(m)) == m and manifest.dumps(m).endswith("\n")
