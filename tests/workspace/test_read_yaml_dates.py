"""workspace.read_yaml and schemas.load_yaml must agree: bare YAML dates come back as ISO strings."""

from __future__ import annotations

import ast
from pathlib import Path

import rqharness
from rqharness import schemas, workspace


def test_read_yaml_turns_bare_dates_into_iso_strings(tmp_path):
    path = tmp_path / "doc.yaml"
    path.write_text("retrieved_at: 2026-11-09\nnested: [{at: 2026-01-02T03:04:05Z}]\n", encoding="utf-8")
    data = workspace.read_yaml(path)
    assert data == {"retrieved_at": "2026-11-09", "nested": [{"at": "2026-01-02T03:04:05+00:00"}]}
    assert data == schemas.load_yaml(path, "doc")[0]


def test_init_writes_gitignore_into_an_existing_uninitialised_folder(tmp_path):
    root = tmp_path / ".riskquant"
    root.mkdir()
    (root / "org-profile.yaml").write_text("schema_version: '1'\n", encoding="utf-8")
    workspace.init_workspace(root)
    assert (root / ".gitignore").read_text(encoding="utf-8") == "*\n"


def _rqh_imports(module: str) -> set[str]:
    tree = ast.parse((Path(rqharness.__file__).parent / module).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found |= {f"{node.module}.{a.name}" for a in node.names} if node.module == "rqharness" else {node.module}
    return {name for name in found if name.startswith("rqharness")}


def test_schemas_is_a_leaf_that_library_and_validate_share():
    assert _rqh_imports("schemas.py") <= {"rqharness.outcomes", "rqharness.workspace"}
    assert "rqharness.validate" not in _rqh_imports("library.py")  # the old library -> validate edge is gone
    assert "rqharness.schemas" in _rqh_imports("library.py") & _rqh_imports("validate.py")


def test_load_yaml_reports_malformed_yaml_as_an_issue(tmp_path):
    path = tmp_path / "doc.yaml"
    path.write_text("a: [unclosed\n", encoding="utf-8")
    data, issues = schemas.load_yaml(path, "doc")
    assert data is None and [(i["path"], i["rule"]) for i in issues] == [("doc.document", "yaml")]
