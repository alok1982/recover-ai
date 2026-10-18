#!/usr/bin/env python3
"""Browser smoke test of the India + bank storyline against a local mock stack; saves docs/screenshots.

  backend: MOCK_MODE=true uvicorn app.main:app --port 8080   frontend: VITE_MOCK=true npm run dev
  python scripts/ui_smoke.py [--base http://localhost:5173]
"""
import argparse
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "docs" / "screenshots"
FIX = ROOT / "fixtures"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    a = ap.parse_args()
    SHOTS.mkdir(parents=True, exist_ok=True)
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome) if chrome else p.chromium.launch()
        pg = b.new_page(viewport={"width": 1366, "height": 900})
        pg.on("pageerror", lambda e: print("PAGE ERROR:", e))
        pg.goto(a.base)
        pg.screenshot(path=str(SHOTS / "00-landing.png"))
        on = lambda: pg.locator(".pickers .seg-btn.on").all_inner_texts()  # noqa: E731
        assert "English" in on(), f"English must be the default language, got {on()}"
        pg.locator(".pickers .seg-btn", has_text="Malaysia").click()
        assert "English" in on(), f"switching country must keep English, got {on()}"
        pg.locator(".pickers .seg-btn", has_text="India").click()
        pg.locator(".pickers .seg-btn", has_text="हिन्दी").click()  # the demo storyline picks Hindi explicitly
        pg.get_by_role("button", name="मेरे साथ ठगी हुई — रिकवरी शुरू करें").click()
        pg.wait_for_url("**/case/**")
        pg.fill(".inputbar textarea", "मैंने CBI वाले को 1,95,000 भेज दिए")
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".upload-card")
        assert pg.locator(".upload-card input[type=file][capture=environment]").count() == 1, "camera input"
        assert pg.locator(".upload-card button.camera").count() == 1, "camera button"
        pg.set_input_files(".upload-card input[type=file]:not([capture])", str(FIX / "in_upi_success.png"))
        pg.wait_for_selector(".upload-card .evidence-list li .ev-type-time")
        assert "·" in pg.locator(".upload-card .ev-type-time").first.inner_text(), "evidence type + time"
        pg.fill(".upload-card textarea.paste", (FIX / "in_whatsapp_scam.txt").read_text())
        pg.get_by_role("button", name="टेक्स्ट जोड़ें").click()
        pg.wait_for_selector(".upload-card .evidence-list li:nth-child(2)")
        pg.get_by_role("button", name="मेरे सबूत पढ़ें").click()
        pg.wait_for_selector(".facts-card")
        pg.wait_for_timeout(600)
        reds = pg.locator(".facts-card tr.lvl-red").count()
        assert pg.locator(".facts-card tr.lvl-red .chip.warn").count() == reds, "check-this chip on every red row"
        pg.screenshot(path=str(SHOTS / "01-copilot-facts-card.png"))
        pg.get_by_role("button", name="✓ सही है").click()
        pg.wait_for_selector(".plan-card")
        pg.wait_for_timeout(1500)
        pg.get_by_role("button", name="✍️ सब तैयार करें").click()
        pg.wait_for_selector(".drafts-card")
        pg.wait_for_selector(".consent-card")
        pg.wait_for_timeout(800)
        pg.locator(".plan-card").scroll_into_view_if_needed()
        pg.screenshot(path=str(SHOTS / "02-copilot-plan-drafts-panel.png"))
        pg.get_by_role("button", name="✓ मेरे बैंक से साझा करें").click()
        pg.wait_for_selector(".timeline-card")
        case_url = pg.url
        # gap 3: mark a clock's step done from the timeline card, with a reference
        tl = pg.locator(".timeline-card")
        tl.locator(".clock-steps .mark-done button").first.click()
        tl.locator(".clock-steps .mark-done input").first.fill("ACK-SMOKE-1")
        tl.locator(".clock-steps .mark-done button.primary").first.click()
        pg.wait_for_selector(".timeline-card .chip:has-text('ACK-SMOKE-1')")
        pg.wait_for_selector(".plan-card .chip:has-text('ACK-SMOKE-1')")
        # gap 5: evidence hashes in the case panel
        pg.locator(".panel .hashes button").click()
        pg.wait_for_selector(".panel .hash-list .sha")
        shas = pg.locator(".panel .hash-list .sha").all_inner_texts()
        assert len(shas) == 2 and all(len(x.strip()) == 64 for x in shas), shas

        bank = b.new_page(viewport={"width": 1366, "height": 900})
        bank.goto(a.base + "/bank")
        bank.get_by_role("button", name="Sign in").click()
        bank.wait_for_selector(".inbox tbody tr a")
        bank.screenshot(path=str(SHOTS / "03-bank-inbox.png"))
        bank.locator(".inbox tbody tr a").first.click()
        bank.wait_for_selector(".signals li")
        bank.screenshot(path=str(SHOTS / "04-bank-case-detail.png"), full_page=True)
        # gap 1: a second open detail view updates without reload
        watcher = b.new_page(viewport={"width": 1366, "height": 900})
        detail_url = bank.url
        watcher.goto(a.base + "/bank")
        watcher.get_by_role("button", name="Sign in").click()
        watcher.wait_for_selector(".inbox tbody tr a")
        watcher.goto(detail_url)
        watcher.wait_for_selector(".signals li")
        bank.get_by_role("button", name="Approve temporary hold").click()
        bank.wait_for_selector(".pill.bstat-HOLD_APPROVED")
        watcher.wait_for_selector(".pill.bstat-HOLD_APPROVED", timeout=8000)
        watcher.close()
        bank.get_by_role("link", name="Scam intelligence").click()
        bank.wait_for_selector(".intel table tbody tr")
        bank.wait_for_timeout(500)
        bank.screenshot(path=str(SHOTS / "09-bank-scam-intelligence.png"), full_page=True)

        pg.goto(case_url)
        pg.wait_for_selector("text=अस्थायी रोक", timeout=10000)
        # F17: light question → Gemma chip (backend started with CHAT_LIGHT_MODEL set); earlier replies → Gemini chip
        if (pg.request.get(a.base + "/api/health").json() or {}).get("chatLight"):
            pg.fill(".inputbar textarea", "अब मुझे क्या करना है?")
            pg.keyboard.press("Enter")
            pg.wait_for_selector(".messages .model-chip.gemma")
            assert pg.locator(".messages .model-chip.gemini").count() >= 1, "Gemini chip on full turns"
            pg.wait_for_timeout(1200)
            pg.locator(".messages .model-chip.gemma").last.scroll_into_view_if_needed()
            pg.locator(".chat").screenshot(path=str(SHOTS / "10-model-chips.png"))
        pg.fill(".inputbar textarea", "Pay ₹5,000 fee and we recover your money")
        pg.keyboard.press("Enter")
        pg.wait_for_selector(".warning-card")
        pg.wait_for_timeout(500)
        pg.screenshot(path=str(SHOTS / "05-recovery-scam-warning.png"))
        pg.get_by_role("button", name="दिन 31 पर जाएँ").click()
        pg.wait_for_selector(".escalation-card", timeout=10000)
        pg.wait_for_timeout(500)
        pg.locator(".escalation-card").scroll_into_view_if_needed()
        pg.screenshot(path=str(SHOTS / "06-day31-escalation.png"))

        m = pg
        m.set_viewport_size({"width": 360, "height": 780})
        m.goto(case_url)
        m.wait_for_selector(".messages .msg")
        tabs = m.locator(".mobile-tabs").bounding_box()
        assert tabs and abs(tabs["y"] + tabs["height"] - 780) < 2, ("tabs at bottom", tabs)
        mic = m.locator(".inputbar .icon-btn.mic").bounding_box()
        assert mic and mic["width"] >= 60 and mic["y"] + mic["height"] <= tabs["y"], ("mic", mic)
        m.screenshot(path=str(SHOTS / "07-mobile-360.png"))
        m.get_by_role("button", name="मेरा केस").click()
        m.screenshot(path=str(SHOTS / "08-mobile-my-case.png"))
        b.close()
    print("UI smoke OK; screenshots in", SHOTS)


if __name__ == "__main__":
    main()
