"""The library of parameter values: the organisation's memory plus shipped benchmarks.

Memory entries live under ``<workspace>/library/``: :func:`add` writes a new one as
``<entry_id>.yaml`` and a user may move it into a subfolder. Shipped entries live in the
installed package and are read-only. Every function here reads a tree through
:func:`_yaml_files`, subfolders included, and knows an entry by the ``entry_id`` inside it.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Callable, Literal, NamedTuple

from rqharness import workspace as ws
from rqharness.outcomes import Issue, NotFound, Rejected, issue
from rqharness.schemas import load_yaml, validate_document

DEFAULT_STALE_MONTHS = 18
_ENTRY_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,62}")  # the schema's entry_id slug
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_VALIDATE_COMMAND = "`rqh library validate`"  # where a refused lookup sends the user for the details

# (entry id, issue path of the reference) -> the library entry it names, or None and the issues why
EntryLookup = Callable[[str, str], tuple[dict | None, list[Issue]]]


@dataclass(frozen=True)
class LibraryQuery:
    parameter_family: str
    scenario_type: str | None = None
    industry: str | None = None
    size_band: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class LibraryHit:
    entry: dict
    origin: Literal["memory", "benchmark"]
    stale: bool
    currency_mismatch: bool
    segment_match: int


@dataclass(frozen=True)
class Added:
    path: Path


@dataclass(frozen=True)
class Duplicate:
    path: Path


def shipped_dir() -> Path:
    """The benchmark entries installed with the package (tests monkeypatch this)."""
    return Path(str(resources.files("rqharness") / "data" / "benchmarks"))


def memory_dir(workspace: Path) -> Path:
    return workspace / "library"


def content_hash(entry: dict) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def memory_entries(workspace: Path) -> list[dict]:
    """Every valid entry in the workspace's memory library."""
    return _entries(memory_dir(workspace))


def _yaml_files(directory: Path) -> list[Path]:
    """Every entry file under ``directory``, subfolders included, in a stable order."""
    return sorted(directory.rglob("*.yaml")) if directory.is_dir() else []


class _EntryFile(NamedTuple):
    path: Path
    name: str  # the path below its tree's folder (memory or shipped) without ".yaml"; issues use library.<name>
    data: object
    issues: list[Issue]


def _entry_files(directory: Path) -> list[_EntryFile]:
    """Every entry file under ``directory`` with what it parsed to."""
    files = []
    for path in _yaml_files(directory):
        name = path.relative_to(directory).with_suffix("").as_posix()
        files.append(_EntryFile(path, name, *load_yaml(path, f"library.{name}")))
    return files


def _trust_issues(file: _EntryFile) -> list[Issue]:
    """Why search and lookup would not trust the entry ``file`` holds, under ``library.<name>``;
    empty when it parses, passes the library-entry schema and is in PERT order."""
    stem = f"library.{file.name}"
    return file.issues or validate_document("library-entry", file.data, stem=stem) or _pert_issues(file.data, stem)


def _valid(file: _EntryFile) -> dict | None:
    """The entry ``file`` holds when search and lookup trust it, else None."""
    return None if _trust_issues(file) else file.data  # type: ignore[return-value]


def _entries(directory: Path) -> list[dict]:
    return [entry for file in _entry_files(directory) if (entry := _valid(file))]


def _held_id(file: _EntryFile) -> str | None:
    entry_id = file.data.get("entry_id") if isinstance(file.data, dict) else None
    return entry_id if isinstance(entry_id, str) else None


def _files_by_id(files: list[_EntryFile]) -> dict[str, list[_EntryFile]]:
    """Entry files by the id each answers to: the ``entry_id`` inside it, else its file name,
    so a file too broken to hold an id can still be removed by name. Several files under one id
    is a ``duplicate_entry_id`` in the memory tree only (:func:`_duplicate_id_issue` states that rule)."""
    held: dict[str, list[_EntryFile]] = {}
    for file in files:
        held.setdefault(_held_id(file) or file.path.stem, []).append(file)
    return held


def _file_names(files: list[_EntryFile]) -> str:
    """The files as an issue message names them, marking one that answers only by its file name."""
    return ", ".join(repr(f"{file.name}.yaml") + ("" if _held_id(file) else " (no entry_id; matched by file name)")
                     for file in files)


def _duplicate_id_issue(entry_id: str, files: list[_EntryFile]) -> Issue | None:
    """The ``duplicate_entry_id`` issue when several memory files answer to ``entry_id``, else None:
    which one is meant is the user's call, so validate reports it and nothing else guesses."""
    if len(files) < 2:
        return None
    return issue(f"library.{entry_id}.entry_id", "duplicate_entry_id",
                 f"{entry_id!r} is held by {len(files)} files ({_file_names(files)}); keep one")


def _memory_holder(entry_id: str, memory: dict[str, list[_EntryFile]]) -> _EntryFile | Issue | None:
    """How ``entry_id`` resolves in the memory library, given as :func:`_files_by_id` indexes it:
    the one file that answers to it (valid or not; trust is the caller's question), None when
    none does, or the ``duplicate_entry_id`` issue when several do. Every memory operation that
    resolves an id goes through here, so ``add``, ``remove`` and ``entry_lookup`` cannot disagree."""
    files = memory.get(entry_id, [])
    return _duplicate_id_issue(entry_id, files) or (files[0] if files else None)


def _holder(entry_id: str, workspace: Path) -> Path | None:
    """The path of the one memory file that answers to ``entry_id``, or None.

    Raises :class:`~rqharness.outcomes.Rejected` when several do: which one is meant is the
    user's call, never a guess.
    """
    held = _memory_holder(entry_id, _files_by_id(_entry_files(memory_dir(workspace))))
    if isinstance(held, _EntryFile):
        return held.path
    if held is not None:
        raise Rejected([held])
    return None


def _trees(workspace: Path | None) -> list[tuple[Literal["memory", "benchmark"], Path]]:
    """Where entries come from, in precedence order: workspace memory (when known), then shipped."""
    trees: list[tuple[Literal["memory", "benchmark"], Path]] = [("benchmark", shipped_dir())]
    if workspace is not None:
        trees.insert(0, ("memory", memory_dir(workspace)))
    return trees


def entry_lookup(workspace: Path | None) -> EntryLookup:
    """The lookup ``validate.validate_inputs`` takes for ``memory`` sources.

    Given an entry id and the issue path of the reference to it, returns the entry
    :func:`search` shows under that id (memory before shipped) and no issues, or ``None`` and
    one issue at that path: ``library_entry_missing``; ``duplicate_entry_id`` when several
    memory files answer to the id, the rule ``remove`` and ``add`` refuse on; or
    ``library_entry_invalid`` when the one memory file that does is not a valid entry. A memory
    file answering to an id is the user's word for it, so a broken one is reported, never passed
    over for the shipped benchmark it was meant to override.

    It reads the trees once, on its first call, so build one per validation.
    """
    index: tuple[dict[str, list[_EntryFile]], dict[str, list[_EntryFile]]] | None = None  # (memory, shipped)

    def find(entry_id: str, at: str) -> tuple[dict | None, list[Issue]]:
        nonlocal index
        if index is None:
            memory = _files_by_id(_entry_files(memory_dir(workspace))) if workspace is not None else {}
            index = memory, _files_by_id(_entry_files(shipped_dir()))
        memory, shipped = index
        held = _memory_holder(entry_id, memory)
        if isinstance(held, _EntryFile):
            if entry := _valid(held):
                return entry, []
            return None, [issue(at, "library_entry_invalid",
                                f"the workspace library holds {entry_id!r} in {_file_names([held])}, which is not "
                                f"a valid entry; {_VALIDATE_COMMAND} lists its issues")]
        if held is not None:
            return None, [issue(at, held["rule"], f"{held['message']}; {_VALIDATE_COMMAND} lists them")]
        for file in shipped.get(entry_id, []):
            if entry := _valid(file):
                return entry, []
        return None, [issue(at, "library_entry_missing",
                            f"no library entry {entry_id!r} in the workspace library or shipped benchmarks")]

    return find


def _add_months(day: date, months: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))


def _segment_matches(want: str | None, have: str) -> int | None:
    """None when the entry is filtered out, else 1 for an exact match and 0 for `any`/no filter."""
    if want is None:
        return 0
    if have == want:
        return 1
    return 0 if have == "any" else None


def _hit(entry: dict, origin: str, q: LibraryQuery, today: date) -> LibraryHit | None:
    if entry["parameter_family"] != q.parameter_family:
        return None
    if q.scenario_type is not None and q.scenario_type not in entry["scenario_tags"]:
        return None
    industry = _segment_matches(q.industry, entry["segment"]["industry"])
    size = _segment_matches(q.size_band, entry["segment"]["size_band"])
    if industry is None or size is None:
        return None
    months = entry.get("stale_after_months", DEFAULT_STALE_MONTHS)
    stale = _add_months(date.fromisoformat(entry["period"]["end"]), months) < today
    unit = entry["value"]["unit"]
    mismatch = q.currency is not None and bool(_CURRENCY.match(unit)) and unit != q.currency
    return LibraryHit(entry, origin, stale, mismatch, industry + size)  # type: ignore[arg-type]


def search(q: LibraryQuery, *, workspace: Path | None, today: date | None = None) -> list[LibraryHit]:
    """Matching entries: memory first, then better segment match, then newer period, then id."""
    today = today or date.today()
    hits = [h for origin, directory in _trees(workspace) for e in _entries(directory) if (h := _hit(e, origin, q, today))]
    hits.sort(key=lambda h: h.entry["entry_id"])
    hits.sort(key=lambda h: (h.entry["period"]["end"], h.entry["captured_at"]), reverse=True)
    hits.sort(key=lambda h: (h.origin != "memory", -h.segment_match))
    return hits


def _pert_issues(entry: object, stem: str) -> list[Issue]:
    value = entry.get("value") if isinstance(entry, dict) else None
    if isinstance(value, dict) and all(isinstance(value.get(k), (int, float)) for k in ("min", "mode", "max")):
        if not value["min"] <= value["mode"] <= value["max"]:
            return [issue(f"{stem}.value", "pert_order", "value must satisfy min <= mode <= max")]
    return []


def _inside(path: Path, parent: Path) -> bool:
    return path.resolve().is_relative_to(parent.resolve())


def add(entry: dict, *, workspace: Path) -> Added | Duplicate:
    """Validate and write one memory entry; idempotent by entry id and content hash.

    Raises :class:`~rqharness.outcomes.Rejected` for an invalid entry, a target inside the
    installed package, an entry id that already holds different content, or an entry id
    that more than one memory file holds.
    """
    issues = validate_document("library-entry", entry, stem="entry") or _pert_issues(entry, "entry")
    if issues:
        raise Rejected(issues)
    target = _holder(entry["entry_id"], workspace) or memory_dir(workspace) / f"{entry['entry_id']}.yaml"
    if _inside(target, shipped_dir()) or _inside(target, Path(__file__).parent):
        raise Rejected([issue("entry", "shipped_data", "memory is never written into the installed package")])
    if target.is_file():
        existing, _ = load_yaml(target, "entry")
        if content_hash(existing or {}) == content_hash(entry):
            return Duplicate(target)
        raise Rejected([issue("entry.entry_id", "entry_id_conflict",
                               f"{entry['entry_id']!r} already holds different content; remove it first")])
    target.parent.mkdir(exist_ok=True)
    ws.write_yaml(target, entry)
    return Added(target)


def remove(entry_id: str, *, workspace: Path) -> None:
    """Delete the one memory file that answers to ``entry_id``, in any subfolder.

    Raises :class:`~rqharness.outcomes.NotFound` when the id is not a valid entry id or no
    file answers to it, and :class:`~rqharness.outcomes.Rejected` when several files do.
    """
    # the id comes from the CLI: anything that is not an id names no entry
    path = _holder(entry_id, workspace) if _ENTRY_ID.fullmatch(entry_id) else None
    if path is None:
        raise NotFound([issue("library", "missing", f"no memory entry {entry_id!r}")])
    path.unlink()


def validate_all(*, workspace: Path) -> list[Issue]:
    """Re-validate every memory file, subfolders included, then flag an id held by several files.

    Issue paths are ``library.<name>.<field>``, where ``<name>`` is the file's path below the
    library folder without ``.yaml``, and ``library.<entry_id>.entry_id`` for a duplicate id.
    """
    files = _entry_files(memory_dir(workspace))
    issues: list[Issue] = []
    for file in files:
        issues += _trust_issues(file)
    by_id = _files_by_id(files)
    return issues + [duplicate for i, held in by_id.items() if (duplicate := _duplicate_id_issue(i, held))]
