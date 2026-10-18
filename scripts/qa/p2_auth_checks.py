#!/usr/bin/env python3
"""QA BUG-06 / BUG-10 on the live build: phone rules on signup + login (A9/A10), and the 'Too many attempts' message
(A12) on the victim (en/hi/ms), bank-desk, staff and admin logins. A11 (same generic error for a wrong password and
an unknown number) is re-checked.

Throw-away accounts only: victims +91 90000 01116 (hi), +91 90000 01117 (ms) and one work-email login
qa.throttle.<hex>@recoverai-qa.example. Each is throttled on purpose and deleted at the end with the ID token from its
own sign-up (no admin rights needed). The real analyst / admin / seed accounts are never sent a wrong password.

  python scripts/qa/p2_auth_checks.py [--out /workspace/qa_logs/p2/auth.json]
"""
import argparse
import sys
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import IDT, SITE, api_key, dump, phone_email, rec, sign_in  # noqa: E402

TOO_MANY = {"en": "Too many attempts", "hi": "बहुत ज़्यादा प्रयास", "ms": "Terlalu banyak percubaan"}


def signup(email: str, pw: str) -> str:
    r = httpx.post(f"{IDT}:signUp?key={api_key()}", json={"email": email, "password": pw, "returnSecureToken": True}, timeout=30)
    r.raise_for_status()
    return r.json()["idToken"]


def throttle(email: str) -> str:
    raw = ""
    for i in range(25):
        raw = sign_in(email, f"Wrong-{i}-x9").json().get("error", {}).get("message", "")
        if "TOO_MANY" in raw:
            break
    return raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/workspace/qa_logs/p2/auth.json")
    ap.add_argument("--base", default=SITE)
    a = ap.parse_args()
    base = a.base.rstrip("/")
    accts = {"hi": "+919000001116", "ms": "+919000001117"}
    staff = f"qa.throttle.{uuid.uuid4().hex[:8]}@recoverai-qa.example"
    pw = "QaThr" + uuid.uuid4().hex[:6] + "7"
    tokens: dict[str, str] = {}
    try:
        for lang, ph in accts.items():
            tokens[ph] = signup(phone_email(ph), pw)
        tokens[staff] = signup(staff, pw)
        raws = {k: throttle(phone_email(k) if k.startswith("+") else k) for k in tokens}
        rec("A12", "Firebase throttles the throw-away logins after repeated wrong passwords",
            all("TOO_MANY" in v for v in raws.values()), str(raws), "P2")
        with sync_playwright() as p:
            for bname in ("chromium", "webkit"):
                br = getattr(p, bname).launch()
                for lang, ph in [("en", accts["hi"]), *accts.items()]:
                    ctx = br.new_context()
                    pg = ctx.new_page()
                    pg.goto(base + "/")
                    pg.evaluate(f"localStorage.setItem('recoverai.lang', '{lang}')")
                    pg.goto(base + "/login?next=/cases")
                    pg.select_option("[data-testid=cc]", "IN")
                    pg.fill("input[name=phone]", ph[3:])
                    pg.fill("input[name=password]", "Wrong-ui-x9")
                    pg.click("button[type=submit]")
                    pg.wait_for_selector("[data-testid=auth-error]", timeout=20000)
                    m = pg.inner_text("[data-testid=auth-error]")
                    rec("A12", f"[{bname}] victim login, {lang}: throttled → '{TOO_MANY[lang]}…'", TOO_MANY[lang] in m, m, "P2")
                    ctx.close()
                for surface, url, email_sel, btn in (("staff (/login?role=bank)", "/login?role=bank", "input[name=email]", "button[type=submit]"),
                                                     ("bank desk (/bank)", "/bank", "input[type=email]", "button:has-text('Sign in')"),
                                                     ("admin (/admin/login)", "/admin/login", "input[name=email], input[type=email]", "button[type=submit]")):
                    ctx = br.new_context()
                    pg = ctx.new_page()
                    pg.goto(base + url)
                    pg.wait_for_selector(email_sel, timeout=20000)
                    pg.fill(email_sel, staff)
                    pg.fill("input[type=password]", "Wrong-ui-x9")
                    pg.click(btn)
                    pg.wait_for_selector("[data-testid=auth-error], .error", timeout=20000)
                    m = pg.locator("[data-testid=auth-error], .error").first.inner_text()
                    rec("A12", f"[{bname}] {surface}: throttled → 'Too many attempts…'", "Too many attempts" in m, m, "P2")
                    ctx.close()
                # A10 / A9 on signup + login, and A11 on a non-throttled unknown number
                ctx = br.new_context()
                pg = ctx.new_page()
                for path in ("/signup", "/login"):
                    for cc, ph, want in (("IN", "10000 0001", "India"), ("IN", "+91 100000001", "India"), ("IN", "5123456789", "India"),
                                         ("IN", "90000011077", "India"), ("MY", "9000001107", "Malaysia"), ("MY", "+60 3 1234 5678", "Malaysia")):
                        pg.goto(base + path)
                        pg.select_option("[data-testid=cc]", cc)
                        pg.fill("input[name=phone]", ph)
                        if path == "/signup":
                            pg.fill("input[name=fullName]", "QA Rule")
                            pg.fill("input[name=password2]", "QaRule2026x")
                            pg.click("input[name=terms]")
                        pg.fill("input[name=password]", "QaRule2026x")
                        pg.click("button[type=submit]")
                        pg.wait_for_selector("[data-testid=auth-error]", timeout=10000)
                        m = pg.inner_text("[data-testid=auth-error]")
                        rec("A10", f"[{bname}] {path}: {cc} {ph!r} → country format error, no account", "valid mobile number" in m and want in m
                            and path in pg.url, m, "P2")
                errs = []
                for ph in ("90000 01198", "90000 01199"):
                    pg.goto(base + "/login")
                    pg.select_option("[data-testid=cc]", "IN")
                    pg.fill("input[name=phone]", ph)
                    pg.fill("input[name=password]", "Wrong-pass-9")
                    pg.click("button[type=submit]")
                    pg.wait_for_selector("[data-testid=auth-error]", timeout=20000)
                    errs.append(pg.inner_text("[data-testid=auth-error]"))
                rec("A11", f"[{bname}] unknown numbers → the same generic 'incorrect' error", errs[0] == errs[1] and "incorrect" in errs[0], str(errs), "P1")
                ctx.close()
                br.close()
        for ph in ("91100000001", "915123456789"):  # the rejected numbers never became accounts
            rec("A10", f"no Firebase login was created for +{ph}", sign_in(f"{ph}@phone.recoverai.app", "QaRule2026x").status_code == 400, "", "P2")
    finally:
        for k, tok in tokens.items():
            r = httpx.post(f"{IDT}:delete?key={api_key()}", json={"idToken": tok}, timeout=30)
            print(f"cleanup: {'staff' if '@' in k else k[:-4] + 'xxxx'} login delete → {r.status_code}")
    dump(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
