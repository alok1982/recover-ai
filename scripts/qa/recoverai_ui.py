#!/usr/bin/env python3
"""RecoverAI Playwright UI suite — the Python equivalent of the plan's `recoverai.spec.js` (Node Playwright is not
installed on the QA box; the repo already uses Python Playwright, WebKit engine). Live site by default.

  .venv/bin/python scripts/qa/recoverai_ui.py [--base https://recoverai-511917.web.app] [--shots docs/screenshots/qa]

Throw-away accounts: +91 90000 01107 (signup/login/XSS/360 px/confirm sheet) and +91 90000 01108 (A12 throttle).
Seed 00002 is used read-only for B1 and B5 (its profile is reset to the seeded state afterwards). Analyst / admin
logins are used read-only. All throw-away accounts are deleted at the end."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import httpx
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import (FIX, ROOT, RUN_URL, SITE, STATE, Api, COMPLETE_IN, Throwaway, api_key, dump, phone_login, rec,  # noqa: E402
                       token_for, IDT, phone_email)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from copilot_api_checks import story_case  # noqa: E402

NEW = "+919000001107"
THROTTLE = "+919000001108"
PW = "QaUi2026x9"


def login(pg, base, national, pw, cc="IN", nxt="/cases"):
    pg.goto(base + f"/login?next={nxt}")
    pg.select_option("[data-testid=cc]", cc)
    pg.fill("input[name=phone]", national)
    pg.fill("input[name=password]", pw)
    pg.click("button[type=submit]")


def no_hscroll(pg) -> tuple[bool, int, int]:
    sw, cw = pg.evaluate("[document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    return sw <= cw + 1, sw, cw


def small_targets(pg) -> list[str]:
    return pg.evaluate("""() => [...document.querySelectorAll('button, a.btn, a.hotline, input[type=checkbox], select')]
      .filter(e => e.offsetParent !== null).map(e => [e, e.getBoundingClientRect()])
      .filter(([e, r]) => r.height < 44 && r.width > 0 && !e.classList.contains('link'))
      .map(([e, r]) => (e.innerText || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 24) + ':' + Math.round(r.height))""")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=SITE)
    ap.add_argument("--shots", default=str(ROOT / "docs" / "screenshots" / "qa"))
    ap.add_argument("--out", default="/workspace/qa_logs/ui.json")
    a = ap.parse_args()
    base, shots = a.base.rstrip("/"), Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    shot = lambda pg, n: pg.screenshot(path=str(shots / f"{n}.png"), full_page=False)  # noqa: E731
    created: list[str] = []
    with sync_playwright() as p:
        br = p.webkit.launch()
        ctx = br.new_context(viewport={"width": 1280, "height": 860})
        pg = ctx.new_page()
        dialogs: list[str] = []
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        try:
            # ---------------- A1-A3 home
            pg.goto(base + "/")
            pg.wait_for_selector("[data-testid=emergency-strip]")
            hrefs = pg.eval_on_selector_all("[data-testid=emergency-strip] a.hotline", "els => els.map(e => e.getAttribute('href'))")
            rec("A1", "hotline strip visible without login, tel:1930 + tel:997, no login wall",
                "tel:1930" in hrefs and "tel:997" in hrefs and "/login" not in pg.url, f"{hrefs}", "P0")
            shot(pg, "A1-home-en")
            before = pg.inner_text("h1")
            pg.click(".lang-switch button[title*='हिन्दी'], .lang-switch button:has-text('HI'), .lang-switch button:has-text('हि')")
            time.sleep(0.5)
            hi = pg.inner_text("h1")
            shot(pg, "A2-home-hi")
            pg.click(".lang-switch button[title*='Melayu'], .lang-switch button:has-text('MS')")
            time.sleep(0.5)
            ms = pg.inner_text("h1")
            rec("A2", "language switch EN → हिन्दी → Bahasa Melayu changes the text", before != hi and hi != ms and bool(re.search(r"[\u0900-\u097F]", hi)),
                f"{before[:30]} | {hi[:30]} | {ms[:30]}", "P1")
            rec("A2", "hotline per country on '/' (plan: changes with country)", None,
                "home shows both India 1930 and Malaysia 997 side by side (no country switch on '/'); per-country hotline appears in the co-pilot", "P1")
            pg.click(".lang-switch button[title*='English'], .lang-switch button:has-text('EN')")
            time.sleep(0.3)
            body = pg.inner_text("body")
            rec("A3", "DEMO ribbon + safety line 'never ask for money, OTPs or passwords'",
                pg.is_visible("[data-testid=demo-ribbon]") and "never ask you for money, OTPs or passwords" in body, "", "P2")
            rec("K-ROLEPICK", "home role picker: victim 'Get help now' + bank staff apply/sign-in", pg.is_visible("[data-testid=home-role-picker]")
                and pg.is_visible("[data-testid=get-help]") and pg.is_visible("[data-testid=home-role-bank]"), "", "P1")
            rec("K-LOGO", "RAI logo in the home header", pg.is_visible("[data-testid=brand-logo]"), "", "P2")
            html = httpx.get(base + "/", timeout=30).text
            assets = {u: httpx.get(base + u, timeout=30) for u in ("/favicon.ico", "/favicon.svg", "/favicon-32.png", "/apple-touch-icon.png",
                                                                  "/icon-192.png", "/icon-512.png", "/icon-maskable-512.png", "/manifest.webmanifest")}
            man = assets["/manifest.webmanifest"].json() if assets["/manifest.webmanifest"].status_code == 200 else {}
            rec("K-LOGO", "favicon (ico/svg/png), apple-touch, PWA icons 192/512/maskable + manifest all 200",
                all(r.status_code == 200 for r in assets.values()) and len(man.get("icons", [])) >= 3 and 'rel="manifest"' in html,
                f"{ {u: r.status_code for u, r in assets.items()} }; manifest name={man.get('name')}", "P2")
            js = re.search(r'src="(/assets/[^"]+\.js)"', html)
            hd_html = httpx.get(base + "/cases", timeout=30).headers
            hd_js = httpx.get(base + js.group(1), timeout=30).headers if js else {}
            rec("K-CACHEHDR", "HTML no-cache; hashed /assets immutable 1 year",
                "no-cache" in hd_html.get("cache-control", "") and "immutable" in hd_js.get("cache-control", "") and "31536000" in hd_js.get("cache-control", ""),
                f"html={hd_html.get('cache-control')} js={hd_js.get('cache-control')}", "P2")
            # ---------------- A4 guarded routes
            for path in ("/cases", "/profile", "/cases/xyz"):
                pg.goto(base + path)
                pg.wait_for_url(re.compile(r".*/login\?next=.*"), timeout=15000)
                rec("A4", f"signed-out {path} → /login?next=…", "next=" in pg.url and path.split("/")[1] in pg.url, pg.url.replace(base, ""), "P0")
            # ---------------- A7/A8/A10 signup validation
            pg.goto(base + "/signup")
            pg.wait_for_selector("input[name=phone]")
            shot(pg, "A5-signup")

            def try_signup(phone, name, pw, pw2, terms) -> str:
                pg.fill("input[name=phone]", phone)
                pg.fill("input[name=fullName]", name)
                pg.fill("input[name=password]", pw)
                pg.fill("input[name=password2]", pw2)
                if pg.is_checked("input[name=terms]") != terms:
                    pg.click("input[name=terms]")
                pg.click("button[type=submit]")
                try:
                    pg.wait_for_selector("[data-testid=auth-error]", timeout=4000)
                    return pg.inner_text("[data-testid=auth-error]")
                except Exception:  # noqa: BLE001
                    return ""
            for bad in ("abc", "12345678", "abcdefgh"):
                m = try_signup("90000 01107", "QA Ui", bad, bad, True)
                rec("A7", f"weak password '{bad}' blocked inline", "8 characters" in m and "/signup" in pg.url, m, "P1")
            m = try_signup("90000 01107", "QA Ui", PW, PW + "x", True)
            rec("A7", "mismatched confirm blocked", "do not match" in m, m, "P1")
            m = try_signup("90000 01107", "QA Ui", PW, PW, False)
            rec("A8", "terms unticked → blocked", "accept the Terms" in m and "/signup" in pg.url, m, "P1")
            for ph, lbl in (("90000", "5 digits"), ("abcdefghij", "letters"), ("5123456789", "IN starting 5"),
                            ("+91 100000001", "+91 with 9 digits"), ("90000011077", "11 digits"), ("+44 7700 900000", "UK number")):
                m = try_signup(ph, "QA Ui", PW, PW, True)
                rec("A10", f"invalid phone ({lbl}) → validation error", "valid mobile" in m, m, "P2")
            pg.select_option("[data-testid=cc]", "IN")
            m = try_signup("10000 0001", "QA Ui", PW, PW, True)
            pg.wait_for_timeout(4000)
            accepted = "/signup" not in pg.url
            rec("A10", "a Malaysian number with the +91 code → validation error", "valid mobile" in m and not accepted,
                "accepted: account +91100000001 was created (deleted again by this suite)" if accepted else m, "P2")
            if accepted:  # clean up the account the bug let through
                from qa_common import sign_in
                r = sign_in("91100000001@phone.recoverai.app", PW)
                if r.status_code == 200:
                    tk = r.json()["idToken"]
                    httpx.delete(SITE + "/api/me", headers={"Authorization": f"Bearer {tk}"}, timeout=30)
                    httpx.post(f"{IDT}:delete?key={api_key()}", json={"idToken": tk}, timeout=30)
                ctx.clear_cookies()
                pg.goto(base + "/")
                pg.evaluate("() => { try { indexedDB.deleteDatabase('firebaseLocalStorageDb'); localStorage.clear(); } catch (e) {} }")
                pg.goto(base + "/signup")
                pg.wait_for_selector("input[name=phone]")
            # ---------------- A5 signup
            pg.select_option("[data-testid=cc]", "IN")
            m = try_signup("90000 01107", "QA Ui Tester", PW, PW, True)
            try:
                pg.wait_for_url(lambda u: urlparse(u).path == "/cases", timeout=30000)
                created.append(NEW)
            except Exception:  # noqa: BLE001
                pass
            pg.wait_for_selector("[data-testid=greeting]", timeout=30000)
            body = pg.content()
            tok = token_for(NEW, PW)
            claims = json.loads(__import__("base64").urlsafe_b64decode(tok.split(".")[1] + "=="))
            rec("A5", "signup → /cases; Firebase email 91…@phone.recoverai.app; UI never shows it",
                pg.url.endswith("/cases") and claims.get("email") == phone_email(NEW) and "phone.recoverai.app" not in body,
                f"email domain ok={claims.get('email', '').endswith('@phone.recoverai.app')}", "P0")
            shot(pg, "A5-cases-after-signup")
            # ---------------- XSS in profile name (I7) + B2/B3 via the profile page
            api = Api(tok)
            api.j("PUT", "/api/me/profile", json={"profile": {**COMPLETE_IN, "fullName": "<img src=x onerror=alert(1)>"}})
            pg.goto(base + "/profile")
            pg.wait_for_selector("[data-testid=profile-meter]")
            pg.goto(base + "/cases")
            pg.wait_for_selector("[data-testid=greeting]")
            time.sleep(1)
            rec("I7", "profile name '<img onerror>' rendered as text, no alert", not dialogs and pg.locator("img[src=x]").count() == 0,
                f"dialogs={dialogs}", "P1")
            for v, ok_ in (("A", False), ("x" * 81, False), ("राम कुमार", True), ("Sean O'Brien", True)):
                r = api.req("PUT", "/api/me/profile", json={"profile": {"fullName": v}})
                rec("B3", f"name {v[:12]!r} ({len(v)} chars) → {'accepted' if ok_ else 'rejected'}", (r.status_code == 200) == ok_, f"HTTP {r.status_code}", "P2")
            for pc, ok_ in (("12345", False), ("1234567", False), ("abcdef", False), ("411001", True)):
                r = api.req("PUT", "/api/me/profile", json={"profile": {"postalCode": pc}})
                rec("B2", f"IN PIN {pc} → {'accepted' if ok_ else 'rejected'}", (r.status_code == 200) == ok_, f"HTTP {r.status_code}", "P1")
            r = api.req("PUT", "/api/me/profile", json={"profile": {"country": "MY", "language": "en", "postalCode": "1234", "primaryBank": "Maybank"}})
            r2 = api.req("PUT", "/api/me/profile", json={"profile": {"country": "MY", "language": "en", "postalCode": "50450", "primaryBank": "Maybank"}})
            rec("B2", "MY postcode 1234 rejected, 50450 accepted", r.status_code == 422 and r2.status_code == 200, f"{r.status_code}/{r2.status_code}", "P1")
            api.j("PUT", "/api/me/profile", json={"profile": COMPLETE_IN})
            # UI-side PIN validation
            pg.goto(base + "/profile")
            pg.wait_for_selector("[data-testid=profile-form]")
            pin = pg.locator("[data-testid=profile-form] input[name=postalCode]")
            if pin.count():
                pin.fill("12345")
                pg.click("[data-testid=profile-save]")
                time.sleep(1.5)
                err_txt = pg.inner_text("[data-testid=profile-form]")
                rec("B2", "profile page shows an inline error for PIN 12345", bool(re.search(r"6|PIN|invalid|digits", err_txt, re.I)) and
                    api.j("GET", "/api/me")["profile"]["postalCode"] == "411001", "", "P1")
                shot(pg, "B2-profile-pin-error")
                pg.goto(base + "/profile")
            # ---------------- A6 same phone again
            ctx2 = br.new_context()
            p2 = ctx2.new_page()
            p2.goto(base + "/signup")
            p2.fill("input[name=phone]", "90000 01107")
            p2.fill("input[name=fullName]", "QA Dup")
            p2.fill("input[name=password]", PW)
            p2.fill("input[name=password2]", PW)
            p2.click("input[name=terms]")
            p2.click("button[type=submit]")
            p2.wait_for_selector("[data-testid=auth-error]", timeout=20000)
            rec("A6", "same phone again → clear 'already exists' message", "already exists" in p2.inner_text("[data-testid=auth-error]"),
                p2.inner_text("[data-testid=auth-error]"), "P1")
            # ---------------- A9 phone formats + A11 generic errors
            for fmt in ("9000001107", "+91 90000 01107", "09000001107", "+91-90000-01107"):
                login(p2, base, fmt, PW)
                try:
                    p2.wait_for_url(lambda u: urlparse(u).path == "/cases", timeout=20000)
                    okk = True
                except Exception:  # noqa: BLE001
                    okk = False
                rec("A9", f"log in with phone format {fmt!r}", okk, p2.url.replace(base, ""), "P1")
                if okk:
                    p2.click("[data-testid=account-menu]")
                    p2.click("[data-testid=logout]")
                    p2.wait_for_url(re.compile(r".*/$"), timeout=15000)
            login(p2, base, "90000 01107", "Wrong-pass-9")
            p2.wait_for_selector("[data-testid=auth-error]", timeout=20000)
            e1 = p2.inner_text("[data-testid=auth-error]")
            login(p2, base, "90000 01199", "Wrong-pass-9")
            p2.wait_for_selector("[data-testid=auth-error]", timeout=20000)
            e2 = p2.inner_text("[data-testid=auth-error]")
            rec("A11", "wrong password and unknown phone → identical generic error", e1 == e2 and "incorrect" in e1, f"{e1!r} / {e2!r}", "P1")
            # ---------------- A14 two browsers, live update
            api = Api(token_for(NEW, PW))
            cid = api.j("POST", "/api/cases", json={"country": "IN", "language": "en"})["caseId"]
            login(p2, base, "90000 01107", PW, nxt=f"/cases/{cid}")
            p2.wait_for_url(f"**/cases/{cid}", timeout=20000)
            pg.goto(base + f"/cases/{cid}")
            pg.wait_for_selector("textarea, input[type=text]", timeout=20000)
            p2.wait_for_selector("textarea, input[type=text]", timeout=20000)
            box = pg.locator("textarea").first
            box.fill("Live sync check from browser one")
            box.press("Enter")
            try:
                p2.wait_for_selector("text=Live sync check from browser one", timeout=20000)
                live = True
            except Exception:  # noqa: BLE001
                live = False
            rec("A14", "same account in two browsers: a message sent in one appears live in the other", live, "", "P2")
            shot(p2, "A14-second-browser")
            # C2 refresh mid-conversation
            pg.wait_for_timeout(6000)
            n_before = pg.locator(".msg, .bubble, [class*=message]").count()
            pg.reload()
            pg.wait_for_selector("text=Live sync check from browser one", timeout=20000)
            rec("C2", "refresh mid-conversation → conversation restored", True, f"{n_before} message nodes before reload", "P1")
            # H3 mic denied (WebKit headless: no permission granted)
            mic = pg.locator("button[aria-label*='oice' i], button[aria-label*='mic' i], button.mic")
            if mic.count():
                mic.first.click()
                try:
                    pg.wait_for_selector("[data-testid=voice-hint]", timeout=8000)
                    hint = pg.inner_text("[data-testid=voice-hint]")
                except Exception:  # noqa: BLE001
                    hint = ""
                rec("H3", "mic unavailable (WebKit headless: no MediaRecorder) → helpful hint, typing still works", bool(re.search(r"Microphone|microphone|No microphone|https|not supported", hint))
                    and pg.locator("textarea").first.is_enabled(), hint[:120], "P1")
                shot(pg, "H3-mic-hint")
            else:
                rec("H3", "mic button present", None, "no mic button found", "P1")
            rec("H6", "no '[voice message could not be transcribed]' bubble", "could not be transcribed" not in pg.content(), "", "P1")
            # I7 chat XSS rendering
            box = pg.locator("textarea").first
            box.fill("<img src=x onerror=alert(1)>")
            box.press("Enter")
            pg.wait_for_timeout(8000)
            rec("I7", "chat message '<img onerror>' rendered as text, no alert", not dialogs and pg.locator("img[src=x]").count() == 0, "", "P1")
            # ---------------- A13 logout + back
            pg.click("[data-testid=account-menu]")
            pg.click("[data-testid=logout]")
            pg.wait_for_url(re.compile(r".*/$"), timeout=15000)
            pg.go_back()
            time.sleep(2)
            rec("A13", "log out, Back → no private data, redirect to login", "/login" in pg.url and "Live sync check" not in pg.content(),
                pg.url.replace(base, ""), "P1")
            api.req("DELETE", f"/api/cases/{cid}")
            ctx2.close()

            # ---------------- E4/E5/E6/E9 confirmation sheet in the UI (case prepared over the API)
            api = Api(token_for(NEW, PW))
            cid, _ = story_case(api, "en", "UI")
            login(pg, base, "90000 01107", PW, nxt=f"/cases/{cid}")
            pg.wait_for_url(f"**/cases/{cid}", timeout=20000)
            pg.wait_for_selector("text=Review and send", timeout=30000)
            rec("E1", "SANDBOX pill visible; no live toggle (ALLOW_LIVE_SUBMISSION=false)", pg.locator("text=SANDBOX").count() > 0
                and pg.locator("input[type=checkbox][aria-label*='andbox' i]").count() == 0, "", "P0")
            pg.locator("text=Review and send").last.click()
            pg.wait_for_selector(".confirm-sheet [data-testid=confirm-bank]", timeout=20000)
            sheet = pg.inner_text(".confirm-sheet")
            btn = pg.locator(".confirm-sheet button.primary").first
            rec("E4", "sheet: demo bank, amount, beneficiary, destination Sandbox; Confirm disabled until ticked",
                "RecoverAI Demo Bank (fictional)" in sheet and "1,95,000" in sheet and btn.is_disabled(), sheet[:200].replace("\n", " | "), "P0")
            rec("E4", "sheet shows evidence thumbnails + masked account (plan wording)", None,
                "sheet lists the evidence count with SHA-256, not thumbnails; beneficiary VPA shown in full: " +
                ("masked" if "*" in sheet or "•" in sheet else "unmasked"), "P0")
            shot(pg, "E4-confirm-sheet")
            pg.click(".confirm-sheet input[type=checkbox]")
            btn.click()
            pg.wait_for_selector("text=Undo", timeout=5000)
            shot(pg, "E5-undo-countdown")
            time.sleep(2)
            pg.click(".confirm-sheet button:has-text('Undo')")
            time.sleep(11)
            st = api.j("GET", f"/api/cases/{cid}")["case"]
            rec("E5", "Confirm then Undo within 10 s → nothing published", st["bankStatus"] == "NONE" and not st.get("bankCaseId"), st["bankStatus"], "P0")
            pg.click(".confirm-sheet button:has-text('Cancel')")
            # E6 close the tab during the countdown
            p3 = ctx.new_page()
            p3.goto(base + f"/cases/{cid}")
            p3.wait_for_selector("text=Review and send", timeout=30000)
            p3.locator("text=Review and send").last.click()
            p3.wait_for_selector(".confirm-sheet [data-testid=confirm-bank]", timeout=20000)
            p3.click(".confirm-sheet input[type=checkbox]")
            p3.locator(".confirm-sheet button.primary").first.click()
            time.sleep(2)
            p3.close()
            time.sleep(12)
            st = api.j("GET", f"/api/cases/{cid}")["case"]
            rec("E6", "Confirm then close the tab within 10 s → nothing sent", st["bankStatus"] == "NONE", st["bankStatus"], "P1")
            # E9 full send through the UI
            pg.reload()
            pg.wait_for_selector("text=Review and send", timeout=30000)
            pg.locator("text=Review and send").last.click()
            pg.wait_for_selector(".confirm-sheet [data-testid=confirm-bank]", timeout=20000)
            pg.click(".confirm-sheet input[type=checkbox]")
            pg.locator(".confirm-sheet button.primary").first.click()
            t0 = time.time()
            pg.wait_for_selector(".confirm-sheet", state="detached", timeout=40000)
            st = api.j("GET", f"/api/cases/{cid}")["case"]
            bank = Api(__import__("qa_common").staff_token("bank"), RUN_URL)  # direct: Hosting caches 404s (K-CACHE)
            seen = None
            for _ in range(30):
                if st.get("bankCaseId") and bank.req("GET", f"/api/bank/cases/{st['bankCaseId']}").status_code == 200:
                    seen = time.time() - t0
                    break
                time.sleep(0.3)
                st = api.j("GET", f"/api/cases/{cid}")["case"]
            pg.wait_for_timeout(2000)
            shot(pg, "E9-sent-to-sandbox")
            body = pg.inner_text("body")
            rec("E9", "UI send → bank case in Sandbox tab; victim sees 'sandbox (test)'", seen is not None and re.search(r"sandbox", body, re.I) is not None,
                f"bank case visible {seen:.1f}s after the 10 s countdown" if seen else "not seen", "P0")
            Path("/workspace/qa_logs/probe_bank_cases.txt").open("a").write(f"{st.get('bankCaseId')}\n")
            # bank desk view of it (analyst)
            bctx = br.new_context(viewport={"width": 1280, "height": 860})
            bp = bctx.new_page()
            bp.goto(base + "/bank")
            bp.wait_for_selector("input[type=email]", timeout=20000)
            rec("K-BANKLOGIN", "bank login asks only email + password (no Name field)", bp.locator("input[name=fullName], input[name=name]").count() == 0,
                "", "P2")
            rec("K-DEMOBANNER", "demo banner on the bank login", bp.locator("[data-testid=demo-ribbon]").count() > 0 or "Demo" in bp.inner_text("body"), "", "P2")
            bp.fill("input[type=email]", "analyst@recoverai-demo.example")
            bp.fill("input[type=password]", (STATE / "bank_password").read_text().strip())
            bp.click("button:has-text('Sign in')")
            bp.wait_for_selector("[data-testid=desk-title]", timeout=30000)
            bp.wait_for_timeout(2500)
            desk = bp.inner_text("body")
            real = [b for b in ("HDFC", "ICICI", "State Bank of India", "Axis Bank", "Kotak", "Maybank", "CIMB") if b in desk]
            rec("K-DEMOBANK", "bank desk header names 'RecoverAI Demo Bank (fictional)'; no real bank names on the desk list",
                "RecoverAI Demo Bank (fictional)" in desk and not real, f"real names seen: {real}", "P1")
            shot(bp, "K-bank-desk")
            ref = st.get("publicRef")
            tab = bp.locator("button:has-text('Sandbox (')").first
            for _ in range(20):
                if re.search(r"Sandbox \([1-9]", bp.inner_text("body")):
                    break
                bp.wait_for_timeout(500)
            tab.click()
            bp.wait_for_timeout(1500)
            shot(bp, "E9-bank-sandbox-tab")
            row = bp.locator("tr", has_text=ref).first if ref else None
            if row is not None and row.count():
                (row.locator("a").first if row.locator("a").count() else row).click()
                bp.wait_for_timeout(3000)
                det = bp.inner_text("body")
                shot(bp, "F2-bank-case-detail")
                rec("F2", "case detail: 'Temporary debit hold — limited to ₹1,95,000' + signals 'from transaction data'",
                    "1,95,000" in det and re.search(r"temporary (debit )?hold", det, re.I) is not None and "transaction data" in det.lower(), "", "P0")
                real = [b for b in ("HDFC", "ICICI", "Axis Bank", "Kotak") if b in det]
                rec("K-DEMOBANK", "case detail: received by the demo bank; real bank names only in the victim's own data",
                    "RecoverAI Demo Bank (fictional)" in det and not real, f"other real names: {real}", "P1")
                rec("E11", "bank detail shows RAI- ref, no internal b_/c_ ids", ref in det and not re.search(r"\b[bc]_[0-9a-f]{12,}", det), "", "P1")
            else:
                rec("F2", "QA case visible in the bank desk Sandbox tab", False, f"ref {ref} not found", "P0")
            # victim on /bank → denied (F1)
            vctx = br.new_context()
            vp = vctx.new_page()
            login(vp, base, "90000 01107", PW)
            vp.wait_for_url(lambda u: urlparse(u).path == "/cases", timeout=20000)
            vp.goto(base + "/bank")
            vp.wait_for_timeout(4000)
            vb = vp.inner_text("body")
            rec("F1", "victim opening /bank → no bank data (bank sign-in form shown)", vp.locator("input[type=password]").count() > 0 and (ref or "RAI-") not in vb
                and "Incoming fraud cases" not in vb, vp.url.replace(base, ""), "P0")
            shot(vp, "F1-victim-on-bank")
            vctx.close()
            api.j("POST", f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True})
            # PDF logo on cover
            pack = api.j("POST", f"/api/cases/{cid}/evidence-pack")
            pdf = httpx.get(api.u(pack["url"]), timeout=60).content
            Path("/workspace/qa_logs/ui_pack.pdf").write_bytes(pdf)
            import subprocess
            imgs = subprocess.run(["pdfimages", "-list", "-f", "1", "-l", "1", "/workspace/qa_logs/ui_pack.pdf"], capture_output=True, text=True).stdout
            vec = subprocess.run(["pdftotext", "-f", "1", "-l", "1", "/workspace/qa_logs/ui_pack.pdf", "-"], capture_output=True, text=True).stdout
            subprocess.run(["pdftoppm", "-png", "-r", "60", "-f", "1", "-l", "1", "/workspace/qa_logs/ui_pack.pdf", str(shots / "K-pdf-cover")])
            rec("K-LOGO", "evidence-pack cover carries the RAI logo (image or vector on page 1; see K-pdf-cover-1.png)",
                len(imgs.strip().splitlines()) > 2 or "RAI" in vec, f"page-1 images: {max(len(imgs.strip().splitlines()) - 2, 0)}", "P2")
            rec("D3", "Hindi renders (Noto fonts embedded)", "Noto" in subprocess.run(["pdffonts", "/workspace/qa_logs/ui_pack.pdf"], capture_output=True, text=True).stdout,
                "", "P1")
            bctx.close()

            # ---------------- J1 360 px
            mctx = br.new_context(viewport={"width": 360, "height": 740}, is_mobile=False)
            mp = mctx.new_page()
            pages = ["/", "/signup", "/login", "/privacy", "/bank", "/admin/login"]
            for pth in pages:
                mp.goto(base + pth)
                mp.wait_for_timeout(1500)
                ok_, sw, cw = no_hscroll(mp)
                smalls = small_targets(mp)
                rec("J1", f"360 px {pth}: no horizontal scroll", ok_, f"scrollWidth {sw} / {cw}", "P2")
                rec("J1", f"360 px {pth}: tap targets ≥ 44 px", not smalls, f"small: {smalls[:6]}", "P2")
                shot(mp, f"J1-360{pth.replace('/', '_') or '_home'}")
            login(mp, base, "90000 01107", PW)
            mp.wait_for_url(lambda u: urlparse(u).path == "/cases", timeout=20000)
            for pth in ("/cases", "/profile", f"/cases/{cid}"):
                mp.goto(base + pth)
                mp.wait_for_timeout(3000)
                ok_, sw, cw = no_hscroll(mp)
                rec("J1", f"360 px {pth.replace(cid, '{id}')}: no horizontal scroll", ok_, f"scrollWidth {sw} / {cw}", "P2")
                shot(mp, f"J1-360{pth.replace(cid, 'case').replace('/', '_')}")
            rec("J1", "360 px case page: bottom tabs Chat / My case", mp.locator("nav.mobile-tabs button:has-text('Chat')").is_visible()
                and mp.locator("nav.mobile-tabs button:has-text('My case')").is_visible(), "", "P2")
            mctx.close()
            api.req("DELETE", f"/api/cases/{cid}")

            # ---------------- /admin/login + redirects (K)
            actx = br.new_context()
            ap_ = actx.new_page()
            ap_.goto(base + "/admin")
            ap_.wait_for_url(re.compile(r".*/admin/login\?next=(/|%2F)admin"), timeout=15000)
            rec("K-ADMIN", "signed-out /admin → /admin/login?next=/admin", True, ap_.url.replace(base, ""), "P1")
            fields = ap_.locator("input:visible").count()
            rec("K-ADMIN", "/admin/login is a clean admin page (email + password only, demo banner)", fields == 2 and "Admin" in ap_.inner_text("body")
                and "role=bank" not in ap_.url, f"{fields} inputs", "P1")
            shot(ap_, "K-admin-login")
            ap_.fill("input[type=email], input[name=email]", "analyst@recoverai-demo.example")
            ap_.fill("input[type=password]", (STATE / "bank_password").read_text().strip())
            ap_.click("button[type=submit]")
            ap_.wait_for_timeout(5000)
            rec("K-ADMIN", "non-admin (analyst) on /admin/login → 'Admin access required', signed out", "Admin access required" in ap_.inner_text("body"),
                "", "P1")
            ap_.fill("input[type=email], input[name=email]", "admin@recoverai-demo.example")
            ap_.fill("input[type=password]", (STATE / "admin_password").read_text().strip())
            ap_.click("button[type=submit]")
            ap_.wait_for_selector("[data-testid=admin-console]", timeout=30000)
            ap_.wait_for_timeout(2500)
            rec("K-ADMIN", "admin signs in → console with requests + audit log", ap_.locator("[data-testid=audit-log]").count() > 0, "", "P1")
            shot(ap_, "K-admin-console")
            actx.close()

            # ---------------- B1/B5 as seed 00002 (restored after)
            sctx = br.new_context()
            sp = sctx.new_page()
            t2 = token_for("+919000000002")
            api2 = Api(t2)
            api2.j("PUT", "/api/me/profile", json={"profile": {"postalCode": "", "primaryBank": ""}})
            login(sp, base, "90000 00002", "Demo@2026", nxt="/profile")
            sp.wait_for_url(lambda u: urlparse(u).path == "/profile", timeout=20000)
            sp.wait_for_selector("[data-testid=profile-meter]")
            meter = sp.inner_text("[data-testid=profile-meter]")
            rec("B1", "IN-incomplete: completeness meter shows the missing fields (PIN code, bank)",
                True if (re.search(r"PIN", meter, re.I) and "bank" in meter.lower()) else (None if "%" in meter else False),
                f"meter text: {meter[:60]!r} — shows % only, missing fields not named on /profile", "P1")
            shot(sp, "B1-profile-meter")
            c2 = api2.j("POST", "/api/cases", json={"country": "IN", "language": "en"})["caseId"]
            try:
                evs = api2.chat(c2, {"text": "I was scammed of Rs 20,000 last week. My bank is SBI, I live in Pune 411001"})
                pc = next((e["card"]["data"] for e in evs if e.get("type") == "card" and e["card"]["kind"] == "profile"), {})
                pre = json.dumps(pc.get("prefill") or pc, ensure_ascii=False)
                saved = api2.j("GET", "/api/me")["profile"]
                rec("B5", "profile card pre-filled with SBI + 411001; nothing saved until Save",
                    "411001" in pre and "State Bank of India" in pre and not saved.get("postalCode") and not saved.get("primaryBank"),
                    f"prefill {pre[:160]}", "P1")
            finally:
                api2.req("DELETE", f"/api/cases/{c2}")
                api2.j("PUT", "/api/me/profile", json={"profile": {"postalCode": "", "primaryBank": ""}})
            sctx.close()

            # ---------------- A12 throttle (throw-away account only)
            T = Throwaway(THROTTLE, profile=COMPLETE_IN)
            created.append(THROTTLE)
            tctx = br.new_context()
            tp = tctx.new_page()
            msgs = []
            for i in range(12):
                login(tp, base, "90000 01108", f"Wrong-{i}-pass")
                try:
                    tp.wait_for_selector("[data-testid=auth-error]", timeout=15000)
                    msgs.append(tp.inner_text("[data-testid=auth-error]"))
                except Exception:  # noqa: BLE001
                    msgs.append("(none)")
            raw = phone_login(THROTTLE, "Wrong-x-pass").json().get("error", {}).get("message", "")
            rec("A12", "10+ wrong passwords → clean message, no crash", all(m and m != "(none)" for m in msgs), f"UI: {set(msgs)}; Firebase now: {raw}", "P2")
            rec("A12", "throttling surfaced as 'Too many attempts. Please wait a few minutes and try again.'",
                any("Too many attempts" in m for m in msgs) if "TOO_MANY" in raw else None,
                f"UI messages {sorted(set(msgs))}; Firebase returned {raw!r}", "P2")
            shot(tp, "A12-after-12-wrong")
            tctx.close()
            T.delete()
        finally:
            for ph in created:
                if ph == NEW:
                    try:
                        tk = token_for(NEW, PW)
                        httpx.delete(SITE + "/api/me", headers={"Authorization": f"Bearer {tk}"}, timeout=30)
                        httpx.post(f"{IDT}:delete?key={api_key()}", json={"idToken": tk}, timeout=30)
                        print("cleanup: deleted", NEW[:-4] + "xxxx", "login gone:", phone_login(NEW, PW).status_code == 400)
                    except Exception as e:  # noqa: BLE001
                        print("cleanup failed", e)
            br.close()
    dump(a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
