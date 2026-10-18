#!/usr/bin/env python3
"""CR-03 Part E acceptance checks in a real browser against a deployed site (or the local mock stack).

  python scripts/cr03_acceptance.py --base https://<project>.web.app --shots /tmp/cr03
  python scripts/cr03_acceptance.py --base http://localhost:5173 --mock

Creates one throw-away signup account (+91 90000 00009) and deletes it (account + its cases) at the end; the cases
opened as the seeded users are deleted too, and 00002 is reset to its seeded (incomplete) profile.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
RESULTS: list[tuple[str, bool, str]] = []
NEW_PHONE, NEW_PW = "90000 00009", "Accept2026x"
HINDI = "मेरे साथ अभी 1,95,000 का फ्रॉड हुआ"


def ok(name: str, cond: bool, info: str = "") -> bool:
    RESULTS.append((name, bool(cond), info))
    print(("PASS " if cond else "FAIL ") + name + (f" — {info}" if info else ""))
    return bool(cond)


def token(mock: bool, e164: str, pw: str = "Demo@2026") -> str:
    if mock:
        return f"mock:phone:{e164}"
    from e2e_demo import phone_login
    r = phone_login(e164, pw)
    r.raise_for_status()
    return r.json()["idToken"]


def login(pg, base, phone, pw="Demo@2026"):
    pg.goto(base + "/login?next=/cases")
    pg.fill("input[name=phone]", phone)
    pg.fill("input[name=password]", pw)
    pg.click("button[type=submit]")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--api", default=None)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--shots", default="/tmp/cr03")
    a = ap.parse_args()
    api = a.api or (a.base.replace(":5173", ":8080") if a.mock else a.base)
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    cleanup: list[tuple[str, str]] = []  # (token, caseId)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        pg = b.new_context(viewport={"width": 1280, "height": 860}).new_page()
        # E1: hotline without login; Get help now → signup → /cases → new case → co-pilot
        pg.goto(a.base)
        pg.wait_for_selector("[data-testid=emergency-strip]")
        ok("home: hotline strip without login", pg.locator("a[href='tel:1930']").count() >= 1
           and pg.locator("a[href='tel:997']").count() >= 1 and "cybercrime.gov.in" in pg.inner_text("[data-testid=emergency-strip]"))
        ok("home: hero, safety line, demo ribbon", "The first hour matters" in pg.inner_text("h1")
           and "never ask you for money, OTPs or passwords" in pg.inner_text("main"), pg.inner_text("[data-testid=demo-ribbon]") if pg.locator("[data-testid=demo-ribbon]").count() else "no ribbon")
        pg.screenshot(path=str(shots / "01-home.png"), full_page=True)
        pg.click("[data-testid=get-help]")
        pg.wait_for_url("**/signup**")
        pg.fill("input[name=phone]", NEW_PHONE)
        pg.fill("input[name=fullName]", "Meera Joshi")
        pg.fill("input[name=password]", NEW_PW)
        pg.fill("input[name=password2]", NEW_PW)
        pg.check("input[name=terms]")
        pg.screenshot(path=str(shots / "02-signup.png"), full_page=True)
        pg.click("button[type=submit]")
        try:
            pg.wait_for_url("**/cases", timeout=30000)
        except Exception:
            err = pg.locator("[data-testid=auth-error]").all_inner_texts()
            if err and "already exists" in err[0]:  # a previous run left the account: sign in instead
                login(pg, a.base, NEW_PHONE, NEW_PW)
                pg.wait_for_url("**/cases", timeout=30000)
            else:
                raise
        pg.wait_for_selector("[data-testid=greeting]:has-text('Meera')")
        pg.click("[data-testid=start-case]")
        pg.wait_for_url("**/cases/c_*", timeout=30000)
        pg.wait_for_selector(".bubble.assistant", timeout=30000)
        cid_new = pg.url.rsplit("/", 1)[1]
        ok("Get help now → signup → /cases → new case → co-pilot", True, cid_new)
        # E2: log out, wrong password, log in → same cases
        pg.click("[data-testid=account-menu]")
        pg.click("[data-testid=logout]")
        pg.wait_for_url(re.compile(r".*/$"))
        pg.goto(a.base + "/cases")
        pg.wait_for_url("**/login**")
        login(pg, a.base, NEW_PHONE, "WrongPass99")
        pg.wait_for_selector("[data-testid=auth-error]", timeout=30000)
        ok("wrong password → generic error", pg.inner_text("[data-testid=auth-error]") == "Phone number or password is incorrect",
           pg.inner_text("[data-testid=auth-error]"))
        login(pg, a.base, NEW_PHONE, NEW_PW)
        pg.wait_for_url("**/cases", timeout=30000)
        pg.wait_for_selector("[data-testid=case-list]", timeout=30000)
        ok("log in again → the same case is listed", cid_new in pg.inner_html("[data-testid=case-list]"))
        ok("no synthetic email shown anywhere", "phone.recoverai.app" not in pg.content())
        # profile page + delete account (SHOULD) — cleans up the throw-away account and its case
        pg.goto(a.base + "/profile")
        pg.wait_for_selector("[data-testid=profile-meter]")
        pg.once("dialog", lambda d: d.accept())
        pg.click("[data-testid=delete-account]")
        pg.wait_for_url(re.compile(r".*/$"), timeout=30000)
        login(pg, a.base, NEW_PHONE, NEW_PW)
        pg.wait_for_selector("[data-testid=auth-error]", timeout=30000)
        ok("delete account removes the login", True)

        # E3: 00002 → hotline card, then profile card (PIN + bank only); 412 until Save; then evidence
        t2 = token(a.mock, "+919000000002")
        h2 = {"Authorization": f"Bearer {t2}"}
        httpx.put(f"{api}/api/me/profile", json={"profile": {"postalCode": "", "primaryBank": ""}}, headers=h2, timeout=30)
        login(pg, a.base, "90000 00002")
        pg.wait_for_url("**/cases", timeout=30000)
        pg.wait_for_selector("[data-testid=profile-banner]")
        ok("/cases banner for 00002", "2" in pg.inner_text("[data-testid=profile-banner]"), pg.inner_text("[data-testid=profile-banner]"))
        pg.screenshot(path=str(shots / "03-cases.png"), full_page=True)
        pg.locator(".pickers .seg-btn", has_text="हिन्दी").click()
        pg.click("[data-testid=start-case]")
        pg.wait_for_url("**/cases/c_*", timeout=30000)
        cid2 = pg.url.rsplit("/", 1)[1]
        cleanup.append((t2, cid2))
        pg.wait_for_selector(".bubble.assistant", timeout=30000)
        pg.fill(".inputbar textarea", HINDI)
        pg.keyboard.press("Enter")
        pg.wait_for_selector("[data-testid=profile-card] [data-testid=profile-form]", timeout=120000)
        pg.wait_for_timeout(1500)
        cls = pg.eval_on_selector_all(".messages .card", "els => els.map(e => e.className)")
        hi = [i for i, k in enumerate(cls) if "hotline-card" in k]
        pi = [i for i, k in enumerate(cls) if "profile-card" in k]
        ok("00002: Call 1930 card, then the profile card", bool(hi) and bool(pi) and hi[0] < pi[0]
           and not any("upload-card" in k for k in cls), str([k.split()[1] if len(k.split()) > 1 else k for k in cls]))
        fields = pg.eval_on_selector_all("[data-testid=profile-form] input, [data-testid=profile-form] select", "els => els.map(e => e.name)")
        ok("profile card shows only PIN code and bank", fields == ["postalCode", "primaryBank"], str(fields))
        pg.locator("[data-testid=hotline-card]").scroll_into_view_if_needed()
        pg.screenshot(path=str(shots / "04-gate-hotline-profile.png"))
        for path in ("drafts", "send-to-bank/preview"):
            r = httpx.post(f"{api}/api/cases/{cid2}/{path}", headers=h2, timeout=60)
            d = (r.json() or {}).get("detail") or {}
            ok(f"{path} → 412 until Save", r.status_code == 412 and d.get("code") == "PROFILE_INCOMPLETE", f"{r.status_code} {d}")
        pg.fill("[data-testid=profile-form] input[name=postalCode]", "208001")
        pg.select_option("[data-testid=profile-form] select[name=primaryBank]", "State Bank of India")
        pg.click("[data-testid=profile-save]")
        pg.wait_for_selector(".upload-card", timeout=120000)
        pg.wait_for_timeout(1000)
        pg.screenshot(path=str(shots / "05-after-save-evidence.png"))
        ok("after Save the co-pilot asks for evidence", True)
        r = httpx.post(f"{api}/api/cases/{cid2}/send-to-bank/preview", headers=h2, timeout=60)
        ok("gate lifted after Save", r.status_code != 412, str(r.status_code))
        httpx.put(f"{api}/api/me/profile", json={"profile": {"postalCode": "", "primaryBank": ""}}, headers=h2, timeout=30)
        pg.click("[data-testid=account-menu]")
        pg.click("[data-testid=logout]")
        pg.wait_for_url(re.compile(r".*/$"))

        # E4: 00001 → straight to evidence
        t1 = token(a.mock, "+919000000001")
        login(pg, a.base, "90000 00001")
        pg.wait_for_url("**/cases", timeout=30000)
        pg.click("[data-testid=start-case]")
        pg.wait_for_url("**/cases/c_*", timeout=30000)
        cid1 = pg.url.rsplit("/", 1)[1]
        cleanup.append((t1, cid1))
        pg.wait_for_selector(".bubble.assistant", timeout=30000)
        pg.fill(".inputbar textarea", HINDI)
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".upload-card", timeout=120000)
        pg.wait_for_timeout(1500)
        cls = pg.eval_on_selector_all(".messages .card", "els => els.map(e => e.className)")
        ok("00001: straight to evidence (no hotline/profile card)", not any("profile-card" in k or "hotline-card" in k for k in cls))
        # E7: guard redirects
        ctx2 = b.new_context()
        g = ctx2.new_page()
        g.goto(a.base + f"/cases/{cid1}")
        g.wait_for_url("**/login?next=**", timeout=30000)
        ok("signed-out /cases/:id → /login?next=…", "next=%2Fcases%2F" in g.url, g.url)
        ctx2.close()
        b.close()
    hdr = httpx.get(a.base + "/", timeout=30).headers.get("permissions-policy")
    ok("Permissions-Policy microphone=(self)", (hdr or "").startswith("microphone=(self)") if not a.mock else True, str(hdr))
    for tok, cid in cleanup:
        r = httpx.delete(f"{api}/api/cases/{cid}", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        print("deleted" if r.status_code == 200 else f"delete failed {r.status_code}", cid)
    bad = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS) - len(bad)}/{len(RESULTS)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
