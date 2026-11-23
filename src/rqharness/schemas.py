"""JSON Schema documents: discovery, loading, and schema errors as issues.

Schemas are discovered by file name (``schemas/<kind>.v<major>.json``), so a later
slice registers a new document kind by dropping a schema file in that folder.
This module is a leaf: it imports nothing of the harness but the issue shape
(:mod:`rqharness.outcomes`) and the YAML reader, so both the library and the cross-reference validator can use it.
"""

from __future__ import annotations

import functools
import json
import re
from importlib import resources
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from rqharness.outcomes import Issue, issue
from rqharness.workspace import parse_yaml

_SCHEMA_FILE = re.compile(r"^(?P<kind>.+)\.v(?P<major>\d+)\.json$")


def _schema_dir():
    return resources.files("rqharness") / "schemas"


def _schema_files() -> list[tuple[str, str]]:
    found = []
    for entry in _schema_dir().iterdir():
        match = _SCHEMA_FILE.match(entry.name)
        if match:
            found.append((match["kind"], match["major"]))
    return sorted(found)


def known_kinds() -> list[str]:
    return sorted({kind for kind, _ in _schema_files()})


@functools.lru_cache(maxsize=None)
def load_schema(kind: str, major: str = "1") -> dict:
    return json.loads((_schema_dir() / f"{kind}.v{major}.json").read_text(encoding="utf-8"))


def _path(stem: str, parts) -> str:
    return ".".join([stem, *(str(p) for p in parts)])


def load_yaml(path: Path, stem: str) -> tuple[object | None, list[Issue]]:
    """:func:`parse_document` of the file.

    A missing file reads as ``(None, [])``, like an empty one: callers that must tell the two
    apart check ``path.is_file()`` first.
    """
    return parse_document(path.read_bytes(), stem) if path.is_file() else (None, [])


def parse_document(data: bytes, stem: str) -> tuple[object | None, list[Issue]]:
    """:func:`workspace.parse_yaml`, with malformed YAML as an issue at ``<stem>.document``."""
    try:
        return parse_yaml(data), []
    except yaml.YAMLError as exc:
        return None, [issue(_path(stem, ["document"]), "yaml", f"malformed YAML: {exc}")]


def validate_document(kind: str, data: object, *, stem: str | None = None) -> list[Issue]:
    """Schema errors for one document; an unknown major version is the only issue reported."""
    stem = stem or kind
    majors = sorted(m for k, m in _schema_files() if k == kind)
    version = data.get("schema_version") if isinstance(data, dict) else None
    if isinstance(version, str) and version.split(".")[0] not in majors:
        return [issue(_path(stem, ["schema_version"]), "unknown_major_version",
                      f"schema_version {version!r} is not supported; known major versions: {', '.join(majors)}")]
    validator = Draft202012Validator(load_schema(kind, majors[0] if version is None else version.split(".")[0]))
    issues: list[Issue] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: ([str(p) for p in e.absolute_path], str(e.validator))):
        base = list(err.absolute_path)
        rule, message = err.validator, err.message
        if err.validator == "required":
            targets = [base + [name] for name in err.validator_value if name not in err.instance]
        elif err.validator == "additionalProperties":
            allowed = err.schema.get("properties", {})
            targets = [base + [name] for name in err.instance if name not in allowed]
        else:
            targets = [base]
        if err.validator == "not" and err.validator_value == {}:  # `{"not": {}}` is the schemas' "forbidden"
            rule, message = "forbidden", "is not allowed here"
        for target in targets:
            issues.append(issue(_path(stem, target), rule, message))
    return list({(i["path"], i["rule"]): i for i in issues}.values())
