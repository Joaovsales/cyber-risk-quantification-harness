"""The private `.riskquant/` workspace: creation, atomic writes and YAML reads.

Every file a command writes goes through :func:`atomic_write_text` (or :func:`write_yaml`),
or is built inside a version's tmp directory that finalize renames, so a crash never leaves
a half-written document.
"""

from __future__ import annotations

import datetime
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from rqharness.outcomes import NotFound, issue

GITIGNORE = "*\n"  # the workspace is private by default; a team opts in by deleting this file
RUNS_DIRNAME = "runs"  # every run lives at <workspace>/runs/<id>/


def utc_now() -> str:
    """Now as ``YYYY-MM-DDTHH:MM:SSZ``; tests monkeypatch this to fix the clock."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 with LF newlines to a temp file beside ``path``, then rename over it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(text.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class _NoAliasDumper(yaml.SafeDumper):
    """Writes a value shared by two keys twice, so every file rqh writes parses without aliases."""

    def ignore_aliases(self, data: object) -> bool:
        return True


def write_yaml(path: Path, data: object) -> None:
    atomic_write_text(path, yaml.dump(data, Dumper=_NoAliasDumper, sort_keys=False, allow_unicode=True))


def plain(value: object) -> object:
    """YAML parses bare dates; schemas and JSON want the ISO strings."""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plain(v) for v in value]
    return value


# The way out for a file an older rqh wrote with aliases (0.1.0 shared an answer's value with its candidate).
ALIAS_HINT = ("re-save the file without anchors: replace each `*idNNN` with the value its `&idNNN` anchor marks, "
              "and drop the `&idNNN` marker")


class _NoAliasLoader(yaml.SafeLoader):
    """``SafeLoader`` that refuses aliases, so a shared document cannot expand into billions of nodes."""

    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.composer.ComposerError(None, None, "found an alias; rqh documents may not use YAML aliases",
                                              event.start_mark, ALIAS_HINT)
        return super().compose_node(parent, index)


def parse_yaml(data: bytes) -> object | None:
    """The document in UTF-8 ``data``, with dates as ISO strings; an alias is a :class:`yaml.YAMLError`."""
    return plain(yaml.load(data.decode("utf-8"), Loader=_NoAliasLoader))  # noqa: S506 - a SafeLoader subclass


def read_yaml(path: Path) -> object | None:
    """:func:`parse_yaml` of the file, or None when the file does not exist."""
    if not path.is_file():
        return None
    return parse_yaml(path.read_bytes())


@dataclass(frozen=True)
class Run:
    """One run: its directory and the workspace that holds it, as ``<workspace>/runs/<id>/``.

    A function that reads workspace-level files for a run (the org profile, the library)
    takes a Run and reads them from ``workspace``, never from the folders above ``dir``.
    Construction refuses, with ``ValueError``, a ``dir`` that is not directly inside
    ``<workspace>/runs/``, and stores ``dir`` as ``<workspace>/runs/<id>`` however the
    caller spelled it, so the same run is always the same Run. Commands get one from
    ``cli.resolve_run``.
    """

    workspace: Path
    dir: Path

    @classmethod
    def named(cls, workspace: Path, run_id: str) -> Run:
        return cls(workspace, workspace / RUNS_DIRNAME / run_id)

    def __post_init__(self) -> None:
        runs = self.workspace / RUNS_DIRNAME
        # The parent is resolved, not ``dir`` itself, so a symlinked run inside runs/ still counts.
        if self.dir.name in ("", ".", "..") or self.dir.parent.resolve() != runs.resolve():
            raise ValueError(f"{self.dir} is not a run directory in {runs}")
        object.__setattr__(self, "dir", runs / self.dir.name)


def require_workspace(root: Path) -> Path:
    """``root``, which must be an existing directory; raises :class:`NotFound` naming ``rqh init`` otherwise."""
    if not root.is_dir():
        raise NotFound([issue("workspace", "missing", f"no workspace at {root}; run `rqh init`")])
    return root


def init_workspace(root: Path) -> bool:
    """Create the workspace; True when anything was created.

    ``.gitignore`` is written on the first init (no ``runs/`` and no ``library/`` yet), even
    into a ``.riskquant/`` folder that already existed, so a team that deleted it after a
    real init to share the workspace keeps it deleted.
    """
    created = not root.exists()
    first = not (root / RUNS_DIRNAME).exists() and not (root / "library").exists()
    root.mkdir(parents=True, exist_ok=True)
    if first and not (root / ".gitignore").exists():
        atomic_write_text(root / ".gitignore", GITIGNORE)
        created = True
    for name in (RUNS_DIRNAME, "library"):
        child = root / name
        if not child.exists():
            child.mkdir()
            created = True
    return created
