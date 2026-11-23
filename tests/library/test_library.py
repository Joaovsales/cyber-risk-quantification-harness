"""Slice 10: the memory library, search (AC16) and add (AC17)."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from rqharness import cli, library
from rqharness.library import Added, Duplicate, LibraryQuery
from rqharness.outcomes import NotFound, Rejected

FIXTURE = yaml.safe_load((Path(__file__).parent / "fixtures" / "entry.yaml").read_text(encoding="utf-8"))
TODAY = date(2025, 6, 1)


def make(entry_id, **over):
    entry = copy.deepcopy(FIXTURE)
    entry["entry_id"] = entry_id
    entry.update(over)
    return entry


def put(directory: Path, entry: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{entry['entry_id']}.yaml").write_text(yaml.safe_dump(entry, sort_keys=False), encoding="utf-8")


@pytest.fixture
def ws(tmp_path):
    (tmp_path / "ws" / "library").mkdir(parents=True)
    return tmp_path / "ws"


@pytest.fixture
def shipped(tmp_path, monkeypatch):
    directory = tmp_path / "shipped"
    directory.mkdir()
    monkeypatch.setattr(library, "shipped_dir", lambda: directory)
    return directory


Q = LibraryQuery(parameter_family="primary_loss.response")


def ids(hits):
    return [h.entry["entry_id"] for h in hits]


def test_memory_before_benchmark(ws, shipped):
    put(shipped / "ransomware", make("bench-new", tier="benchmark", period={"start": "2025-01-01", "end": "2025-05-31"}))
    put(ws / "library", make("mem-old", period={"start": "2020-01-01", "end": "2020-12-31"}))
    hits = library.search(Q, workspace=ws, today=TODAY)
    assert ids(hits) == ["mem-old", "bench-new"]
    assert [h.origin for h in hits] == ["memory", "benchmark"]


def test_order_segment_then_recency_then_id(ws, shipped):
    put(ws / "library", make("b-any", segment={"industry": "any", "size_band": "any"}))
    put(ws / "library", make("c-exact", segment={"industry": "retail", "size_band": "mid_market"},
                             period={"start": "2020-01-01", "end": "2020-12-31"}))
    put(ws / "library", make("a-newer", segment={"industry": "any", "size_band": "any"},
                             period={"start": "2025-01-01", "end": "2025-03-31"}))
    put(ws / "library", make("a-tie", segment={"industry": "any", "size_band": "any"},
                             period={"start": "2025-01-01", "end": "2025-03-31"}))
    q = LibraryQuery("primary_loss.response", industry="retail", size_band="mid_market")
    hits = library.search(q, workspace=ws, today=TODAY)
    assert ids(hits) == ["c-exact", "a-newer", "a-tie", "b-any"]
    assert [h.segment_match for h in hits] == [2, 0, 0, 0]


def test_segment_filter(ws, shipped):
    put(ws / "library", make("m-retail", segment={"industry": "retail", "size_band": "smb"}))
    put(ws / "library", make("m-health", segment={"industry": "healthcare", "size_band": "smb"}))
    put(ws / "library", make("m-any", segment={"industry": "any", "size_band": "any"}))
    put(ws / "library", make("m-ent", segment={"industry": "retail", "size_band": "enterprise"}))
    hits = library.search(LibraryQuery("primary_loss.response", industry="retail", size_band="smb"), workspace=ws, today=TODAY)
    assert ids(hits) == ["m-retail", "m-any"]
    assert [h.segment_match for h in hits] == [2, 0]
    assert len(library.search(Q, workspace=ws, today=TODAY)) == 4


def test_family_and_scenario_filter(ws, shipped):
    put(ws / "library", make("m-other-family", parameter_family="frequency.lef",
                             value={"min": 1, "mode": 2, "max": 3, "unit": "events/year"}))
    put(ws / "library", make("m-ddos", scenario_tags=["ddos"]))
    put(ws / "library", make("m-bec"))
    hits = library.search(LibraryQuery("primary_loss.response", scenario_type="business_email_compromise"),
                          workspace=ws, today=TODAY)
    assert ids(hits) == ["m-bec"]


def test_stale_flag(ws, shipped):
    put(ws / "library", make("m-fresh", period={"start": "2024-01-01", "end": "2024-12-31"}))
    put(ws / "library", make("m-stale", period={"start": "2022-01-01", "end": "2023-11-30"}))
    put(ws / "library", make("m-short", period={"start": "2024-06-01", "end": "2024-12-31"}, stale_after_months=3))
    stale = {h.entry["entry_id"]: h.stale for h in library.search(Q, workspace=ws, today=TODAY)}
    assert stale == {"m-fresh": False, "m-stale": True, "m-short": True}


def test_currency_mismatch(ws, shipped):
    put(ws / "library", make("m-usd"))
    put(ws / "library", make("m-eur", value={"min": 1, "mode": 2, "max": 3, "unit": "EUR"}))
    got = {h.entry["entry_id"]: h.currency_mismatch
           for h in library.search(LibraryQuery("primary_loss.response", currency="USD"), workspace=ws, today=TODAY)}
    assert got == {"m-usd": False, "m-eur": True}
    none = library.search(Q, workspace=ws, today=TODAY)
    assert not any(h.currency_mismatch for h in none)


def test_rate_unit_is_not_a_currency_mismatch(ws, shipped):
    put(ws / "library", make("m-rate", parameter_family="frequency.lef",
                             value={"min": 1, "mode": 2, "max": 3, "unit": "events/year"}))
    hits = library.search(LibraryQuery("frequency.lef", currency="USD"), workspace=ws, today=TODAY)
    assert [h.currency_mismatch for h in hits] == [False]


def test_search_tolerates_missing_dirs_and_invalid_files(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "shipped_dir", lambda: tmp_path / "nope")
    assert library.search(Q, workspace=None, today=TODAY) == []
    ws = tmp_path / "ws"
    put(ws / "library", make("good"))
    (ws / "library" / "bad.yaml").write_text("entry_id: [", encoding="utf-8")
    put(ws / "library", {"entry_id": "invalid"})
    assert ids(library.search(Q, workspace=ws, today=TODAY)) == ["good"]


def test_add_writes_and_round_trips(ws, shipped):
    result = library.add(make("mem-new"), workspace=ws)
    assert isinstance(result, Added)
    assert result.path == ws / "library" / "mem-new.yaml"
    assert yaml.safe_load(result.path.read_text(encoding="utf-8")) == make("mem-new")
    assert not list((ws / "library").glob(".*.tmp"))


def test_add_rejects_missing_sensitivity_and_long_note(ws, shipped):
    no_sens = make("mem-a")
    del no_sens["sensitivity"]
    with pytest.raises(Rejected) as exc:
        library.add(no_sens, workspace=ws)
    result = exc.value
    assert any(i["rule"] == "required" and i["path"] == "entry.sensitivity" for i in result.issues)
    with pytest.raises(Rejected) as exc:
        library.add(make("mem-b", note="x" * 501), workspace=ws)
    long_note = exc.value
    assert any(i["rule"] == "maxLength" and i["path"] == "entry.note" for i in long_note.issues)
    assert isinstance(library.add(make("mem-c", note="x" * 500), workspace=ws), Added)
    assert sorted(p.name for p in (ws / "library").iterdir()) == ["mem-c.yaml"]


def test_add_rejects_unordered_value(ws, shipped):
    with pytest.raises(Rejected) as exc:
        library.add(make("mem-d", value={"min": 5, "mode": 3, "max": 9, "unit": "USD"}), workspace=ws)
    assert [i["rule"] for i in exc.value.issues] == ["pert_order"]
    assert not (ws / "library" / "mem-d.yaml").exists()


def test_add_never_writes_shipped(shipped):
    put(shipped / "ransomware", make("bench-one", tier="benchmark"))
    before = sorted((p.relative_to(shipped), p.read_bytes()) for p in shipped.rglob("*") if p.is_file())
    for workspace in (shipped, shipped / "ransomware"):
        with pytest.raises(Rejected) as exc:
            library.add(make("mem-x"), workspace=workspace)
        assert exc.value.issues[0]["rule"] == "shipped_data"
    after = sorted((p.relative_to(shipped), p.read_bytes()) for p in shipped.rglob("*") if p.is_file())
    assert before == after
    assert not (shipped / "library").exists()


def test_add_never_writes_into_package_root(shipped):
    root = Path(library.__file__).parent
    with pytest.raises(Rejected) as exc:
        library.add(make("mem-y"), workspace=root / "scratch-ws")
    assert exc.value.issues[0]["rule"] == "shipped_data"
    assert not (root / "scratch-ws").exists()


def test_add_duplicate(ws, shipped):
    assert isinstance(library.add(make("mem-dup"), workspace=ws), Added)
    path = ws / "library" / "mem-dup.yaml"
    stamp = path.stat().st_mtime_ns
    assert isinstance(library.add(make("mem-dup"), workspace=ws), Duplicate)
    assert path.stat().st_mtime_ns == stamp
    with pytest.raises(Rejected) as exc:
        library.add(make("mem-dup", sensitivity="public"), workspace=ws)
    assert exc.value.issues[0]["rule"] == "entry_id_conflict"


def test_content_hash_is_canonical():
    a = {"b": 1, "a": [1, 2]}
    expected = hashlib.sha256(json.dumps(a, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert library.content_hash(a) == expected
    assert library.content_hash({"a": [1, 2], "b": 1}) == expected


def test_remove_and_validate_all(ws, shipped):
    library.add(make("mem-r"), workspace=ws)
    (ws / "library" / "broken.yaml").write_text(yaml.safe_dump({"entry_id": "broken"}), encoding="utf-8")
    issues = library.validate_all(workspace=ws)
    assert issues and all(i["path"].startswith("library.broken.") for i in issues)
    library.remove("mem-r", workspace=ws)
    with pytest.raises(NotFound):
        library.remove("mem-r", workspace=ws)


def test_validate_all_reaches_subfolders(ws, shipped):
    (ws / "library" / "team-a").mkdir()
    (ws / "library" / "team-a" / "broken.yaml").write_text(yaml.safe_dump({"entry_id": "broken"}), encoding="utf-8")
    issues = library.validate_all(workspace=ws)
    assert issues and all(i["path"].startswith("library.team-a/broken.") for i in issues)  # names the file


def test_remove_finds_the_entry_search_shows(ws, shipped):
    put(ws / "library" / "team-a", make("nested"))
    (ws / "library" / "other-name.yaml").write_text(yaml.safe_dump(make("real-id")), encoding="utf-8")
    library.remove("nested", workspace=ws)  # in a subfolder
    library.remove("real-id", workspace=ws)  # known by the id inside the file
    assert not list((ws / "library").rglob("*.yaml"))
    (ws / "library" / "broken.yaml").write_text("tier: [unclosed\n", encoding="utf-8")
    library.remove("broken", workspace=ws)  # no id inside: known by its file name
    assert not list((ws / "library").rglob("*.yaml"))


def test_one_id_in_two_files_is_an_issue_and_nothing_guesses(ws, shipped):
    put(ws / "library", make("twin"))
    put(ws / "library" / "team-a", make("twin", sensitivity="public"))
    issues = library.validate_all(workspace=ws)
    assert [(i["path"], i["rule"]) for i in issues] == [("library.twin.entry_id", "duplicate_entry_id")]
    assert "team-a/twin.yaml" in issues[0]["message"] and "'twin.yaml'" in issues[0]["message"]
    for act in (lambda: library.remove("twin", workspace=ws), lambda: library.add(make("twin"), workspace=ws)):
        with pytest.raises(Rejected) as exc:
            act()
        assert exc.value.issues == issues
    assert len(list((ws / "library").rglob("twin.yaml"))) == 2


def test_add_sees_an_id_held_in_a_subfolder(ws, shipped):
    put(ws / "library" / "team-a", make("nested"))
    assert library.add(make("nested"), workspace=ws) == Duplicate(ws / "library" / "team-a" / "nested.yaml")
    with pytest.raises(Rejected) as exc:
        library.add(make("nested", sensitivity="public"), workspace=ws)
    assert exc.value.issues[0]["rule"] == "entry_id_conflict"
    assert not (ws / "library" / "nested.yaml").exists()


def test_cli_validate_and_remove_reach_subfolders(cli_ws, capsys):
    sub = cli_ws / ".riskquant" / "library" / "team-a"
    put(sub, make("nested"))
    (sub / "broken.yaml").write_text(yaml.safe_dump({"entry_id": "broken"}), encoding="utf-8")
    code, out = rqh("library", "validate", capsys=capsys)
    assert code == 1 and out["issues"][0]["path"].startswith("library.team-a/broken.")
    code, out = rqh("library", "remove", "nested", capsys=capsys)
    assert code == 0 and not (sub / "nested.yaml").exists()


# --- CLI ---------------------------------------------------------------------


def rqh(*argv, capsys):
    code = cli.main(list(argv) + ["--json"])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def cli_ws(tmp_path, monkeypatch, shipped):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    (tmp_path / ".riskquant" / "library").mkdir(parents=True)
    return tmp_path


def test_cli_round_trip(cli_ws, capsys):
    entry_file = cli_ws / "entry.yaml"
    entry_file.write_text(yaml.safe_dump(make("mem-cli")), encoding="utf-8")
    code, out = rqh("library", "add", str(entry_file), capsys=capsys)
    assert code == 0 and out["data"]["result"] == "added"
    code, out = rqh("library", "add", str(entry_file), capsys=capsys)
    assert code == 0 and out["data"]["result"] == "duplicate"
    code, out = rqh("library", "search", "--family", "primary_loss.response", "--industry", "retail",
                    "--size-band", "mid_market", "--currency", "EUR", capsys=capsys)
    hit = out["data"]["hits"][0]
    assert code == 0 and hit["entry_id"] == "mem-cli" and hit["origin"] == "memory"
    assert hit["currency_mismatch"] is True and hit["segment_match"] == 2 and hit["entry"]["entry_id"] == "mem-cli"
    code, out = rqh("library", "list", capsys=capsys)
    assert code == 0 and [e["entry_id"] for e in out["data"]["entries"]] == ["mem-cli"]
    code, out = rqh("library", "validate", capsys=capsys)
    assert code == 0
    code, out = rqh("library", "remove", "mem-cli", capsys=capsys)
    assert code == 0
    code, out = rqh("library", "remove", "mem-cli", capsys=capsys)
    assert code == 5


def test_cli_add_rejected_exit_1(cli_ws, capsys):
    bad = make("mem-bad")
    del bad["sensitivity"]
    (cli_ws / "bad.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    code, out = rqh("library", "add", str(cli_ws / "bad.yaml"), capsys=capsys)
    assert code == 1 and out["issues"][0]["rule"] == "required"


def test_cli_missing_workspace(tmp_path, monkeypatch, capsys, shipped):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RQH_WORKSPACE", raising=False)
    put(shipped / "ddos", make("bench-d", tier="benchmark"))
    code, out = rqh("library", "search", "--family", "primary_loss.response", capsys=capsys)
    assert code == 0 and out["data"]["hits"][0]["origin"] == "benchmark"
    (tmp_path / "e.yaml").write_text(yaml.safe_dump(make("mem-q")), encoding="utf-8")
    for argv in (["add", "e.yaml"], ["list"], ["validate"], ["remove", "x"]):
        code, _ = rqh("library", *argv, capsys=capsys)
        assert code == 5


def test_remove_refuses_an_id_that_leaves_the_library(tmp_path):
    from rqharness import library, workspace

    root = tmp_path / ".riskquant"
    workspace.init_workspace(root)
    victim = root / "org-profile.yaml"
    victim.write_text("schema_version: '1'\n", encoding="utf-8")
    with pytest.raises(NotFound):
        library.remove("../org-profile", workspace=root)
    assert victim.is_file()


def found(lookup, entry_id):
    """The entry a lookup resolves ``entry_id`` to; the reference issues are asserted elsewhere."""
    return lookup(entry_id, "at")[0]


def test_lookup_finds_only_valid_entries(tmp_path, shipped):
    from rqharness import workspace

    root = tmp_path / ".riskquant"
    workspace.init_workspace(root)
    (root / "library" / "loose.yaml").write_text("tier: internal_data\n", encoding="utf-8")
    (root / "notes.yaml").write_text("tier: internal_data\n", encoding="utf-8")
    assert found(library.entry_lookup(root), "../notes") is None
    assert found(library.entry_lookup(root), "*") is None  # a pattern names no entry
    assert found(library.entry_lookup(root), "loose") is None  # present but not a valid library entry
    (root / "library" / "broken.yaml").write_text("tier: [unclosed\n", encoding="utf-8")
    assert found(library.entry_lookup(root), "broken") is None  # malformed YAML is not a traceback


def test_lookup_reports_a_missing_entry_at_the_reference(ws, shipped):
    entry, issues = library.entry_lookup(ws)("absent", "inputs.sources.2.library_entry_id")
    assert entry is None
    assert [(i["path"], i["rule"]) for i in issues] == [("inputs.sources.2.library_entry_id", "library_entry_missing")]


def test_lookup_prefers_memory_then_the_shipped_seam(ws, shipped):
    put(shipped / "ransomware", make("shared", tier="benchmark"))
    put(shipped / "ransomware", make("bench-only", tier="benchmark"))
    put(ws / "library", make("shared"))
    entry, issues = library.entry_lookup(ws)("shared", "at")
    assert entry["tier"] == FIXTURE["tier"] and issues == []  # memory shadowing shipped is precedence, not ambiguity
    assert found(library.entry_lookup(ws), "bench-only")["tier"] == "benchmark"  # rglob reaches the subfolder
    assert found(library.entry_lookup(None), "shared")["tier"] == "benchmark"  # no workspace: shipped only


def test_lookup_reports_an_id_two_memory_files_hold_instead_of_guessing(ws, shipped):
    put(shipped, make("twin", tier="benchmark"))
    put(ws / "library", make("twin"))
    put(ws / "library" / "team-a", make("twin", sensitivity="public"))
    entry, issues = library.entry_lookup(ws)("twin", "inputs.sources.3.library_entry_id")
    assert entry is None  # neither memory file, nor the shipped one they both shadow
    assert [(i["path"], i["rule"]) for i in issues] == [("inputs.sources.3.library_entry_id", "duplicate_entry_id")]
    message = issues[0]["message"]
    assert "'twin.yaml'" in message and "'team-a/twin.yaml'" in message and "rqh library validate" in message


def _broken(entry_id: str) -> dict:
    """A memory entry for ``entry_id`` that fails the library-entry schema (no ``sensitivity``)."""
    entry = make(entry_id)
    del entry["sensitivity"]
    return entry


def test_an_invalid_memory_override_is_reported_instead_of_the_benchmark(ws, shipped):
    put(shipped / "ransomware", make("shared", tier="benchmark"))
    put(ws / "library" / "team-a", _broken("shared"))
    entry, issues = library.entry_lookup(ws)("shared", "inputs.sources.4.library_entry_id")
    assert entry is None  # never the shipped benchmark the user meant to override
    assert [(i["path"], i["rule"]) for i in issues] == [("inputs.sources.4.library_entry_id", "library_entry_invalid")]
    message = issues[0]["message"]
    assert "'team-a/shared.yaml'" in message and "rqh library validate" in message


def test_an_invalid_memory_file_does_not_shadow_other_ids(ws, shipped):
    put(shipped, make("shared", tier="benchmark"))
    put(shipped, make("bench-only", tier="benchmark"))
    put(ws / "library", make("shared"))  # a valid override still wins
    put(ws / "library", _broken("broken-other"))
    lookup = library.entry_lookup(ws)
    assert lookup("shared", "at") == (make("shared"), [])
    assert found(lookup, "bench-only")["tier"] == "benchmark"  # an id only the shipped tree holds still resolves


def test_a_duplicate_id_is_reported_before_an_invalid_file(ws, shipped):
    put(shipped, make("twin", tier="benchmark"))
    put(ws / "library", make("twin"))
    put(ws / "library" / "team-a", _broken("twin"))
    _, issues = library.entry_lookup(ws)("twin", "at")
    assert [i["rule"] for i in issues] == ["duplicate_entry_id"]


def test_a_memory_id_resolves_to_nothing_one_file_or_the_duplicate_issue(ws):
    put(ws / "library", make("solo"))
    put(ws / "library" / "team-a", _broken("bad"))
    put(ws / "library", make("twin"))
    put(ws / "library" / "team-a", make("twin"))
    index = library._files_by_id(library._entry_files(library.memory_dir(ws)))
    assert library._memory_holder("absent", index) is None
    assert library._memory_holder("solo", index).path == ws / "library" / "solo.yaml"
    assert library._memory_holder("bad", index).path == ws / "library" / "team-a" / "bad.yaml"  # validity is the caller's
    duplicate = library._memory_holder("twin", index)
    assert (duplicate["path"], duplicate["rule"]) == ("library.twin.entry_id", "duplicate_entry_id")


def test_search_still_hides_an_invalid_memory_override(ws, shipped):
    put(shipped, make("shared", tier="benchmark"))
    put(ws / "library", _broken("shared"))
    hits = library.search(Q, workspace=ws, today=TODAY)
    assert [(h.entry["entry_id"], h.origin) for h in hits] == [("shared", "benchmark")]


def test_a_file_that_matches_only_by_name_is_marked_in_the_duplicate_issue(ws, shipped):
    put(ws / "library", make("x"))
    (ws / "library" / "notes").mkdir()
    (ws / "library" / "notes" / "x.yaml").write_text("tier: internal_data\n", encoding="utf-8")  # holds no entry_id
    [duplicate] = [i for i in library.validate_all(workspace=ws) if i["rule"] == "duplicate_entry_id"]
    assert "'notes/x.yaml' (no entry_id; matched by file name)" in duplicate["message"]
    assert "'x.yaml' (no" not in duplicate["message"]  # the file holding the id carries no marker


def test_lookup_applies_the_pert_order_check(ws, shipped):
    put(ws / "library", make("upside-down", value={**FIXTURE["value"], "min": 9, "mode": 5, "max": 10}))
    assert found(library.entry_lookup(ws), "upside-down") is None


def test_lookup_matches_the_id_inside_the_file(ws, shipped):
    entry = make("real-id")
    (ws / "library" / "other-name.yaml").write_text(yaml.safe_dump(entry), encoding="utf-8")
    hits = library.search(Q, workspace=ws, today=TODAY)
    assert ids(hits) == ["real-id"]  # identity is the id inside the file, for search and lookup alike
    assert found(library.entry_lookup(ws), "real-id") == entry
    assert found(library.entry_lookup(ws), "other-name") is None
