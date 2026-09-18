"""
End-to-end UI test (Playwright over the installed Chrome, headless).

    python -m scripts.ui_test [--headed] [--out DIR]

Stands up its own backend (a fresh demo database from the walkthrough, port
8013) and a Vite dev server per role, then drives every screen as that role:
navigates, screenshots, asserts the text a person would look for, performs
the writes a role may perform, and fails on any console error or failed API
request. Screenshots and a JSON report land in --out (default: ../ui-report).

Roles and what each is driven through:
  director  every screen; intake create; review approve/reject; stage move;
            import dry run; analyses; findings; run compare; notices; ask
  owner     intake create; the screens an owner may not use are absent
  manager   the review queue in-region; a lifecycle approval
  finance   targets entered; coverage lights up; roll-ups; ROI feed export
  admin     rubric publish/feedback; users provisioning; connectors dry run;
            access; no pipeline data
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # backend/
FRONTEND = ROOT.parent / "frontend"
BACKEND_PORT = 8013
# Stage two: the real sign-in (AUTH_MODE=local) on its own backend and app.
AUTH_BACKEND_PORT = 8014
AUTH_APP_PORT = 5190
DEMO_PASSWORD = "OppTrack-2026!"
API = f"http://127.0.0.1:{BACKEND_PORT}/api/v1"

# Own ports, away from scripts/dev_up.ps1 (8000, 5181-5185): the harness must
# never drive the live dev stack and write test data into its database.
ROLE_PORTS = {"director": 5191, "owner": 5192, "manager": 5193, "finance": 5194, "admin": 5195}
ACTORS = {"director": "marc", "owner": "owner-korea", "manager": "kim", "finance": "cfo", "admin": "root"}


def assert_free(port: int) -> None:
    with socket.socket() as s:
        s.settimeout(1)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise SystemExit(f"port {port} is already in use -- refusing to test against something else's server")


def wait_port(port: int, timeout: float = 120) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"port {port} did not open")


def start_backend(db_path: Path, log: Path, port: int = BACKEND_PORT, auth_mode: str = "headers") -> subprocess.Popen:
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}", "JUDGMENT_MODE": "mock",
           "REDIS_BACKEND": "fake", "STORAGE_BACKEND": "local", "NOTIFICATION_CHANNEL": "log",
           "AUTH_MODE": auth_mode, "OTP_DELIVERY": "console"}
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT)
    wait_port(port)
    return proc


def start_frontend(role: str, log: Path, port: int | None = None, api: str = API) -> subprocess.Popen:
    port = port or ROLE_PORTS[role]
    env = {**os.environ, "VITE_API_BASE": api, "VITE_OPPTRACK_ROLE": role, "VITE_OPPTRACK_ACTOR": ACTORS[role],
           "VITE_OPPTRACK_REGIONS": "Korea" if role == "manager" else "*"}
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    proc = subprocess.Popen([npx, "vite", "--port", str(port), "--strictPort", "--host", "127.0.0.1"],
                            cwd=FRONTEND, env=env, stdout=log.open("w"), stderr=subprocess.STDOUT, shell=False)
    wait_port(port)
    time.sleep(1.5)
    return proc


def stop(proc: subprocess.Popen) -> None:
    """Kill the whole tree: on Windows terminate() reaches the npx shell but
    not the node child that actually holds the port."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class Report:
    def __init__(self, out: Path):
        self.out = out
        self.results: list[dict] = []
        self.console: list[str] = []
        self.failed_requests: list[str] = []

    def step(self, role: str, name: str, ok: bool, detail: str = "") -> None:
        self.results.append({"role": role, "step": name, "ok": ok, "detail": detail})
        print(f"[{role:8}] {'PASS' if ok else 'FAIL'}  {name}{(' -- ' + detail) if detail else ''}")


def run_role(pw, role: str, report: Report, headed: bool) -> None:
    from playwright.sync_api import expect

    port = ROLE_PORTS[role]
    browser = pw.chromium.launch(channel="chrome", headless=not headed)
    page = browser.new_page(viewport={"width": 1440, "height": 960})
    page.on("console", lambda m: report.console.append(f"[{role}] {m.type}: {m.text}") if m.type == "error" else None)
    page.on("response", lambda r: report.failed_requests.append(f"[{role}] {r.status} {r.request.method} {r.url}")
            if (r.url.startswith(API) and r.status >= 500) or (r.status == 404 and "/api/" in r.url) else None)
    page.on("response", lambda r: report.console_errors.append(f"[{role}] 404 {r.url}") if r.status == 404 and "/api/" not in r.url else None)
    shots = report.out / role
    shots.mkdir(parents=True, exist_ok=True)

    def nav(label: str, shot: str | None = None):
        page.click(f"nav.sidebar-nav button[title='{label}']")
        page.wait_for_timeout(700)
        page.screenshot(path=str(shots / f"{shot or label.lower().replace(' ', '-').replace('&', 'and')}.png"), full_page=True)

    def check(name: str, condition: bool, detail: str = ""):
        report.step(role, name, bool(condition), detail)

    page.goto(f"http://127.0.0.1:{port}/")
    page.wait_for_selector("nav.sidebar-nav")
    page.wait_for_timeout(1200)
    page.screenshot(path=str(shots / "dashboard.png"), full_page=True)
    visible = [b.get_attribute("title") for b in page.query_selector_all("nav.sidebar-nav button.nav-item")]
    check("dashboard loads", page.is_visible("text=Dashboard"))
    page.wait_for_selector("[data-testid='profile-card'] strong", timeout=15000)
    profile = page.inner_text("[data-testid='profile-card']")
    check("sidebar profile shows actor, role and headers",
          ACTORS[role] in profile and "X-OppTrack-Role: " + role in profile, profile.replace(chr(10), " | "))
    check(f"nav for {role}", True, ", ".join(v for v in visible if v not in ("Close sidebar", "Open sidebar")))

    if role == "director":
        check("role landing: director", page.is_visible("text=All regions"))
        check("landing shows proposals waiting", page.is_visible("text=proposal(s) waiting for you"))

        nav("Pipeline")
        check("pipeline lists the nine rows", page.is_visible("text=Hermes") and page.is_visible("text=Yellowstone"))

        nav("Intake")
        page.fill("label:has-text('Region') input", "Korea")
        page.fill("label:has-text('Customer') >> nth=0 >> input", "SLM")
        page.fill("label:has-text('End customer') input", "GM")
        page.fill("label:has-text('Project') input", "UI-Test-Row")
        page.fill("label:has-text('Part #') input", "AX77")
        page.select_option("label:has-text('Design status') select", "Design In")
        page.select_option("label:has-text('Stage') select", "DVT")
        eau = page.query_selector("label:has-text('EAU') input")
        if eau:
            eau.fill("500")
        asp = page.query_selector("label:has-text('Disty') input") or page.query_selector("label:has-text('ASP') input")
        if asp:
            asp.fill("3")
        conf = page.query_selector("label:has-text('Confidence') input[type='number']") or page.query_selector("label:has-text('Confidence') >> nth=0 >> input")
        if conf:
            conf.fill("0.65")
        owner = page.query_selector("label:has-text('Owner') input")
        if owner:
            owner.fill("marc")
        rat = page.query_selector("label:has-text('rationale') input, label:has-text('rationale') textarea, label:has-text('Rationale') input")
        if rat:
            rat.fill("UI test: design in at DVT with a second source dropped")
        page.click("form.intake-form button[type='submit']")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shots / "intake-submitted.png"), full_page=True)
        created = page.is_visible("text=UI-Test-Row") or page.is_visible("text=OPP-0000")
        check("intake creates a row", created, "toast or row visible" if created else page.inner_text("body")[:200])

        nav("Review Queue", "review")
        check("review queue shows proposals with rule ids", page.is_visible("text=J-05") or page.is_visible("text=Decide"))
        decide = page.query_selector_all("button:has-text('Decide')")
        before = len(decide)
        if decide:
            decide[0].click()
            page.wait_for_timeout(500)
            page.screenshot(path=str(shots / "review-open.png"), full_page=True)
            check("decision panel shows a verbatim quote", page.is_visible("text=“") or page.is_visible("text=pp"))
            page.click("button:has-text('Reject…')")
            page.wait_for_timeout(300)
            page.select_option("label:has-text('Rejection reason') select", "factor_misfired")
            page.click("button:has-text('Confirm reject')")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(shots / "review-rejected.png"), full_page=True)
            check("reject with a reason succeeds", page.is_visible("text=Rejected"))
            # The console pill is the shell's copy of the queue; it must drop with the queue.
            check("console pill drops after a decision", page.is_visible(f"text={before - 1} need review"),
                  f"expected {before - 1} need review")
        approve = page.query_selector_all("button:has-text('Decide')")
        if approve:
            approve[0].click()
            page.wait_for_timeout(400)
            page.click("button:has-text('Approve')")
            page.wait_for_timeout(1200)
            check("approve succeeds", page.is_visible("text=Approved"))

        nav("Roll-ups", "rollups")
        check("roll-ups show a weighted forecast", page.is_visible("text=Weighted forecast"))

        nav("Runs & Audit", "audit")
        check("runs listed with the audit feed", page.is_visible("text=Runs & audit") and page.is_visible("text=Recent decisions"))
        check("director sees the ten-step run", page.is_visible("text=completed"))

        nav("Import")
        check("import wizard present", page.is_visible("text=dry run") or page.is_visible("text=Dry run") or page.is_visible("input[type='file']"))

        nav("Findings")
        page.wait_for_selector("text=12 of 12", timeout=20000)
        page.screenshot(path=str(shots / "findings.png"), full_page=True)
        check("findings report reproduces 12 of 12", page.is_visible("text=12 of 12"))
        check("findings list the #REF! roll-up", page.is_visible("text=SUM(#REF!)"))

        nav("Analyses")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shots / "analyses.png"), full_page=True)
        check("analyses: stage mix headline", page.is_visible("text=has not reached DVT"))
        check("analyses: concentration headline", page.is_visible("text=of the weighted pipeline"))
        check("analyses: dark ones name their parameter", page.is_visible("text=Regional Target"))
        rows_btn = page.query_selector_all("button:has-text('Rows')")
        if rows_btn:
            rows_btn[0].click()
            page.wait_for_timeout(400)
            page.screenshot(path=str(shots / "analyses-rows.png"), full_page=True)

        nav("Notices", "notices")
        check("notices screen renders", page.is_visible("text=Notices"))

        nav("Ask", "ask")
        page.fill("input[placeholder*='weighted pipeline']", "what is the weighted pipeline by region?")
        page.click(".card .workflow-actions button:has-text('Ask')")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shots / "ask-answer.png"), full_page=True)
        check("assistant answers with a citation", page.is_visible("text=get_rollup"))
        page.fill("input[placeholder*='weighted pipeline']", "set Hermes confidence to 0.5")
        page.click(".card .workflow-actions button:has-text('Ask')")
        page.wait_for_timeout(1200)
        check("assistant refuses a write with a pointer", page.is_visible("text=no tool here that writes"))

        page.goto(f"http://127.0.0.1:{port}/embed/assistant")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(shots / "embed-assistant.png"), full_page=True)
        check("embedded assistant route renders standalone", page.is_visible("text=Read-only assistant") and not page.is_visible("nav.sidebar-nav"))

    if role == "owner":
        check("role landing: owner", page.is_visible("text=Your rows"))
        check("owner has no review queue", "Review Queue" not in visible and "Rubric" not in visible and "Users" not in visible)
        nav("Intake")
        check("owner can reach intake", page.is_visible("form.intake-form"))
        nav("Notices", "notices")
        check("owner sees notices", page.is_visible("text=Notices"))
        nav("Analyses")
        page.wait_for_timeout(1200)
        check("owner sees analyses without the targets form", page.is_visible("text=Analyses") and not page.is_visible("text=Save target"))

    if role == "manager":
        check("role landing: manager (own region)", page.is_visible("text=Your region"))
        nav("Review Queue", "review")
        page.wait_for_timeout(800)
        body = page.inner_text("body")
        check("manager queue is Korea only", "Europe" not in body.split("Review")[-1][:3000] and page.is_visible("text=Korea"))
        nav("Pipeline")
        check("manager pipeline shows only Korea rows", page.is_visible("text=Hermes") and not page.is_visible("text=Dresden"))

    if role == "finance":
        check("role landing: finance", page.is_visible("text=Finance"))
        nav("Analyses")
        page.wait_for_timeout(1200)
        check("finance sees the targets form", page.is_visible("text=Save target"))
        page.fill("label:has-text('Region') input", "Korea")
        page.fill("label:has-text('Period') input", "2027")
        page.fill("label:has-text('Amount') input", "10000")
        page.click("button:has-text('Save target')")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shots / "analyses-with-target.png"), full_page=True)
        check("coverage lights up after a target", page.is_visible("text=Coverage against target") and page.is_visible("text=target(s)"))
        nav("Roll-ups", "rollups")
        check("finance sees the forecast feed", page.is_visible("text=Weighted forecast"))
        check("finance has no intake or review", "Intake" not in visible and "Review Queue" not in visible)

    if role == "admin":
        check("role landing: admin", page.is_visible("text=Configuration"))
        nav("Rubric")
        page.wait_for_timeout(1000)
        page.screenshot(path=str(shots / "rubric-matrix.png"), full_page=True)
        check("matrix A grid renders", page.is_visible("text=Design Win") and page.is_visible("text=Promotion"))
        tabs = page.query_selector_all("button.pill, .pill-tabs button, button:has-text('Factors')")
        for t in tabs:
            if "Factors" in (t.inner_text() or ""):
                t.click()
                break
        page.wait_for_timeout(800)
        page.screenshot(path=str(shots / "rubric-factors.png"), full_page=True)
        check("factors show rule ids and caps", page.is_visible("text=J-05") and page.is_visible("text=cap pp"))
        check("review policy control present", page.is_visible("text=Review policy"))
        check("feedback per factor shown", page.is_visible("text=fired") or page.is_visible("text=not fired yet"))
        nav("Users")
        page.fill("label:has-text('User id') input", "ui-kim")
        page.fill("label:has-text('Display name') input", "Kim UI")
        page.fill("label:has-text('Email') input", "kim.ui@axcelai.com")
        page.select_option("label:has-text('Role') select", "manager")
        page.fill("label:has-text('Region scope') input", "Korea")
        page.click("button:has-text('Provision person')")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(shots / "users.png"), full_page=True)
        check("admin provisions a user", page.is_visible("text=ui-kim"))
        nav("Connectors")
        page.wait_for_timeout(800)
        page.screenshot(path=str(shots / "connectors.png"), full_page=True)
        check("connector catalogue lists the four", all(page.is_visible(f"text={x}") for x in ("CRM sync", "ERP extract", "Distributor POS", "Vehicle programme")))
        csv = report.out / "crm-drop.csv"
        csv.write_text("Opportunity ID,End Customer\nOPP-000001,General Motors\n")
        page.set_input_files("input[type='file']", str(csv))
        page.click("button:has-text('Pull')")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(shots / "connectors-dry-run.png"), full_page=True)
        check("connector dry run reports without writing", page.is_visible("text=dry run, nothing written") or page.is_visible("text=\"dry_run\": true"))
        nav("Access")
        check("access matrix renders", page.is_visible("text=Approve") or page.is_visible("text=matrix"))
        nav("Runs & Audit", "audit")
        page.click("button:has-text('Trigger run')")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(shots / "audit-after-run.png"), full_page=True)
        if page.is_visible("text=Compare two runs"):
            page.click("button:has-text('Compare')")
            page.wait_for_timeout(1200)
            page.screenshot(path=str(shots / "run-compare.png"), full_page=True)
            check("run comparison renders", page.is_visible("text=stamps differ on") or page.is_visible("text=Identical"))
        else:
            check("run comparison renders", False, "compare card not shown")
        nav("Pipeline")
        page.wait_for_timeout(800)
        check("admin sees no pipeline rows", not page.is_visible("text=Hermes"))

    browser.close()


def run_auth(pw, report: Report, headed: bool) -> None:
    """Stage two, AUTH_MODE=local: landing -> sign-up -> one-time code -> waiting
    for a role -> admin provisions the email -> the app; then sign-out, a wrong
    password, the seeded director, session persistence and a forged token."""
    import json as _json
    import urllib.error
    import urllib.request

    role = "auth"
    api = f"http://127.0.0.1:{AUTH_BACKEND_PORT}/api/v1"
    app = f"http://127.0.0.1:{AUTH_APP_PORT}"
    tag = str(int(time.time()))[-6:]
    email, uid = f"priya.{tag}@example.com", f"priya{tag}"
    shots = report.out / role
    shots.mkdir(exist_ok=True)

    def check(name: str, condition: bool, detail: str = "") -> None:
        report.step(role, name, bool(condition), detail)

    def call(path: str, body: dict | None = None, token: str | None = None):
        headers = {"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})}
        req = urllib.request.Request(api + path, data=_json.dumps(body).encode() if body is not None else None,
                                     headers=headers, method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req) as r:
            return _json.loads(r.read() or b"null")

    browser = pw.chromium.launch(channel="chrome", headless=not headed)
    page = browser.new_page(viewport={"width": 1366, "height": 900})
    # The deliberate failures below answer 401/403 on purpose; only 5xx count.
    page.on("console", lambda m: report.console.append(f"[{role}] {m.type}: {m.text}")
            if m.type == "error" and "401" not in m.text and "403" not in m.text else None)
    page.on("response", lambda r: report.failed_requests.append(f"[{role}] {r.status} {r.request.method} {r.url}")
            if r.url.startswith(api) and r.status >= 500 else None)

    page.goto(app + "/")
    page.wait_for_selector("text=Create an account", timeout=60000)
    check("signed out: landing page", "/welcome" in page.url)
    page.screenshot(path=str(shots / "01-landing.png"), full_page=True)

    page.click("header nav button:has-text('Create account')")
    page.wait_for_selector("h1:has-text('Create your account')")
    page.fill("label:has-text('Display name') input", "Priya Test")
    page.fill("label:has-text('Email') input", email)
    page.fill("label:has-text('Password') >> nth=0 >> input", "a-strong-password-1")
    page.fill("label:has-text('Confirm password') input", "a-strong-password-1")
    page.screenshot(path=str(shots / "02-signup.png"), full_page=True)
    page.click("button:has-text('Create account')")
    page.wait_for_selector("h1:has-text('Check your email')", timeout=15000)
    code = page.inner_text("[data-testid='dev-code']").strip()
    check("sign-up leads to the code screen (console delivery shows the code)", len(code) == 6)
    page.screenshot(path=str(shots / "03-verify.png"), full_page=True)

    page.fill("label:has-text('Code') input", "000000")
    page.click("button:has-text('Verify and sign in')")
    page.wait_for_selector("text=wrong code", timeout=10000)
    check("wrong code refused with attempts left", page.is_visible("text=attempt(s) left"))
    page.fill("label:has-text('Code') input", code)
    page.click("button:has-text('Verify and sign in')")
    page.wait_for_selector("h1:has-text('waiting for a role')", timeout=15000)
    check("verified stranger waits for a role", "/pending" in page.url)
    page.screenshot(path=str(shots / "04-pending.png"), full_page=True)

    admin = call("/auth/login", {"email": "root@axcelai.com", "password": DEMO_PASSWORD})["token"]
    call("/users", {"user_id": uid, "display_name": "Priya Test", "email": email, "role": "owner", "region_scope": "Korea"}, token=admin)
    page.click("button:has-text('Check again')")
    page.wait_for_selector("[data-testid='profile-card'] strong:has-text('priya')", timeout=20000)
    profile = page.inner_text("[data-testid='profile-card']")
    check("once an admin provisions the email the same session opens the app", "owner" in profile.lower(), profile.replace(chr(10), " | "))
    check("profile card says email + password and offers sign out", "email + password" in profile and page.is_visible("button:has-text('Sign out')"))
    page.screenshot(path=str(shots / "05-owner.png"), full_page=True)

    page.click("[data-testid='profile-card'] button:has-text('Sign out')")
    page.wait_for_selector("text=Create an account", timeout=15000)
    check("sign out returns to the landing page", "/welcome" in page.url)
    page.click("header nav button:has-text('Sign in')")
    page.fill("label:has-text('Email') input", "marc@axcelai.com")
    page.fill("label:has-text('Password') input", "wrong-password-1")
    page.click("button:has-text('Sign in')")
    page.wait_for_selector("text=email or password is wrong", timeout=10000)
    check("wrong password refused", True)
    page.fill("label:has-text('Password') input", DEMO_PASSWORD)
    page.screenshot(path=str(shots / "06-login.png"), full_page=True)
    page.click("button:has-text('Sign in')")
    page.wait_for_selector("[data-testid='profile-card'] strong:has-text('marc')", timeout=20000)
    check("seeded director signs in and has the review queue", page.is_visible("nav.sidebar-nav button[title='Review Queue']"))
    page.screenshot(path=str(shots / "07-director.png"), full_page=True)

    page.reload()
    page.wait_for_selector("[data-testid='profile-card'] strong:has-text('marc')", timeout=20000)
    check("reload keeps the session", True)
    page.evaluate("localStorage.setItem('ot-session','not-a-real-token')")
    page.reload()
    page.wait_for_selector("text=Create an account", timeout=20000)
    check("a forged or revoked token falls back to the landing page", "/welcome" in page.url)

    try:
        urllib.request.urlopen(urllib.request.Request(api + "/opportunities", headers={"X-OppTrack-Role": "director", "X-OppTrack-Actor": "x", "X-OppTrack-Regions": "*"}))
        check("dev headers are ignored in local mode", False, "answered 200")
    except urllib.error.HTTPError as exc:
        check("dev headers are ignored in local mode", exc.code == 401, str(exc.code))
    browser.close()


def main(argv: list[str]) -> int:
    headed = "--headed" in argv
    out = Path(argv[argv.index("--out") + 1]) if "--out" in argv else ROOT.parent / "ui-report"
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    report = Report(out)

    from playwright.sync_api import sync_playwright
    from scripts import walkthrough

    db_path = out / "demo.sqlite"
    walkthrough.OUT = out / "walkthrough.md"
    walkthrough.main(["--keep-db", str(db_path)])
    for port in (BACKEND_PORT, AUTH_BACKEND_PORT, AUTH_APP_PORT, *ROLE_PORTS.values()):
        assert_free(port)
    backend = start_backend(db_path, out / "backend.log", auth_mode="headers")
    frontends: list[subprocess.Popen] = []
    try:
        with sync_playwright() as pw:
            for role in ROLE_PORTS:
                fe = start_frontend(role, out / f"frontend-{role}.log")
                frontends.append(fe)
                try:
                    run_role(pw, role, report, headed)
                except Exception as exc:  # noqa: BLE001 -- recorded, the other roles still run
                    report.step(role, "unhandled", False, f"{type(exc).__name__}: {exc}")
                finally:
                    stop(fe)
    finally:
        stop(backend)
        for fe in frontends:
            stop(fe)

    # Stage two: the same demo database, served in AUTH_MODE=local with the
    # five demo people seeded, behind the real sign-in screens.
    seed_env = {**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}"}
    subprocess.run([sys.executable, "-m", "scripts.seed_demo_accounts"], cwd=ROOT, env=seed_env, check=True,
                   stdout=(out / "seed.log").open("w"), stderr=subprocess.STDOUT)
    auth_backend = start_backend(db_path, out / "backend-auth.log", port=AUTH_BACKEND_PORT, auth_mode="local")
    auth_app = None
    try:
        auth_app = start_frontend("owner", out / "frontend-auth.log", port=AUTH_APP_PORT,
                                  api=f"http://127.0.0.1:{AUTH_BACKEND_PORT}/api/v1")
        with sync_playwright() as pw:
            try:
                run_auth(pw, report, headed)
            except Exception as exc:  # noqa: BLE001
                report.step("auth", "unhandled", False, f"{type(exc).__name__}: {exc}")
    finally:
        stop(auth_backend)
        if auth_app is not None:
            stop(auth_app)

    failures = [r for r in report.results if not r["ok"]]
    summary = {"steps": len(report.results), "failed": len(failures), "console_errors": report.console,
               "failed_requests": report.failed_requests, "results": report.results}
    (out / "report.json").write_text(json.dumps(summary, indent=2))
    print(f"\n{len(report.results) - len(failures)}/{len(report.results)} steps passed; "
          f"{len(report.console)} console error(s); {len(report.failed_requests)} failed API request(s)")
    print(f"screenshots and report.json in {out}")
    return 1 if failures or report.console or report.failed_requests else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
