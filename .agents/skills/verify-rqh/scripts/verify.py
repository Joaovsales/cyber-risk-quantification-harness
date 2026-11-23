#!/usr/bin/env python3
"""Drive the real `rqh` command on the sample run and check the report it writes.

Subcommands (all print one JSON object on stdout; exit 0 only when every check passes):

  doctor                     read-only: this checkout's rqh, Python deps, browser, design hash
  run [--route R] [--n N] [--seed S] [--out DIR] [--profile FILE]
                             fresh workspace -> init, copy sample, validate, run confirm,
                             finalize, report (twice), status; static report checks;
                             headless screenshots when Edge or Chrome is installed
  serve RUN_DIR              start a static server for RUN_DIR/evidence on a free port
  cleanup RUN_DIR            stop the server this run started; delete RUN_DIR/ws, profile-* and
                             mobile-frame.html; keep evidence

Every rqh call runs `python -m rqharness` from THIS checkout (PYTHONPATH=<repo>/src) inside
RUN_DIR/ws, so concurrent runs never share a workspace.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html.parser
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SAMPLE = REPO / "tests" / "validate" / "fixtures" / "sample-run"
RUN_ID = "credential-phishing-bec"
CONCEPT_SHA256 = "525413fd8e98234793d2383f73c71ff0fe3af695b09f8834540075cbc2654ac7"
# The one inline script is allowed by its own SHA-256; {script} is filled from the page itself.
CSP = ("default-src 'none'; img-src data:; style-src 'unsafe-inline'; script-src {script}; "
       "base-uri 'none'; form-action 'none'")
SECTIONS = ["takeaway", "summary", "lec", "distribution", "drivers", "variants", "scenario",
            "provenance", "appendix", "collect"]
SIZE_BUDGET = 1_000_000
FRAME_NAME = "mobile-frame.html"  # the 375 px iframe page `run` writes for the phone screenshot
TITLE_SUFFIX = "/ risk report"
SECTION_NUMBERS = [f"{i:02d}" for i in range(1, 10)]
COLLECT_LABELS = {"System of record", "Owner"}
SAMPLE_CHARTS = 4  # the sample's LEC plus one histogram for each of its three variants
SAMPLE_REQUESTS = 3  # the sample's "What to collect" requests
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def default_out() -> Path:
    return Path(os.environ.get("RQH_VERIFY_OUT") or Path(tempfile.gettempdir()) / "rqh-verify")


def find_browser() -> str | None:
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return next((p for p in BROWSERS if Path(p).is_file()), None)


def rqh(args: list[str], cwd: Path) -> dict:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    env.pop("RQH_WORKSPACE", None)  # the workspace is always cwd/.riskquant
    proc = subprocess.run([sys.executable, "-m", "rqharness", *args, "--json"], cwd=cwd, env=env,
                          capture_output=True, text=True, encoding="utf-8")
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        envelope = None
    return {"argv": ["rqh", *args, "--json"], "exit": proc.returncode, "envelope": envelope,
            "stderr": proc.stderr[-2000:]}


class _Scan(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.csp: list[str] = []
        self.sections: list[tuple[str, str, dict]] = []
        self.external: list[str] = []
        self.svg_img = 0
        self.scripts_with_src = 0
        self.links = 0
        self.title: str | None = None  # the page <title>, not the <title> of an SVG mark
        self.sec_no: list[str] = []
        self.org: str | None = None  # the masthead badge an org profile adds
        self.histograms = 0
        self.collect: list[set[str]] = []  # the <dt> labels of each "What to collect" request
        self._text: str | None = None  # the element whose text is being read: title, sec-no or dt
        self._buffer = ""
        self._svg_depth = 0
        self._in_ck = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        classes = a.get("class", "").split()
        if tag == "svg":
            self._svg_depth += 1
        if tag == "title" and not self._svg_depth and self.title is None:
            self._read("title")
        if tag == "span" and "sec-no" in classes:
            self._read("sec-no")
        if tag == "span" and "org" in classes:
            self._read("org")
        if tag == "div" and "hist" in classes and "data-variant" in a:
            self.histograms += 1
        if tag == "li" and "ck" in classes:
            self.collect.append(set())
            self._in_ck = True
        if tag == "dt" and self._in_ck:
            self._read("dt")
        if tag == "meta" and a.get("http-equiv", "").lower() == "content-security-policy":
            self.csp.append(a.get("content", ""))
        if "data-section" in a:
            self.sections.append((a["data-section"], tag, a))
        if tag == "svg" and a.get("role") == "img":
            self.svg_img += 1
        if tag == "script" and "src" in a:
            self.scripts_with_src += 1
        if tag == "link":
            self.links += 1
        for key in ("src", "srcset", "href", "xlink:href"):
            value = a.get(key, "").strip().lower()
            if value.startswith(("http:", "//")) or (value.startswith("https:") and not (tag == "a" and key == "href")):
                self.external.append(f"<{tag} {key}={a[key]}>")

    def _read(self, what: str) -> None:
        self._text, self._buffer = what, ""

    def handle_data(self, data: str) -> None:
        if self._text:
            self._buffer += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "svg":
            self._svg_depth -= 1
        if tag == "li":
            self._in_ck = False
        if self._text and tag == {"title": "title", "sec-no": "span", "org": "span", "dt": "dt"}[self._text]:
            text = self._buffer.strip()
            if self._text == "title":
                self.title = text
            elif self._text == "org":
                self.org = text
            elif self._text == "sec-no":
                self.sec_no.append(text)
            else:
                self.collect[-1].add(text)
            self._text = None


def check_report(path: Path, route: str, *, charts: int | None = None, requests: int | None = None) -> list[dict]:
    """The static checks of one report; ``charts`` and ``requests`` pin exact counts (`run` pins the sample's).

    Without them the charts must still be the LEC plus one per histogram, and every request must
    name an owner and a system of record.
    """
    text = path.read_text(encoding="utf-8")
    scan = _Scan()
    scan.feed(text)
    order = [s[0] for s in scan.sections]
    appendix = next((s for s in scan.sections if s[0] == "appendix"), None)
    styles = " ".join(re.findall(r"<style[^>]*>(.*?)</style>", text, flags=re.S))
    urls = re.findall(r"url\(\s*['\"]?([^)'\"]+)", styles)
    banner = "Not yet validated" in text
    scripts = re.findall(r"<script>(.*?)</script>", text, flags=re.S)
    digests = [base64.b64encode(hashlib.sha256(js.encode("utf-8")).digest()).decode("ascii") for js in scripts]
    expected_csp = CSP.format(script=f"'sha256-{digests[0]}'" if len(digests) == 1 else "'none'")

    def row(name: str, ok: bool, detail: object) -> dict:
        return {"check": name, "pass": bool(ok), "detail": detail}

    return [
        row("csp_meta_exact", scan.csp == [expected_csp], {"page": scan.csp, "expected": expected_csp}),
        row("section_order", order == SECTIONS, order),
        row("appendix_collapsed", appendix is not None and appendix[1] == "details" and "open" not in appendix[2],
            appendix[1] if appendix else None),
        row("yolo_banner_matches_route", banner == (route == "yolo"), {"route": route, "banner": banner}),
        row("size_budget", path.stat().st_size <= SIZE_BUDGET, path.stat().st_size),
        row("no_external_refs", not scan.external and scan.links == 0 and scan.scripts_with_src == 0,
            scan.external[:5]),
        row("no_css_import_or_remote_url", "@import" not in styles and all(u.startswith("data:") for u in urls),
            [u for u in urls if not u.startswith("data:")][:5]),
        row("static_charts_present", scan.histograms >= 1 and scan.svg_img == 1 + scan.histograms
            and (charts is None or scan.svg_img == charts), {"svg_img": scan.svg_img, "histograms": scan.histograms}),
        row("section_numbers", scan.sec_no == SECTION_NUMBERS, scan.sec_no),
        row("title_suffix", (scan.title or "").endswith(TITLE_SUFFIX), scan.title),
        row("collect_requests", bool(scan.collect) and all(COLLECT_LABELS <= labels for labels in scan.collect)
            and (requests is None or len(scan.collect) == requests),
            {"requests": len(scan.collect), "labels": [sorted(labels) for labels in scan.collect]}),
    ]


def check_profile(report: Path, profile: Path) -> dict:
    """Whether the report's masthead badge is the org profile's display name (the theme's, else the org name).

    The badge, not the page text: a scenario can name the organisation without any profile.
    """
    import yaml  # from the venv; doctor checks that it imports

    data = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    name = (data.get("theme") or {}).get("display_name") or data.get("org_name")
    scan = _Scan()
    scan.feed(report.read_text(encoding="utf-8"))
    return {"check": "profile_applied", "pass": bool(name) and scan.org == name,
            "detail": {"display_name": name, "badge": scan.org}}


def screenshot(browser: str, url: str, target: Path, width: int, height: int, profile: Path) -> bool:
    try:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--user-data-dir={profile}", f"--window-size={width},{height}",
                        "--virtual-time-budget=3000", f"--screenshot={target}", url],
                       capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        pass  # under load the launcher can outlive the PNG it wrote; the poll below decides
    # msedge.exe on Windows is a launcher that exits before the headless child writes the file
    last = -1
    for _ in range(600):
        size = target.stat().st_size if target.is_file() else -1
        if size > 0 and size == last:
            return True
        last = size
        time.sleep(0.25)
    return False


def cmd_doctor(_: argparse.Namespace) -> int:
    probe = subprocess.run([sys.executable, "-c", "import rqharness, numpy, scipy, jinja2, jsonschema, yaml;"
                            "print(rqharness.__file__, rqharness.__version__)"],
                           env={**os.environ, "PYTHONPATH": str(REPO / "src")}, capture_output=True, text=True)
    module_path, _, version = probe.stdout.strip().rpartition(" ")
    concept = REPO / "design" / "concepts" / "report.html"
    checks = [
        {"check": "python", "pass": sys.version_info >= (3, 11), "detail": sys.version.split()[0]},
        {"check": "rqharness_from_this_checkout", "pass": probe.returncode == 0
         and Path(module_path).resolve().is_relative_to((REPO / "src").resolve()), "detail": probe.stdout.strip() or probe.stderr[-300:]},
        {"check": "sample_run_present", "pass": (SAMPLE / "scenario.yaml").is_file() and (SAMPLE / "inputs.yaml").is_file(),
         "detail": str(SAMPLE)},
        {"check": "concept_unchanged", "pass": concept.is_file()
         and hashlib.sha256(concept.read_bytes()).hexdigest() == CONCEPT_SHA256, "detail": str(concept)},
    ]
    ok = all(c["pass"] for c in checks)
    info = {"headless_browser": find_browser() or "none (screenshots will be skipped)"}
    print(json.dumps({"ok": ok, "repo": str(REPO), "version": version, "checks": checks, "info": info}, indent=2))
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    run_dir = Path(args.out) / f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"
    ws, evidence = run_dir / "ws", run_dir / "evidence"
    ws.mkdir(parents=True)
    evidence.mkdir()
    steps: list[dict] = []

    def step(name: str, argv: list[str]) -> dict:
        result = rqh(argv, ws)
        result["name"] = name
        result["pass"] = result["exit"] == 0 and result["envelope"] is not None
        steps.append(result)
        return result

    step("init", ["init"])
    if args.profile:
        shutil.copy2(args.profile, ws / ".riskquant" / "org-profile.yaml")  # theme, people and systems
    shutil.copytree(SAMPLE, ws / ".riskquant" / "runs" / RUN_ID)
    step("validate", ["validate", RUN_ID])
    step("run_confirm", ["run", "confirm", RUN_ID, "--route", args.route, "--n", str(args.n), "--seed", str(args.seed)])
    fin = step("finalize", ["finalize", RUN_ID])
    first = step("report", ["report", RUN_ID])
    report = ws / ".riskquant" / "runs" / RUN_ID / "v1" / "report.html"
    checks: list[dict] = []
    if report.is_file():
        once = report.read_bytes()
        step("report_again", ["report", RUN_ID])
        checks.append({"check": "render_idempotent", "pass": report.read_bytes() == once, "detail": len(once)})
        shutil.copy2(report, evidence / "report.html")
        checks += check_report(report, args.route, charts=SAMPLE_CHARTS, requests=SAMPLE_REQUESTS)
    else:
        checks.append({"check": "report_written", "pass": False, "detail": str(report)})
    status = step("status", ["status", RUN_ID])
    data = (status["envelope"] or {}).get("data") or {}
    checks.append({"check": "status_second_view", "pass": data.get("latest_version") == 1
                   and data.get("next_skill") is None and data.get("status") == "finalized",
                   "detail": {k: data.get(k) for k in ("status", "latest_version", "next_skill", "reason")}})
    fdata = (fin["envelope"] or {}).get("data") or {}
    checks.append({"check": "finalize_n_seed", "pass": fdata.get("n") == args.n and fdata.get("seed") == args.seed,
                   "detail": {"n": fdata.get("n"), "seed": fdata.get("seed")}})
    if args.profile and report.is_file():
        checks.append(check_profile(report, Path(args.profile)))
    # the CLI evidence is on disk before any browser starts, so a browser fault cannot lose it
    (evidence / "steps.json").write_text(json.dumps(steps, indent=2), encoding="utf-8")

    shots = {}
    browser = find_browser()
    if browser and report.is_file():
        # Headless Chromium will not lay out narrower than about 500 px, so the phone view is a 375 px iframe.
        frame = run_dir / FRAME_NAME
        frame.write_text('<!doctype html><body style="margin:0;background:#888">'
                         f'<iframe src="{(evidence / "report.html").resolve().as_uri()}" width="375" height="2400" '
                         'style="border:0;display:block"></iframe></body>', encoding="utf-8")
        targets = {"desktop-1280": ((evidence / "report.html").resolve().as_uri(), 1280, 6400),
                   "mobile-375": (frame.resolve().as_uri(), 520, 2400)}
        try:
            for label, (url, w, h) in targets.items():
                target = evidence / f"report-{label}.png"
                shots[label] = str(target) if screenshot(browser, url, target, w, h, run_dir / f"profile-{label}") else None
        finally:
            frame.unlink(missing_ok=True)
    ok = all(s["pass"] for s in steps) and all(c["pass"] for c in checks)
    summary = {"ok": ok, "run_dir": str(run_dir), "evidence": str(evidence), "report": str(evidence / "report.html"),
               "steps": [{k: s[k] for k in ("name", "exit", "pass")} for s in steps],
               "checks": checks, "screenshots": shots or "skipped (no headless browser)"}
    (evidence / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if ok else 1


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cmd_serve(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    evidence = run_dir / "evidence"
    if not (evidence / "report.html").is_file():
        print(json.dumps({"ok": False, "error": f"no report in {evidence}"}))
        return 1
    port = _free_port()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                             "--directory", str(evidence)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=flags, start_new_session=os.name != "nt")
    (run_dir / "server.pid").write_text(str(proc.pid), encoding="utf-8")
    url = f"http://127.0.0.1:{port}/report.html"
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.1)
    print(json.dumps({"ok": proc.poll() is None, "url": url, "pid": proc.pid}))
    return 0 if proc.poll() is None else 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    run_dir = Path(args.run_dir)
    stopped = None
    pid_file = run_dir / "server.pid"
    if pid_file.is_file():
        pid = int(pid_file.read_text(encoding="utf-8"))
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.kill(pid, signal.SIGTERM)
            stopped = pid
        except OSError:
            stopped = f"{pid} (already gone)"
        pid_file.unlink()
    for owned in [run_dir / "ws", *run_dir.glob("profile-*")]:
        shutil.rmtree(owned, ignore_errors=True)
    (run_dir / FRAME_NAME).unlink(missing_ok=True)  # left only by a run that crashed while taking screenshots
    kept = sorted(p.name for p in (run_dir / "evidence").glob("*")) if (run_dir / "evidence").is_dir() else []
    print(json.dumps({"ok": not (run_dir / "ws").exists(), "server_stopped": stopped, "evidence_kept": kept}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="verify.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    run = sub.add_parser("run")
    run.add_argument("--route", choices=["yolo", "accuracy"], default="yolo")
    run.add_argument("--n", type=int, default=50_000)
    run.add_argument("--seed", type=int, default=20261109)
    run.add_argument("--out", default=str(default_out()))
    run.add_argument("--profile", help="org profile YAML to install before finalize (e.g. tests/routing/fixtures/org-profile.yaml)")
    run.set_defaults(fn=cmd_run)
    for name, fn in (("serve", cmd_serve), ("cleanup", cmd_cleanup)):
        p = sub.add_parser(name)
        p.add_argument("run_dir")
        p.set_defaults(fn=fn)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
