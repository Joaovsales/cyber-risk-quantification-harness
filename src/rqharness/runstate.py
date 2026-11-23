"""The run status machine: the only writer of ``run.yaml``.

``TRANSITIONS`` is the spec table; :func:`apply` is the single way a status
changes, so a skill or a later slice cannot move a run along an unlisted edge.
:func:`update` is the single way to edit ``run.yaml`` without changing the
status. :func:`check` raises the refusal :func:`apply` would raise and :func:`can`
answers the same question as a bool, so no caller reads the table or the status
to decide a write. Every refusal is an :class:`~rqharness.outcomes.IllegalTransition`
and an invalid ``run.yaml`` is :class:`~rqharness.outcomes.Rejected`.

Every write to a run's state happens under the run lock (:func:`locked`): :func:`apply`
and :func:`update` take it themselves, and finalize and the request writers hold it across
their read, check and write. :func:`publish` renames a built directory into place and fires
a trigger as one step: a journal names the pending trigger, so a crash between the rename and
the status write still reads as the new status, and the next locked write records it.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal, get_args

from rqharness import schemas, workspace
from rqharness.outcomes import IllegalTransition, Issue, Rejected, issue
from rqharness.schemas import validate_document

RunStatus = Literal["scoping", "collecting", "awaiting_data", "finalized"]
Trigger = Literal["confirm", "rescope", "pause", "resume", "auto_resume", "finalize", "reopen"]

# trigger -> {from: to}
TRANSITIONS: dict[str, dict[str, str]] = {
    "confirm": {"scoping": "collecting"},
    "rescope": {"collecting": "scoping"},
    "pause": {"collecting": "awaiting_data"},
    "resume": {"awaiting_data": "collecting"},
    "auto_resume": {"awaiting_data": "collecting"},
    "finalize": {"collecting": "finalized", "awaiting_data": "finalized"},
    "reopen": {"finalized": "collecting"},
}
assert set(TRANSITIONS) == set(get_args(Trigger))

# A request in one of these statuses keeps a run waiting; requests.REQUEST_TRANSITIONS has them as its sources.
OPEN_REQUEST_STATUSES = ("drafted", "sent")
# A run in one of these statuses keeps its requests, candidates and inputs frozen until `rqh run reopen`.
FROZEN_STATUSES = ("finalized",)
_KEY_ORDER = ("schema_version", "scenario_id", "route", "route_overrides", "n", "seed",
              "status", "created_at", "updated_at")

LOCK_NAME = ".lock"
LOCK_STALE_SECONDS = 10 * 60  # a lock untouched this long belongs to a holder that died
LOCK_REFRESH_SECONDS = 60  # how often a live holder touches its lock
LOCK_WAIT_SECONDS = 2.0  # how long a writer waits for a held lock before it refuses
LOCK_POLL_SECONDS = 0.05
BREAK_SUFFIX = ".break"  # the guard a writer holds while it breaks a stale lock: .lock.break
PENDING_NAME = ".pending-status.yaml"  # the journal of a publish: {trigger, path}


class _HeldLocks(threading.local):
    """The run locks this thread holds: per thread, so a thread a holder starts takes the lock itself."""

    keys: frozenset[str] = frozenset()


_HELD = _HeldLocks()


def read_state(run_dir: Path) -> dict | None:
    """The validated ``run.yaml``, or None when the run has none yet."""
    path = run_dir / "run.yaml"
    if not path.is_file():
        return None
    data, issues = schemas.load_yaml(path, "run")
    issues = issues or validate_document("run", data, stem="run")
    if issues:
        raise Rejected(issues)
    return data


def _status(state: dict | None) -> RunStatus:
    """A run directory without ``run.yaml`` is in ``scoping``."""
    return state["status"] if state else "scoping"


def status_of(run_dir: Path) -> RunStatus:
    """The run status, counting a published version whose status write a crash lost (see :func:`publish`)."""
    current = _status(read_state(run_dir))
    pending = _pending(run_dir, current)
    return TRANSITIONS[pending][current] if pending else current


def _write_state(run_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Stamp ``updated_at``, validate and atomically write ``run.yaml``."""
    stamped = {**state, "updated_at": workspace.utc_now()}
    ordered = {k: stamped[k] for k in _KEY_ORDER if k in stamped}
    issues = validate_document("run", ordered, stem="run")
    if issues:
        raise Rejected(issues)
    workspace.write_yaml(run_dir / "run.yaml", ordered)
    return ordered


def _has_open_request(run_dir: Path) -> bool:
    """Whether ``requests.yaml`` holds a drafted or sent request; :class:`Rejected` for a file that does not validate.

    It reads the file the way ``requests.load`` does, which this module cannot import.
    """
    path = run_dir / "requests.yaml"
    if not path.is_file():
        return False
    doc, issues = schemas.load_yaml(path, "requests")
    issues = issues or validate_document("requests", doc, stem="requests")
    if issues:
        raise Rejected(issues)
    return any(r["status"] in OPEN_REQUEST_STATUSES for r in doc["requests"])


def _refusal(run_dir: Path, current: RunStatus, trigger: Trigger) -> Issue | None:
    """Why ``trigger`` may not fire on a run that is ``current``, or None when it may.

    An unknown trigger raises KeyError: a misspelt name is a bug, not a refusal.
    """
    if current not in TRANSITIONS[trigger]:
        return issue("run.status", "illegal_transition", f"cannot {trigger} a run that is {current}")
    if trigger == "pause" and not _has_open_request(run_dir):
        return issue("run.status", "pause_guard", "pause needs at least one request that is drafted or sent")
    return None


def _check(run_dir: Path, current: RunStatus, trigger: Trigger) -> None:
    refusal = _refusal(run_dir, current, trigger)
    if refusal:
        raise IllegalTransition([refusal])


def check(run_dir: Path, trigger: Trigger) -> None:
    """Raise the :class:`IllegalTransition` :func:`apply` would raise for ``trigger`` now; writes nothing."""
    _check(run_dir, status_of(run_dir), trigger)


def can(run_dir: Path, trigger: Trigger) -> bool:
    """Whether :func:`apply` would accept ``trigger`` now; writes nothing."""
    return _refusal(run_dir, status_of(run_dir), trigger) is None


def check_editable(run_dir: Path, action: str) -> None:
    """Raise :class:`IllegalTransition` while the run is in ``FROZEN_STATUSES``; writes nothing.

    Every writer of a run's requests and candidates calls it, except withdrawing a request.
    ``action`` names the write in the refusal, which points at ``rqh run reopen``.
    """
    current = status_of(run_dir)
    if current in FROZEN_STATUSES:
        raise IllegalTransition([issue(
            "run.status", "illegal_transition",
            f"cannot {action} while the run is {current}; run `rqh run reopen` first")])


def apply(run_dir: Path, trigger: Trigger, **changes: Any) -> dict[str, Any]:
    """Move the run along ``trigger`` (merging ``changes``) or raise :class:`IllegalTransition`."""
    with locked(run_dir):
        state = read_state(run_dir)
        current = _status(state)
        _check(run_dir, current, trigger)
        merged = {"schema_version": "1", "created_at": workspace.utc_now(), **(state or {}), **changes,
                  "status": TRANSITIONS[trigger][current]}
        return _write_state(run_dir, merged)


def update(run_dir: Path, *, allowed: Collection[RunStatus], action: str, **changes: Any) -> dict[str, Any]:
    """Merge ``changes`` into ``run.yaml`` keeping the status; :class:`IllegalTransition` unless the run is ``allowed``.

    ``action`` names the edit in the refusal ("cannot <action> while the run is <status>").
    A run with no ``run.yaml`` yet is refused even when ``scoping`` is allowed: there is
    nothing to edit until ``confirm`` creates the file. A status change is never an
    update: it goes through :func:`apply`.
    """
    if "status" in changes:
        raise ValueError("runstate.update never changes the status; use runstate.apply")
    with locked(run_dir):
        state = read_state(run_dir)
        current = _status(state)
        if state is None or current not in allowed:
            raise IllegalTransition([issue(
                "run.status", "illegal_transition", f"cannot {action} while the run is {current}")])
        return _write_state(run_dir, {**state, **changes})


def publish(run_dir: Path, built: Path, name: str, trigger: Trigger) -> dict[str, Any]:
    """Rename ``built`` to ``run_dir/name`` and fire ``trigger``, so a crash between the two is not lost.

    The caller holds the lock and has checked ``trigger``. The journal is written before the
    rename and removed after the status write. While it names a directory that exists and a
    trigger that still fires, :func:`status_of` reads the new status and the next
    :func:`locked` records it; a journal whose trigger no longer fires is spent.
    """
    workspace.write_yaml(run_dir / PENDING_NAME, {"trigger": trigger, "path": name})
    os.replace(built, run_dir / name)
    saved = apply(run_dir, trigger)
    _drop_journal(run_dir)
    return saved


def _drop_journal(run_dir: Path) -> None:
    """Remove a spent journal, never failing the write it followed.

    A reader that holds the file open on Windows blocks the delete, so the journal is then
    emptied in place instead: an empty journal is spent too, and the next :func:`locked`
    removes it.
    """
    path = run_dir / PENDING_NAME
    try:
        path.unlink(missing_ok=True)
    except OSError:
        try:
            path.write_bytes(b"")
        except OSError:
            pass  # the next locked write tries again


def _pending(run_dir: Path, current: RunStatus) -> Trigger | None:
    """The trigger a crashed :func:`publish` left unrecorded, when it still fires from ``current``."""
    doc, issues = schemas.load_yaml(run_dir / PENDING_NAME, "pending")
    if issues or not isinstance(doc, dict) or doc.get("trigger") not in TRANSITIONS:
        return None
    name = doc.get("path")
    if not isinstance(name, str) or Path(name).name != name or not (run_dir / name).is_dir():
        return None
    return doc["trigger"] if _refusal(run_dir, current, doc["trigger"]) is None else None


def _recover(run_dir: Path) -> None:
    """Record the status a crashed :func:`publish` left unwritten, then drop its journal."""
    if not (run_dir / PENDING_NAME).is_file():
        return
    pending = _pending(run_dir, _status(read_state(run_dir)))
    if pending:
        apply(run_dir, pending)
    _drop_journal(run_dir)


def _is_stale(path: Path) -> bool | None:
    """Whether ``path`` is older than ``LOCK_STALE_SECONDS``; None when it no longer exists."""
    try:
        return time.time() - path.stat().st_mtime > LOCK_STALE_SECONDS
    except FileNotFoundError:
        return None


def _create(path: Path, token: str) -> bool:
    """Create ``path`` exclusively, holding ``token`` as its last word; False when it already exists."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()} {workspace.utc_now()} {token}\n")
    return True


def _token_of(path: Path) -> str | None:
    """The token :func:`_create` wrote into ``path`` ("" for an empty file), or None when it cannot be read."""
    try:
        words = path.read_text(encoding="utf-8").split()
    except (OSError, UnicodeDecodeError):
        return None
    return words[-1] if words else ""


def _release(path: Path, token: str) -> None:
    """Delete ``path`` (the lock or the break guard) only while it still holds ``token``."""
    if _token_of(path) == token:
        path.unlink(missing_ok=True)


def _break_stale(lock: Path, guard: Path, token: str) -> bool:
    """Delete ``lock`` if it is still stale, while holding the break guard; False when another breaker holds it.

    A guard left by a breaker that died while breaking is itself broken, but only while it
    still holds the token read before its staleness was checked.
    """
    if not _create(guard, token):
        seen = _token_of(guard)
        if seen is not None and _is_stale(guard):
            _release(guard, seen)
        return False
    try:
        if _is_stale(lock):
            lock.unlink(missing_ok=True)
    finally:
        _release(guard, token)
    return True


def _take_lock(lock: Path, token: str) -> bool:
    """Create ``lock`` holding ``token``; False while a live holder has it.

    A lock that vanishes between the failed create and its stale check was released, so the
    create is tried again. A stale lock is broken only while holding a second exclusive file,
    the break guard, and only after its staleness is checked again, so two writers that both
    saw it stale never both take it.
    """
    guard = lock.with_name(lock.name + BREAK_SUFFIX)
    for _ in range(3):
        if _create(lock, token):
            return True
        stale = _is_stale(lock)
        if stale is None:
            continue
        if not stale or not _break_stale(lock, guard, token):
            return False
    return False


def _keep_fresh(lock: Path, stop: threading.Event) -> None:
    """Touch ``lock`` every ``LOCK_REFRESH_SECONDS`` until ``stop``, or until the lock is gone."""
    while not stop.wait(LOCK_REFRESH_SECONDS):
        try:
            os.utime(lock)
        except FileNotFoundError:
            return
        except OSError:
            continue  # a passing refusal, such as a reader holding the file open on Windows


@contextmanager
def locked(run_dir: Path) -> Iterator[None]:
    """Hold the run ``.lock`` for the block; raises :class:`Rejected` (``lock_held``) while another writer has it.

    A writer polls for up to ``LOCK_WAIT_SECONDS`` before it refuses, so brief contention
    between parallel commands is waited out. Re-entrant within one thread (never in a thread
    it starts), so a holder can call :func:`apply`. The holder refreshes the lock while it
    works, so only a dead holder's lock goes stale. On entry it records any status a crashed
    :func:`publish` left unwritten.
    """
    key = os.path.abspath(run_dir)
    before = _HELD.keys
    if key in before:
        yield
        return
    lock, token = run_dir / LOCK_NAME, secrets.token_hex(8)
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while not _take_lock(lock, token):
        if time.monotonic() >= deadline:
            # The wording is a pinned CLI contract (tests/cli).
            raise Rejected([issue("run.lock", "lock_held", "another rqh command holds the run lock; try again shortly")])
        time.sleep(LOCK_POLL_SECONDS)
    stop = threading.Event()
    threading.Thread(target=_keep_fresh, args=(lock, stop), daemon=True).start()
    _HELD.keys = before | {key}
    try:
        _recover(run_dir)
        yield
    finally:
        _HELD.keys = before
        stop.set()
        _release(lock, token)
