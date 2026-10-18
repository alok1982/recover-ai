#!/usr/bin/env python3
"""QA BUG-09 / I3: the Content-Security-Policy in firebase.json, checked in real headless browsers on every page.

  --inject : before deploying. The live site is loaded, and the CSP from firebase.json is added to each HTML document
             response by request interception, so the browser enforces exactly that policy on the real origin (same
             Firebase Auth, Firestore, Cloud Run chat origin and GCS signed URLs as production).
  default  : after deploying. Checks that Hosting serves the CSP and that the browser reports no violations.

Pages: home, signup, login, privacy, victim /cases, co-pilot (image upload + streamed chat + mic recording), /profile,
bank desk + case detail with evidence images, admin console. Passes only with zero CSP violations and zero CSP console
errors. Throw-away victim +91 90000 01115 (deleted at the end); its sandbox bank copy is deleted too.

  python scripts/qa/csp_check.py [--inject] [--browser chromium|webkit|firefox] [--out /workspace/qa_logs/p2/csp.json]
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import FIX, ROOT, SITE, STATE, COMPLETE_IN, Throwaway, rec, dump  # noqa: E402
from copilot_api_checks import send, story_case  # noqa: E402

PHONE = "+919000001115"
PW = "QaCsp2026x7"
HOOK = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(
  {dir: e.effectiveDirective, uri: e.blockedURI, src: (e.sourceFile || '') + ':' + e.lineNumber, sample: e.sample}));
"""


def csp_from_firebase() -> str:
    d = json.loads((ROOT / "firebase.json").read_text())
    for h in d["hosting"]["headers"]:
        if h["source"] == "**":
            for kv in h["headers"]:
                if kv["key"] == "Content-Security-Policy":
                    return kv["value"]
    raise SystemExit("no CSP in firebase.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inject", action="store_true")
    ap.add_argument("--browser", default="chromium")
    ap.add_argument("--base", default=SITE)
    ap.add_argument("--out", default="/workspace/qa_logs/p2/csp.json")
    ap.add_argument("--shots", default="/workspace/qa_logs/p2/csp_shots")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    csp = csp_from_firebase()
    shots = Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    violations: list[dict] = []
    console_csp: list[str] = []
    served: dict[str, str | None] = {}

    T = Throwaway(PHONE, pw=PW, profile=COMPLETE_IN)
    bank_case = None
    try:
        api = T.api
        cid, _info = story_case(api, "en", "CSP")
        sent = send(api, cid)
        bank_case = (sent.get("case") or {}).get("bankCaseId")
        ref = (sent.get("case") or {}).get("publicRef")
        cid2 = api.j("POST", "/api/cases", json={"country": "IN", "language": "en"})["caseId"]  # fresh case for the UI upload

        with sync_playwright() as p:
            kind = getattr(p, a.browser)
            args = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"] if a.browser == "chromium" else []
            br = kind.launch(args=args) if args else kind.launch()

            def new_page(ctx):
                pg = ctx.new_page()
                pg.on("console", lambda m: console_csp.append(f"{pg.url}: {m.text[:300]}")
                      if re.search(r"Content.Security.Policy|Refused to", m.text, re.I) else None)
                return pg

            def ctx_new():
                kw = {"viewport": {"width": 1280, "height": 860}}
                if a.browser == "chromium":
                    kw["permissions"] = ["microphone"]
                ctx = br.new_context(**kw)
                ctx.add_init_script(HOOK)
                if a.inject:
                    def handle(route, request):
                        if request.resource_type != "document" or not request.url.startswith(base):
                            return route.continue_()
                        resp = route.fetch()
                        h = {k: v for k, v in resp.headers.items() if k.lower() != "content-security-policy"}
                        h["content-security-policy"] = csp
                        route.fulfill(response=resp, headers=h)
                    ctx.route("**/*", handle)
                ctx.on("response", lambda r: served.__setitem__(r.url.split("?")[0], r.headers.get("content-security-policy"))
                       if r.request.resource_type == "document" else None)
                return ctx

            def harvest(pg, label):
                try:
                    v = pg.evaluate("window.__csp || []")
                except Exception:  # noqa: BLE001
                    v = []
                for x in v:
                    violations.append({"page": label, **x})
                pg.screenshot(path=str(shots / f"{a.browser}-{label}.png"))
                rec("I3", f"[{a.browser}] {label}: no CSP violations", not v, json.dumps(v)[:300] if v else "", "P2")

            # public pages
            ctx = ctx_new()
            pg = new_page(ctx)
            for path, label, sel in (("/", "home", "[data-testid=emergency-strip]"), ("/signup", "signup", "input[name=phone]"),
                                     ("/login", "login", "input[name=phone]"), ("/privacy", "privacy", "h1, h2")):
                pg.goto(base + path)
                pg.wait_for_selector(sel, timeout=20000)
                pg.wait_for_timeout(1200)
                harvest(pg, label)
            # victim: login → cases → co-pilot (stream + upload + mic) → profile
            pg.goto(base + "/login?next=/cases")
            pg.select_option("[data-testid=cc]", "IN")
            pg.fill("input[name=phone]", PHONE[3:])
            pg.fill("input[name=password]", PW)
            pg.click("button[type=submit]")
            pg.wait_for_url(re.compile(r".*/cases$"), timeout=30000)
            pg.wait_for_timeout(2000)
            harvest(pg, "cases")
            pg.goto(base + f"/cases/{cid}")
            pg.wait_for_selector("textarea", timeout=30000)
            pg.wait_for_timeout(2500)  # history incl. drafts card, timeline, live listener
            harvest(pg, "copilot-history")
            pg.goto(base + f"/cases/{cid2}")
            pg.wait_for_selector("textarea", timeout=30000)
            puts: list[int] = []
            pg.on("response", lambda r: puts.append(r.status) if r.request.method == "PUT" else None)
            with pg.expect_response(lambda r: r.request.method == "POST" and re.search(r"/evidence$", r.url) is not None,
                                    timeout=60000) as ev:
                pg.locator(".inputbar input[type=file]").set_input_files(str(FIX / "in_upi_success.png"))
            rec("I3", f"[{a.browser}] co-pilot image upload (signed-URL PUT + register) under the CSP",
                ev.value.status == 200 and bool(puts) and all(x < 300 for x in puts), f"PUT {puts}, register {ev.value.status}", "P2")
            pg.wait_for_timeout(12000)
            n0 = pg.locator("textarea").count()
            pg.fill("textarea", "What should I do first?")
            pg.keyboard.press("Enter")
            t0 = time.time()
            pg.wait_for_timeout(1500)
            for _ in range(60):
                if not pg.locator("textarea[disabled], .inputbar button[disabled]").count():
                    break
                pg.wait_for_timeout(500)
            pg.wait_for_timeout(2000)
            body = pg.inner_text("body")
            rec("I3", f"[{a.browser}] co-pilot: upload + streamed reply arrive under the CSP", n0 > 0 and "What should I do first?" in body,
                f"{time.time() - t0:.1f}s", "P2")
            mic = pg.locator(".inputbar button.mic")
            if a.browser == "chromium" and mic.count():
                mic.click()
                pg.wait_for_timeout(2500)
                pg.locator(".inputbar button.mic").click()
                pg.wait_for_timeout(6000)
                rec("I3", f"[{a.browser}] mic recording + voice upload run under the CSP", True,
                    (pg.locator("[data-testid=voice-hint]").inner_text() if pg.locator("[data-testid=voice-hint]").count() else "no hint"), "P2")
            harvest(pg, "copilot-upload-chat-mic")
            pg.goto(base + "/profile")
            pg.wait_for_selector("input, select", timeout=20000)
            pg.wait_for_timeout(1500)
            harvest(pg, "profile")
            ctx.close()

            # bank desk + case detail with evidence images
            ctx = ctx_new()
            bp = new_page(ctx)
            bp.goto(base + "/bank")
            bp.wait_for_selector("input[type=email]", timeout=20000)
            bp.fill("input[type=email]", "analyst@recoverai-demo.example")
            bp.fill("input[type=password]", (STATE / "bank_password").read_text().strip())
            bp.click("button:has-text('Sign in')")
            bp.wait_for_selector("[data-testid=desk-title]", timeout=30000)
            bp.wait_for_timeout(2500)
            harvest(bp, "bank-desk")
            for _ in range(20):
                if re.search(r"Sandbox \([1-9]", bp.inner_text("body")):
                    break
                bp.wait_for_timeout(500)
            bp.locator("button:has-text('Sandbox (')").first.click()
            bp.wait_for_timeout(1500)
            row = bp.locator("tr", has_text=ref).first
            (row.locator("a").first if row.locator("a").count() else row).click()
            bp.wait_for_timeout(5000)
            imgs = bp.evaluate("[...document.querySelectorAll('main img')].filter(i => !i.classList.contains('logo'))"
                               ".map(i => [i.src.slice(0, 40), i.complete && i.naturalWidth > 0])")
            rec("I3", f"[{a.browser}] bank case detail: evidence images load (GCS signed URL) under the CSP",
                bool(imgs) and all(ok for _, ok in imgs), json.dumps(imgs)[:200], "P2")
            harvest(bp, "bank-case-detail")
            ctx.close()

            # admin console
            ctx = ctx_new()
            ad = new_page(ctx)
            ad.goto(base + "/admin/login")
            ad.wait_for_selector("input[name=email], input[type=email]", timeout=20000)
            harvest(ad, "admin-login")
            ad.fill("input[type=email], input[name=email]", "admin@recoverai-demo.example")
            ad.fill("input[type=password]", (STATE / "admin_password").read_text().strip())
            ad.click("button[type=submit]")
            ad.wait_for_selector("[data-testid=audit-log]", timeout=30000)
            ad.wait_for_timeout(2500)
            harvest(ad, "admin-console")
            ctx.close()
            br.close()
        for c in (cid, cid2):
            api.req("DELETE", f"/api/cases/{c}")
    finally:
        T.delete()
        if bank_case:
            try:
                from google.cloud import firestore
                db = firestore.Client(project="recoverai-511917")
                r = db.collection("bank_cases").document(bank_case)
                for sub in r.collections():
                    for s in sub.stream():
                        s.reference.delete()
                r.delete()
                print("deleted QA bank copy", bank_case)
            except Exception as e:  # noqa: BLE001
                print("bank copy cleanup failed", bank_case, e)

    rec("I3", f"[{a.browser}] no CSP errors in the console on any page", not console_csp, "; ".join(console_csp)[:400], "P2")
    if not a.inject:
        docs = {u: v for u, v in served.items() if u.startswith(base)}
        rec("I3", f"[{a.browser}] Hosting serves the CSP on every HTML document", bool(docs) and all(v == csp for v in docs.values()),
            f"{sum(1 for v in docs.values() if v == csp)}/{len(docs)} documents", "P2")
    Path(a.out).write_text(json.dumps({"mode": "inject" if a.inject else "live", "browser": a.browser, "csp": csp,
                                       "violations": violations, "console": console_csp}, indent=1))
    dump(a.out.replace(".json", "_rec.json"))
    print("VIOLATIONS", len(violations), "CONSOLE", len(console_csp))
    return 0 if not violations and not console_csp else 1


if __name__ == "__main__":
    sys.exit(main())
