"""The harness's one failure model: the issue shape and the five kinds of domain failure.

A domain function returns its success value and *raises* one of the kinds below when it
cannot deliver it; each kind carries the issues that say why. Which exit code a kind means is
the command line's business: ``cli.EXIT_CODES`` is the only mapping, and ``cli.main`` the only
handler. This module is a leaf, so every module can raise a kind without knowing the CLI.
"""

from __future__ import annotations

from typing import TypedDict


class Issue(TypedDict):
    path: str
    rule: str
    message: str


def issue(path: str, rule: str, message: str) -> Issue:
    return {"path": path, "rule": rule, "message": message}


class DomainError(Exception):
    """A failure a caller is expected to report, not a bug; ``issues`` name every reason."""

    def __init__(self, issues: list[Issue]):
        if type(self) is DomainError:
            raise TypeError("raise one of the DomainError kinds, not DomainError itself")
        if not issues:
            raise ValueError(f"{type(self).__name__} needs at least one issue")
        super().__init__("; ".join(i["message"] for i in issues))
        self.issues = list(issues)


class Rejected(DomainError):
    """A document or value breaks a rule; issues name every dotted field path."""


class Usage(DomainError):
    """A command-line argument or environment value is unusable as given (``argv.*``, ``env.*``)."""


class IllegalTransition(DomainError):
    """The status of a run, request or candidate does not allow the change asked for."""


class NarrativeRejected(DomainError):
    """The report narrative states a figure outside its placeholders."""


class NotFound(DomainError):
    """A required workspace, run, version, file or item does not exist."""
