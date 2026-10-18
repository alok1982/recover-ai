#!/usr/bin/env python3
"""CR-04 browser check: role picker → bank signup → pending page (no bank data, 403) → admin approves in /admin →
the applicant re-logs in and lands on the bank desk → admin revokes → blocked again. Also: /admin needs login
(next= kept), the existing analyst still signs in, the seeded pending applicant is in the queue.

  local mock stack:  python scripts/cr04_roles_check.py --base http://localhost:5173 --mock
  live:              python scripts/cr04_roles_check.py --base https://<project>.web.app
Live reads the admin and analyst passwords from deploy/.state (never printed). The test applicant is deleted at
the end (request doc via DELETE /api/me, login via the Firebase REST self-delete)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "deploy" / ".state"
IDT = "https://identitytoolkit.googleapis.com/v1/accounts"
RESULTS: list[tuple[str, bool, str]] = []
ADMIN_EMAIL, ANALYST_EMAIL = "admin@recoverai-demo.example", "analyst@recoverai-demo.example"
SEEDED_APPLICANT = "pending.applicant@demo-bank.example"


def ok(name: str, cond: bool, info: str = "") -> bool:
    RESULTS.append((name, bool(cond), info))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info else ""))
    return bool(cond)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--shots", default="/tmp/cr04")
    a = ap.parse_args()
    api = a.base.replace(":5173", ":8080") if a.mock else a.base
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    admin_pw = "Demo@2026" if a.mock else (STATE / "admin_password").read_text().strip()
    analyst_pw = "Demo@2026" if a.mock else (STATE / "bank_password").read_text().strip()
    email = f"cr04.ui.{uuid.uuid4().hex[:8]}@demo-bank.example"
    pw = "Ui-" + uuid.uuid4().hex[:10] + "7"
    key = None if a.mock else json.loads((STATE / "sdkconfig.json").read_text())["apiKey"]

    def app_token() -> str:
        if a.mock:
            return f"mock:staff:{email}"
        r = httpx.post(f"{IDT}:signInWithPassword?key={key}", json={"email": email, "password": pw, "returnSecureToken": True}, timeout=30)
        r.raise_for_status()
        return r.json()["idToken"]

    def bank_status(tok: str) -> int:
        return httpx.get(f"{api}/api/bank/cases", headers={"Authorization": f"Bearer {tok}"}, timeout=30).status_code

    def staff_login(pg, em, p, next_=None):
        pg.goto(a.base + "/login?role=bank" + (f"&next={next_}" if next_ else ""))
        pg.wait_for_selector("[data-testid=staff-login]")
        pg.fill("[data-testid=staff-login] input[name=email]", em)
        pg.fill("[data-testid=staff-login] input[name=password]", p)
        pg.click("[data-testid=staff-login] button[type=submit]")

    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    created = False
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        vp = {"viewport": {"width": 1280, "height": 860}}
        try:
            # 1. role picker on the home page → bank signup → pending
            appc = b.new_context(**vp)
            pg = appc.new_page()
            pg.goto(a.base)
            pg.wait_for_selector("[data-testid=home-role-picker]")
            txt = pg.inner_text("[data-testid=home-role-picker]")
            ok("home: role picker (victim default + bank)", "I've been scammed" in txt and "I work at a bank (fraud team)" in txt
               and pg.locator("[data-testid=get-help]").count() == 1)
            pg.screenshot(path=str(shots / "01-home-role-picker.png"), full_page=True)
            pg.click("[data-testid=home-role-bank]")
            pg.wait_for_selector("[data-testid=bank-signup]")
            ok("signup: bank role selected, staff form shown", pg.get_attribute("[data-testid=role-bank]", "aria-checked") == "true")
            f = "[data-testid=bank-signup] "
            pg.fill(f + "input[name=email]", email)
            pg.fill(f + "input[name=password]", pw)
            pg.fill(f + "input[name=password2]", pw)
            pg.fill(f + "input[name=fullName]", "Neha Sharma")
            opts = pg.eval_on_selector_all(f + "select[name=bankName] option", "els => els.map(e => [e.value, e.disabled])")
            ok("demo: staff signup offers only the demo bank (Other disabled)",
               [o for o in opts if o[0] and not o[1]] == [["RecoverAI Demo Bank (fictional)", False]], str(opts))
            pg.select_option(f + "select[name=bankName]", "RecoverAI Demo Bank (fictional)")
            pg.fill(f + "input[name=employeeId]", "KMB-77310")
            pg.fill(f + "input[name=designation]", "Fraud investigation officer")
            pg.fill(f + "textarea[name=note]", "UI check account — deleted after the test")
            pg.check(f + "input[name=ack]")
            pg.screenshot(path=str(shots / "02-bank-signup.png"), full_page=True)
            pg.click(f + "button[type=submit]")
            pg.wait_for_url("**/pending", timeout=30000)
            created = True
            pg.wait_for_selector("[data-testid=pending-title]")
            body = pg.inner_text("main")
            ok("bank signup → Pending admin approval page", "Pending admin approval" in pg.inner_text("[data-testid=pending-title]"))
            ok("pending page shows no bank data", "RAI-" not in body and "Inbox" not in body, "own request only")
            pg.screenshot(path=str(shots / "03-pending.png"), full_page=True)
            ok("pending applicant → 403 on bank API", bank_status(app_token()) == 403)
            pg.goto(a.base + "/admin")
            pg.wait_for_selector("[data-testid=admin-denied]", timeout=30000)
            ok("pending applicant opening /admin → admin access required", True)

            # 2. admin console: login required (next=/admin kept), queue, approve
            admc = b.new_context(**vp)
            ag = admc.new_page()
            ag.goto(a.base + "/admin")
            ag.wait_for_url(lambda u: "/admin/login" in u and "next=" in u, timeout=30000)
            ok("signed-out /admin → /admin/login?next=/admin", "next=/admin" in ag.url or "next=%2Fadmin" in ag.url, ag.url)
            ag.wait_for_selector("[data-testid=admin-login]")
            ok("admin login page: 'RecoverAI Admin', email + password only, demo banner",
               "RecoverAI Admin" in ag.inner_text("h1") and ag.locator("[data-testid=admin-login] input").count() == 2
               and ag.locator("[data-testid=demo-ribbon]").count() == 1)
            ag.screenshot(path=str(shots / "00-admin-login.png"), full_page=True)
            # a non-admin (the existing analyst) is refused and signed out
            ag.fill("[data-testid=admin-login] input[name=email]", ANALYST_EMAIL)
            ag.fill("[data-testid=admin-login] input[name=password]", analyst_pw)
            ag.click("[data-testid=admin-login] button[type=submit]")
            ag.wait_for_selector("[data-testid=admin-required]", timeout=30000)
            ag.goto(a.base + "/admin")
            ag.wait_for_url(lambda u: "/admin/login" in u, timeout=30000)
            ok("non-admin on /admin/login → 'Admin access required' and signed out", True)
            ag.fill("[data-testid=admin-login] input[name=email]", ADMIN_EMAIL)
            ag.fill("[data-testid=admin-login] input[name=password]", admin_pw)
            ag.click("[data-testid=admin-login] button[type=submit]")
            ag.wait_for_url("**/admin", timeout=30000)
            uid = httpx.get(api + "/api/me", headers={"Authorization": "Bearer " + app_token()}, timeout=30).json()["uid"]
            ag.wait_for_selector(f"[data-testid='req-{uid}']", timeout=30000)
            q = ag.inner_text("[data-testid=admin-console]")
            ok("admin console lists the new and the seeded pending applicant", email in q and SEEDED_APPLICANT in q)
            ag.screenshot(path=str(shots / "04-admin-console.png"), full_page=True)
            ag.click(f"[data-testid='req-{uid}'] [data-testid=approve]")
            ag.wait_for_selector("[data-testid=admin-flash]")
            ok("admin approves with bankId demo-recoverai-bank", "Approved" in ag.inner_text("[data-testid=admin-flash]")
               and "demo-recoverai-bank" in ag.inner_text("[data-testid=admin-flash]"), ag.inner_text("[data-testid=admin-flash]"))
            ok("admin console shows the demo banner", ag.locator("[data-testid=demo-ribbon]").count() == 1)

            # 3. applicant: "Check again" (forced token refresh) → bank desk; and a fresh re-login → bank desk
            pg.goto(a.base + "/pending")
            pg.wait_for_selector("[data-testid=check-again], .bank-top", timeout=30000)
            if "/bank" not in pg.url:  # live: the cached token still has no claim until it is refreshed
                pg.click("[data-testid=check-again]")
            pg.wait_for_url("**/bank", timeout=30000)
            ok("Check again (token refresh) → bank desk", True)
            pg.click("text=Sign out")
            staff_login(pg, email, pw)
            pg.wait_for_url("**/bank", timeout=30000)
            pg.wait_for_selector("text=Inbox")
            ok("approved applicant re-login → bank desk", "/bank" in pg.url)
            ok("bank desk header names the demo bank + demo banner",
               "RecoverAI Demo Bank (fictional)" in pg.inner_text("[data-testid=desk-title]") and pg.locator("[data-testid=demo-ribbon]").count() == 1,
               pg.inner_text("[data-testid=desk-title]"))
            try:  # the desk's live Firestore listener must pass the rules (role=bank + APPROVED request)
                pg.wait_for_function("() => /Sandbox \\(([1-9][0-9]*)\\)/.test(document.body.innerText)", timeout=15000)
                ok("approved applicant: bank desk loads the queue (Firestore rules allow)", True,
                   pg.inner_text(".sandbox-tab"))
            except Exception:
                ok("approved applicant: bank desk loads the queue (Firestore rules allow)", False, pg.inner_text("main")[:200])
            pg.screenshot(path=str(shots / "05-approved-bank-desk.png"), full_page=True)
            ok("approved applicant → 200 on bank API", bank_status(app_token()) == 200)

            # 4. revoke → blocked again
            old_tok = app_token()
            ag.click("[data-testid=tab-APPROVED]")
            ag.wait_for_selector(f"[data-testid='req-{uid}'] [data-testid=revoke]")
            ag.fill(f"[data-testid='req-{uid}'] input[aria-label=reason]", "UI check: access no longer needed")
            ag.click(f"[data-testid='req-{uid}'] [data-testid=revoke]")
            ag.wait_for_selector("[data-testid=admin-flash]:has-text('Revoked')")
            ok("admin revokes", True)
            ok("revoked: the old token gets 403 at once", bank_status(old_tok) == 403)
            ag.click("[data-testid=tab-REVOKED]")
            ag.wait_for_selector(f"[data-testid='req-{uid}']")
            ag.screenshot(path=str(shots / "06-admin-revoked-audit.png"), full_page=True)
            ok("audit log shows approve + revoke", "approve" in ag.inner_text("[data-testid=audit-log]")
               and "revoke_bank" in ag.inner_text("[data-testid=audit-log]"))
            pg.goto(a.base + "/")
            staff_login(pg, email, pw)
            pg.wait_for_url("**/pending", timeout=30000)
            pg.wait_for_selector("[data-testid=pending-title]")
            ok("revoked applicant re-login → status page (not the bank desk)", "revoked" in pg.inner_text("[data-testid=pending-title]").lower())
            pg.screenshot(path=str(shots / "07-revoked-status.png"), full_page=True)

            # 5. existing analyst: single login → bank desk, and the /bank login form still works
            anc = b.new_context(**vp)
            an = anc.new_page()
            staff_login(an, ANALYST_EMAIL, analyst_pw)
            an.wait_for_url("**/bank", timeout=30000)
            an.wait_for_selector("text=Inbox")
            ok("existing analyst: single login → bank desk", True)
            an.wait_for_selector("[data-testid=desk-title]")
            an.screenshot(path=str(shots / "08-bank-desk-header.png"))
            an.click(".sandbox-tab")
            try:
                an.wait_for_selector("table a[href*='/bank/case/']", timeout=15000)
                an.click("table a[href*='/bank/case/']")
                an.wait_for_selector("[data-testid=received-by]", timeout=30000)
                rb = an.inner_text("[data-testid=received-by]")
                ok("bank case detail: received by the demo bank", "RecoverAI Demo Bank (fictional)" in rb, rb)
                an.wait_for_timeout(800)
                an.screenshot(path=str(shots / "09-bank-case-detail.png"), full_page=True)
            except Exception as e:  # noqa: BLE001
                ok("bank case detail: received by the demo bank", False, f"no sandbox case to open ({type(e).__name__})")
            anc2 = b.new_context(**vp)
            an2 = anc2.new_page()
            an2.goto(a.base + "/bank")
            if not a.mock:
                an2.fill("label:has-text('Email') input", ANALYST_EMAIL)
                an2.fill("label:has-text('Password') input", analyst_pw)
            an2.click("button:has-text('Sign in')")
            an2.wait_for_selector("text=Scam intelligence", timeout=30000)
            ok("existing analyst: /bank login form unchanged", True)
            # 6. victim role still the default on signup
            vc = b.new_context(**vp).new_page()
            vc.goto(a.base + "/signup")
            ok("signup defaults to the victim role (phone form)", vc.get_attribute("[data-testid=role-victim]", "aria-checked") == "true"
               and vc.locator("input[name=phone]").count() == 1)
        finally:
            if created:
                tok = app_token()
                httpx.delete(f"{api}/api/me", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
                if not a.mock:
                    httpx.post(f"{IDT}:delete?key={key}", json={"idToken": tok}, timeout=30)
                    gone = httpx.post(f"{IDT}:signInWithPassword?key={key}", json={"email": email, "password": pw,
                                                                                   "returnSecureToken": True}, timeout=30).status_code == 400
                    ok("test applicant account deleted", gone)
            b.close()
    failed = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
