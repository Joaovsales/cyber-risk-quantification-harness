from __future__ import annotations

import ast
import io
import http.client
import json
import urllib.error
from pathlib import Path

import pytest

from rqharness import cli, search

SRC = Path(__file__).resolve().parents[2] / "src" / "rqharness"
NETWORK_MODULES = {"urllib", "http", "socket", "ssl", "requests", "httpx", "aiohttp", "urllib3", "ftplib",
                   "smtplib", "poplib", "imaplib", "xmlrpc", "asyncio", "webbrowser", "subprocess"}

PAYLOAD = {
    "answer": "A short answer.",
    "results": [
        {"title": "Good", "url": "https://example.org/a", "content": "text", "score": 0.9},
        {"title": "Plain http", "url": "http://example.org/b", "content": "x", "score": 0.5},
        {"title": "No url", "content": "x", "score": 0.1},
    ],
}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def stub(monkeypatch):
    calls: list[dict] = []

    def install(body=PAYLOAD, error=None):
        def fake_urlopen(req, timeout=None):
            calls.append({"req": req, "timeout": timeout})
            if error is not None:
                raise error
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            return _Response(raw)

        monkeypatch.setattr(search._OPENER, "open", fake_urlopen)
        return calls

    return install


def test_search_json_with_key(stub, monkeypatch, capsys):
    calls = stub()
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    code = cli.main(["search", "ransomware cost", "--max-results", "3", "--depth", "advanced", "--json"])
    assert code == 0
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is True
    data = env["data"]
    assert data["query"] == "ransomware cost"
    assert data["answer"] == "A short answer."
    assert data["results"] == [
        {"title": "Good", "url": "https://example.org/a", "content": "text", "score": 0.9}
    ]
    sent = json.loads(calls[0]["req"].data)
    assert sent["max_results"] == 3 and sent["search_depth"] == "advanced"
    assert calls[0]["req"].get_header("Authorization") == "Bearer tvly-secret"


def test_default_timeout_is_60(stub):
    calls = stub()
    search.search("q", api_key="k")
    assert calls[0]["timeout"] == 60


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_exit_2(value, stub, monkeypatch, capsys):
    calls = stub()
    if value is None:
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    else:
        monkeypatch.setenv("TAVILY_API_KEY", value)
    code = cli.main(["search", "q", "--json"])
    assert code == 2
    env = json.loads(capsys.readouterr().out)
    assert env["issues"][0]["path"] == "env.TAVILY_API_KEY"
    assert env["issues"][0]["rule"] == "missing"
    assert calls == []


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError("https://x", 401, "Unauthorized", {}, io.BytesIO(b"bad tvly-secret")),
        urllib.error.URLError("boom tvly-secret"),
        TimeoutError("timed out tvly-secret"),
        http.client.RemoteDisconnected("closed tvly-secret"),
    ],
)
def test_network_faults_exit_1_without_key(error, stub, monkeypatch, capsys):
    stub(error=error)
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    code = cli.main(["search", "q", "--json"])
    assert code == 1
    out = capsys.readouterr().out
    env = json.loads(out)
    assert env["issues"][0]["path"] == "search"
    assert env["issues"][0]["rule"] == "network"
    assert "tvly-secret" not in out


def test_invalid_json_raises_search_error(stub):
    stub(body=b"not json")
    with pytest.raises(search.SearchError):
        search.search("q", api_key="k")


def test_search_writes_nothing(stub, monkeypatch, tmp_path):
    stub()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    assert cli.main(["search", "q", "--json"]) == 0
    assert list(tmp_path.iterdir()) == []


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def test_only_search_module_networks():
    offenders = {
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if _imported_roots(p) & NETWORK_MODULES
    }
    assert offenders == {"search.py"}


def test_a_redirect_is_refused_so_the_key_never_follows_it():
    request = search.urllib.request.Request("https://api.tavily.com/search", headers={"Authorization": "Bearer k"})
    handler = next(h for h in search._OPENER.handlers if isinstance(h, search._NoRedirect))
    assert handler.redirect_request(request, None, 302, "Found", {}, "http://elsewhere.example/") is None
