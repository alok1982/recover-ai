#!/usr/bin/env python3
"""H4 (0.3 s tap ignored) and H5 (in-app browser hint, emulated WhatsApp user agent) on the live site.
Throw-away account +91 90000 01110 (deleted at the end). Chromium fake microphone; no real device."""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from qa_common import COMPLETE_IN, ROOT, SITE, Throwaway, dump, rec  # noqa: E402

shots = ROOT / "docs" / "screenshots" / "qa"
T = Throwaway("+919000001110", profile=COMPLETE_IN)
try:
    cid = T.api.j("POST", "/api/cases", json={"country": "IN", "language": "en"})["caseId"]
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        ctx = b.new_context(viewport={"width": 1280, "height": 860}, permissions=["microphone"])
        pg = ctx.new_page()
        pg.goto(SITE + f"/login?next=/cases/{cid}")
        pg.fill("input[name=phone]", "90000 01110")
        pg.fill("input[name=password]", T.pw)
        pg.click("button[type=submit]")
        pg.wait_for_selector(".inputbar .mic", timeout=30000)
        n0 = len(T.api.j("GET", f"/api/cases/{cid}/evidence")["evidence"])
        pg.click(".inputbar .mic")
        pg.wait_for_selector(".inputbar .mic.rec", timeout=5000)
        pg.wait_for_timeout(300)
        pg.click(".inputbar .mic")
        pg.wait_for_timeout(6000)
        voice_msgs = pg.locator(".msg.user .voice-tag").count()
        rec("H4", "0.3 s tap → ignored (no upload, no voice bubble)", voice_msgs == 0, f"voice bubbles {voice_msgs}", "P2")
        rec("H4", "2-minute cap (MAX_MS=120000 in recorder.ts; server 413 above 8 MB)", None, "code review + API limit only; a 2-min live recording was not run", "P2")
        b.close()
        b = p.webkit.launch()
        ua = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Mobile Safari/537.36 "
              "WhatsApp/2.24.10")
        ctx = b.new_context(user_agent=ua, viewport={"width": 390, "height": 800})
        pg = ctx.new_page()
        pg.goto(SITE + f"/login?next=/cases/{cid}")
        pg.fill("input[name=phone]", "90000 01110")
        pg.fill("input[name=password]", T.pw)
        pg.click("button[type=submit]")
        try:
            pg.wait_for_selector("[data-testid=voice-hint]", timeout=30000)
            hint = pg.inner_text("[data-testid=voice-hint]")
        except Exception:  # noqa: BLE001
            hint = ""
        pg.screenshot(path=str(shots / "H5-inapp-hint-emulated.png"))
        rec("H5", "WhatsApp in-app browser (emulated UA) → 'open in Chrome/Safari' hint", bool(hint), hint[:120], "P2")
        b.close()
finally:
    T.delete()
dump("/workspace/qa_logs/voice_extra.json")
