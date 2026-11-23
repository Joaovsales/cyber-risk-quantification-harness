"""Requests for data and candidate values: the only writer of ``requests.yaml``.

A found figure is a *candidate* until a person confirms it. Only
:func:`confirm_candidate` ever puts a candidate into ``inputs.yaml``. Each function
returns what it did and raises a :mod:`rqharness.outcomes` kind when it cannot:
``NotFound`` for an unknown id, ``IllegalTransition`` for a move the status tables
do not allow, ``Rejected`` for a document that would not validate. Every write holds the
run lock and, except withdrawing a request, is refused on a finalized run
(:func:`runstate.check_editable`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rqharness import library, runstate, schemas, tiers, validate, workspace
from rqharness.outcomes import IllegalTransition, NotFound, Rejected, issue

REQUEST_TRANSITIONS: dict[str, set[str]] = {
    "drafted": {"sent", "withdrawn"},
    "sent": {"answered", "unavailable", "withdrawn"},
}
CANDIDATE_TRANSITIONS: dict[str, set[str]] = {"pending": {"confirmed", "rejected"}}
_OPEN = runstate.OPEN_REQUEST_STATUSES
assert set(_OPEN) == set(REQUEST_TRANSITIONS), "open statuses are the sources of the request transition table"
_FALLBACK_TIERS = frozenset(name for name, tier in tiers.TIERS.items() if tier.is_fallback)


@dataclass(frozen=True)
class Added:
    item: dict


@dataclass(frozen=True)
class Duplicate:
    item: dict


@dataclass(frozen=True)
class Updated:
    item: dict
    changed: bool


@dataclass(frozen=True)
class Confirmed:
    candidate: dict
    inputs_path: Path


def load(run_dir: Path) -> dict:
    """The validated ``requests.yaml``, or an empty one; raises :class:`Rejected` for a file that does not validate."""
    path = run_dir / "requests.yaml"
    if path.is_file():
        doc, issues = schemas.load_yaml(path, "requests")
        issues = issues or schemas.validate_document("requests", doc, stem="requests")
        if issues:
            raise Rejected(issues)
        return doc
    scenario, _ = schemas.load_yaml(run_dir / "scenario.yaml", "scenario")  # a bad scenario is not ours to report
    scenario_id = scenario.get("scenario_id") if isinstance(scenario, dict) else None
    return {"schema_version": "1", "scenario_id": scenario_id if isinstance(scenario_id, str) else run_dir.name,
            "requests": [], "candidates": []}


def _save(run_dir: Path, doc: dict) -> None:
    issues = schemas.validate_document("requests", doc, stem="requests")
    if issues:
        raise Rejected(issues)
    workspace.write_yaml(run_dir / "requests.yaml", doc)


def _next_id(prefix: str, items: list[dict]) -> str:
    return f"{prefix}-{max((int(i['id'].split('-')[1]) for i in items), default=0) + 1}"


def _find(items: list[dict], item_id: str) -> dict | None:
    return next((i for i in items if i["id"] == item_id), None)


def _get(items: list[dict], item_id: str) -> dict:
    found = _find(items, item_id)
    if found is None:
        raise NotFound([issue("id", "not_found", f"no item {item_id!r}")])
    return found


def _require_move(table: dict[str, set[str]], current: str, to: str) -> None:
    if to not in table.get(current, set()):
        raise IllegalTransition([issue("status", "illegal_transition", f"cannot move from {current} to {to}")])


def _rejected(path: str, rule: str, message: str) -> Rejected:
    return Rejected([issue(path, rule, message)])


def open_requests(run_dir: Path) -> list[dict]:
    return [r for r in load(run_dir)["requests"] if r["status"] in _OPEN]


def pending_candidates(run_dir: Path) -> list[dict]:
    return [c for c in load(run_dir)["candidates"] if c["status"] == "pending"]


def fallback_parameters(inputs: dict) -> list[str]:
    """Baseline estimate paths still on a fallback tier (``tiers.Tier.is_fallback``)."""
    return [f"{block}.{key}"
            for block, body in inputs["parameters"].items() if isinstance(body, dict)
            for key, est in body.items()
            if isinstance(est, dict) and est["provenance"]["tier"] in _FALLBACK_TIERS]


def add_request(run_dir: Path, *, parameter_path: str, ask: str, owner_role: str, person: str | None = None,
                draft_message: str, due_at: str | None = None) -> Added | Duplicate:
    """A new drafted request, or the open request already asking this target for this parameter."""
    with runstate.locked(run_dir):
        runstate.check_editable(run_dir, "add a request")
        doc = load(run_dir)
        target = {"owner_role": owner_role, **({"person": person} if person else {})}
        existing = next((r for r in doc["requests"] if r["status"] in _OPEN
                         and r["parameter_path"] == parameter_path and r["target"] == target), None)
        if existing:
            return Duplicate(existing)
        item = {"id": _next_id("req", doc["requests"]), "parameter_path": parameter_path, "ask": ask,
                "target": target, "draft_message": draft_message, "status": "drafted",
                "created_at": workspace.utc_now(), **({"due_at": due_at} if due_at else {})}
        doc["requests"].append(item)
        _save(run_dir, doc)
        return Added(item)


def _new_candidate(doc: dict, parameter_path: str, value: dict, evidence_kind: str, origin: str,
                   link: str | None) -> dict:
    return {"id": _next_id("cand", doc["candidates"]), "parameter_path": parameter_path, "value": value,
            "evidence_kind": evidence_kind, "origin": origin, **({"link": link} if link else {}),
            "status": "pending", "created_at": workspace.utc_now()}


def transition_request(run_dir: Path, request_id: str, to: str, *,
                       answer: dict | None = None) -> Updated:
    """Move a request to ``to``; on a finalized run only ``withdrawn`` is allowed.

    A repeat of the current status changes nothing, but still finishes an auto-resume a crash
    interrupted, and refuses an answer that differs from the one recorded (its value, note or
    evidence kind).
    """
    with runstate.locked(run_dir):
        if to != "withdrawn":
            runstate.check_editable(run_dir, "update a request")
        doc = load(run_dir)
        item = _get(doc["requests"], request_id)
        if item["status"] == to:
            if answer:
                _require_answer_status(request_id, to)
                if _changes_answer(doc, item, answer):
                    raise IllegalTransition([issue(
                        f"requests.{request_id}.answer", "answer_recorded",
                        f"{request_id} is already {to}, and a repeated update cannot change its answer; "
                        "record a different value with `rqh candidates add`")])
            _auto_resume(run_dir, to)
            return Updated(item, False)
        return _move_request(run_dir, doc, item, to, answer)


def _require_answer_status(request_id: str, to: str) -> None:
    if to != "answered":
        raise _rejected(f"requests.{request_id}.answer", "answer_status", "only an answered request carries an answer")


def _changes_answer(doc: dict, item: dict, answer: dict) -> bool:
    """Whether ``answer`` differs from the recorded one; its evidence kind is on the request's own candidate."""
    stored = item.get("answer", {})
    origin = f"request:{item['id']}"
    stored_kind = next((c["evidence_kind"] for c in doc["candidates"] if c["origin"] == origin), None)
    asked_kind = answer.get("evidence_kind") if answer.get("value") else None
    recorded_kind = stored_kind if stored.get("value") else None
    return ((answer.get("value"), answer.get("note"), asked_kind)
            != (stored.get("value"), stored.get("note"), recorded_kind))


def _auto_resume(run_dir: Path, to: str) -> None:
    """Move an ``awaiting_data`` run to ``collecting`` once a close leaves no request open."""
    if to not in _OPEN and not open_requests(run_dir) and runstate.can(run_dir, "auto_resume"):
        runstate.apply(run_dir, "auto_resume")


def _move_request(run_dir: Path, doc: dict, item: dict, to: str, answer: dict | None) -> Updated:
    request_id = item["id"]
    _require_move(REQUEST_TRANSITIONS, item["status"], to)
    if to == "answered" or answer:
        _require_answer_status(request_id, to)
        if not answer:
            raise _rejected(f"requests.{request_id}.answer", "answer_required", "an answered request needs a value or a note")
        value, kind = answer.get("value"), answer.get("evidence_kind")
        if value and kind is None:
            raise _rejected(f"requests.{request_id}.answer.evidence_kind", "evidence_required",
                             "an answer with a value needs an evidence kind: measured or judgement")
        item["answer"] = {**({"value": value} if value else {}),
                          **({"note": answer["note"]} if answer.get("note") else {}),
                          "received_at": workspace.utc_now()}
        if value:
            doc["candidates"].append(_new_candidate(
                doc, item["parameter_path"], value, kind, f"request:{request_id}", None))
    item["status"] = to
    _save(run_dir, doc)
    _auto_resume(run_dir, to)
    return Updated(item, True)


def add_candidate(run_dir: Path, *, parameter_path: str, value: dict, evidence_kind: str, origin: str,
                  link: str | None = None) -> Added | Duplicate:
    with runstate.locked(run_dir):
        runstate.check_editable(run_dir, "add a candidate")
        doc = load(run_dir)
        for cand in doc["candidates"]:
            same_key = (cand.get("link") == link) if link else (cand["origin"] == origin and "link" not in cand)
            if cand["parameter_path"] == parameter_path and same_key:
                return Duplicate(cand)
        item = _new_candidate(doc, parameter_path, value, evidence_kind, origin, link)
        doc["candidates"].append(item)
        _save(run_dir, doc)
        return Added(item)


def _source_for(candidate: dict, doc: dict) -> dict:
    kind, _, name = candidate["origin"].partition(":")
    measured = candidate["evidence_kind"] == "measured"
    if kind == "request":
        request = _find(doc["requests"], name)
        role = request["target"]["owner_role"] if request else "the data owner"
        source = {"kind": "person", "title": f"Answer to {name} from {role}", "owner_role": role}
    else:
        source = {"kind": "internal_system" if measured else "person", "title": f"Finding via {name}"}
    if candidate.get("link", "").startswith("https://"):
        source["url"] = candidate["link"]
    return {"id": candidate["id"], **source, "retrieved_at": workspace.utc_now()[:10]}


def confirm_candidate(run: workspace.Run, candidate_id: str) -> Confirmed:
    """Write the value into ``inputs.yaml`` first, then mark the candidate confirmed.

    A crash between the two writes leaves a candidate that is still pending; a
    retry rewrites the same value and source row, so it is safe. The value is validated
    against the run's own workspace library. A parameter takes one confirmed candidate: a
    second is refused (exit 3) until it is rejected, so no confirmed candidate goes stale.
    """
    with runstate.locked(run.dir):
        runstate.check_editable(run.dir, "confirm a candidate")
        return _confirm(run, candidate_id)


def _confirm(run: workspace.Run, candidate_id: str) -> Confirmed:
    run_dir = run.dir
    doc = load(run_dir)
    cand = _get(doc["candidates"], candidate_id)
    inputs_path = run_dir / "inputs.yaml"
    if cand["status"] == "confirmed":
        return Confirmed(cand, inputs_path)
    _require_move(CANDIDATE_TRANSITIONS, cand["status"], "confirmed")
    holder = next((c for c in doc["candidates"]
                   if c["status"] == "confirmed" and c["parameter_path"] == cand["parameter_path"]), None)
    if holder:
        raise IllegalTransition([issue(
            f"candidates.{candidate_id}.status", "already_confirmed",
            f"{holder['id']} is already confirmed for {cand['parameter_path']}; reject {candidate_id}, "
            f"or edit that estimate in inputs.yaml")])
    inputs, issues = schemas.load_yaml(inputs_path, "inputs") if inputs_path.is_file() else (None, [])
    if issues:
        raise Rejected(issues)
    if not isinstance(inputs, dict):
        raise Rejected([validate.missing_document(inputs_path)])
    block, _, key = cand["parameter_path"].partition(".")
    estimate = inputs.get("parameters", {}).get(block, {}).get(key)
    if not isinstance(estimate, dict):
        raise _rejected(f"inputs.parameters.{cand['parameter_path']}", "unknown_estimate",
                         f"the baseline has no estimate at {cand['parameter_path']}")
    tier = tiers.EVIDENCE_TIER[cand["evidence_kind"]]
    inputs["parameters"][block][key] = {
        **({"label": estimate["label"]} if "label" in estimate else {}), **cand["value"],
        "provenance": {"tier": tier, "source_ids": [cand["id"]]}}
    source = _source_for(cand, doc)
    inputs["sources"] = [s for s in inputs["sources"] if s["id"] != source["id"]] + [source]
    issues = validate.validate_inputs(inputs, entry_lookup=library.entry_lookup(run.workspace))
    if issues:
        raise Rejected(issues)
    workspace.write_yaml(inputs_path, inputs)
    cand["status"] = "confirmed"
    _save(run_dir, doc)
    return Confirmed(cand, inputs_path)


def reject_candidate(run_dir: Path, candidate_id: str) -> Updated:
    with runstate.locked(run_dir):
        runstate.check_editable(run_dir, "reject a candidate")
        doc = load(run_dir)
        cand = _get(doc["candidates"], candidate_id)
        if cand["status"] == "rejected":
            return Updated(cand, False)
        _require_move(CANDIDATE_TRANSITIONS, cand["status"], "rejected")
        cand["status"] = "rejected"
        _save(run_dir, doc)
        return Updated(cand, True)
