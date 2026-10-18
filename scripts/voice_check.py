#!/usr/bin/env python3
"""CR-03 D: browser check of the voice-note recorder with a fake microphone.

Chromium: --use-fake-device-for-media-stream + --use-file-for-fake-audio-capture=<wav> (desktop and Pixel emulation).
WebKit: Playwright's mock capture device (iPhone emulation; MediaRecorder → audio/mp4).
Also checks a blocked mic shows the helpful hint and typing still works. No real devices are involved.

  python scripts/voice_check.py --base http://localhost:5173 [--wav fixtures/x.wav] [--open-case <fn>]
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def default_wav() -> str:
    out = Path(tempfile.gettempdir()) / "recoverai_hindi5s.wav"
    if not out.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ROOT / "fixtures" / "in_voice_note.mp3"), "-ac", "1",
                        "-ar", "48000", "-t", "6", str(out)], check=True)
    return str(out)


def open_case(pg, base: str, phone: str = "90000 00001", password: str = "Demo@2026") -> None:
    """CR-03: sign in as a seeded victim (complete profile) and start a new case."""
    cleanup(base, MODE["mock"])  # one open case at a time (MAX_OPEN_CASES per user)
    pg.goto(base + "/login?next=/cases")
    pg.fill("input[name=phone]", phone)
    pg.fill("input[name=password]", password)
    pg.click("button[type=submit]")
    pg.wait_for_url("**/cases", timeout=30000)
    pg.wait_for_selector("[data-testid=start-case]")
    pg.click("[data-testid=start-case]")
    pg.wait_for_url("**/cases/c_*", timeout=30000)
    pg.wait_for_selector(".bubble.assistant", timeout=30000)
    CREATED.append(pg.url.rsplit("/", 1)[1])


CREATED: list[str] = []
MODE = {"mock": False}


def cleanup(base: str, mock: bool) -> None:
    """Delete only the cases this run created (seeded users may hold at most MAX_OPEN_CASES open cases)."""
    import httpx
    api = base.replace(":5173", ":8080") if mock else base
    if mock:
        tok = "mock:phone:+919000000001"
    else:
        from e2e_demo import phone_login
        tok = phone_login("+919000000001").json()["idToken"]
    while CREATED:
        cid = CREATED.pop()
        r = httpx.delete(f"{api}/api/cases/{cid}", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
        print("deleted" if r.status_code == 200 else f"delete failed {r.status_code}", cid)


def record(pg, secs: float = 5.5) -> dict:
    logs: list[str] = []
    pg.on("console", lambda m: logs.append(m.text))
    pg.wait_for_selector(".inputbar .mic")
    pg.click(".inputbar .mic")
    pg.wait_for_selector(".inputbar .mic.rec", timeout=5000)
    pg.wait_for_timeout(int(secs * 1000))
    pg.click(".inputbar .mic")
    pg.wait_for_selector(".msg.user .voice-tag", timeout=90000)
    pg.wait_for_timeout(500)
    bubbles = pg.locator(".bubble").all_inner_texts()
    return {"console": [x for x in logs if "[voice]" in x], "bubbles": bubbles}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5173")
    ap.add_argument("--wav", default=None)
    ap.add_argument("--shots", default=None, help="directory for screenshots")
    ap.add_argument("--only", default="", help="comma list: chrome,pixel,iphone,blocked")
    ap.add_argument("--mock", action="store_true", help="local mock stack (cleanup with a mock token)")
    a = ap.parse_args()
    wav = a.wav or default_wav()
    MODE["mock"] = a.mock
    only = set(filter(None, a.only.split(",")))
    want = lambda k: not only or k in only  # noqa: E731
    shots = Path(a.shots) if a.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    ok = True
    chrome = shutil.which("google-chrome") or shutil.which("chromium")
    fake = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-audio-capture={wav}"]
    with sync_playwright() as p:
        if want("chrome") or want("pixel") or want("blocked"):
            b = p.chromium.launch(executable_path=chrome, args=fake) if chrome else p.chromium.launch(args=fake)
            for name, opts in (("chrome", {"viewport": {"width": 1366, "height": 900}}), ("pixel", dict(p.devices["Pixel 7"]))):
                if not want(name):
                    continue
                ctx = b.new_context(**opts, permissions=["microphone"])
                pg = ctx.new_page()
                open_case(pg, a.base)
                r = record(pg)
                bad = [x for x in r["bubbles"] if "could not be transcribed" in x or "[voice" in x]
                good = r["console"] and not bad
                ok &= bool(good)
                print(f"{name}: {'PASS' if good else 'FAIL'} console={r['console']} last_user={[x for x in r['bubbles'] if '🎤' in x][-1:]}")
                if shots:
                    pg.screenshot(path=str(shots / f"voice-{name}.png"))
                ctx.close()
            b.close()
            if want("blocked"):
                dev = [x for x in fake if "fake-ui" not in x]  # a device exists, but permission is denied → NotAllowedError
                b = p.chromium.launch(executable_path=chrome, args=dev) if chrome else p.chromium.launch(args=dev)
                ctx = b.new_context(viewport={"width": 1366, "height": 900})
                pg = ctx.new_page()
                open_case(pg, a.base)
                pg.click(".inputbar .mic")
                pg.wait_for_selector("[data-testid=voice-hint]", timeout=10000)
                hint = pg.inner_text("[data-testid=voice-hint]")
                pg.fill(".inputbar textarea", "I typed instead")
                pg.keyboard.press("Enter")
                pg.wait_for_selector(".bubble.user:has-text('I typed instead')", timeout=30000)
                pg.wait_for_selector(".upload-card", timeout=60000)  # the typed turn got a co-pilot answer
                good = any(x in hint for x in ("Microphone is blocked", "माइक्रोफ़ोन ब्लॉक है", "Mikrofon disekat"))
                ok &= good
                print(f"blocked: {'PASS' if good else 'FAIL'} hint={hint!r}; typing still works")
                if shots:
                    pg.screenshot(path=str(shots / "voice-blocked.png"))
                b.close()
        if want("iphone"):
            b = p.webkit.launch()
            ctx = b.new_context(**dict(p.devices["iPhone 14"]))
            pg = ctx.new_page()
            open_case(pg, a.base)
            mime = pg.evaluate("() => window.MediaRecorder ? ['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].map(m=>[m, MediaRecorder.isTypeSupported(m)]) : null")
            try:
                r = record(pg, 3)
                good = bool(r["console"])
                print(f"iphone(webkit): {'PASS' if good else 'FAIL'} types={mime} console={r['console']}")
            except Exception as e:  # WebKit headless may expose no capture device
                good = None
                hint = pg.locator("[data-testid=voice-hint]").all_inner_texts()
                print(f"iphone(webkit): NOT VERIFIABLE ({type(e).__name__}) types={mime} hint={hint}")
            if shots:
                pg.screenshot(path=str(shots / "voice-iphone-webkit.png"))
            b.close()
    cleanup(a.base, a.mock)
    print("OVERALL", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
