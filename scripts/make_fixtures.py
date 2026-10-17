#!/usr/bin/env python3
"""Generate synthetic evidence fixtures (no real app logos, people or accounts).

  python scripts/make_fixtures.py            # PNG screenshots (+ voice note if TTS is available) + manifest
Renders HTML mocks to PNG with Playwright if installed, else headless Chrome/Chromium.
The voice note uses Google Cloud Text-to-Speech (Hindi) when ADC is available, else gTTS if installed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures"

CSS = """
body{margin:0;font-family:'Noto Sans',Arial,sans-serif;background:#eef2f5;}
.phone{width:380px;margin:0 auto;background:#fff;min-height:820px}
.top{background:%(accent)s;color:#fff;padding:22px 20px 70px;text-align:center}
.tick{width:74px;height:74px;border-radius:50%%;background:#fff;color:%(accent)s;font-size:46px;line-height:74px;margin:14px auto 10px;font-weight:700}
.amt{font-size:40px;font-weight:700;margin:6px 0}
.card{margin:-50px 16px 0;background:#fff;border-radius:14px;box-shadow:0 2px 10px rgba(0,0,0,.12);padding:16px 18px}
.row{display:flex;justify-content:space-between;padding:9px 0;border-bottom:1px solid #eee;font-size:14px}
.row b{color:#222;max-width:62%%;text-align:right;word-break:break-all}
.row span{color:#666}
.foot{color:#999;font-size:11px;text-align:center;padding:18px}
.badge{display:inline-block;font-size:11px;background:rgba(255,255,255,.25);padding:3px 8px;border-radius:8px}
"""

UPI_HTML = """<html><head><meta charset='utf-8'><style>%s</style></head><body><div class='phone'>
<div class='top'><div class='badge'>DemoPay UPI · SAMPLE</div><div class='tick'>✓</div>
<div>Payment Successful</div><div class='amt'>₹1,95,000</div><div>17 Oct 2026, 02:02 PM</div></div>
<div class='card'>
<div class='row'><span>Paid to</span><b>CBI Verification Desk</b></div>
<div class='row'><span>UPI ID</span><b>cbi.verify.desk@okdemo</b></div>
<div class='row'><span>Receiver bank</span><b>Sample Co-op Bk</b></div>
<div class='row'><span>From</span><b>Bank of Demo ••4821</b></div>
<div class='row'><span>UPI transaction ID (UTR)</span><b>612345678901</b></div>
<div class='row'><span>Date &amp; time</span><b>17/10/2026 14:02 IST</b></div>
<div class='row'><span>Status</span><b style='color:#1a7f37'>Completed</b></div>
</div><div class='foot'>Synthetic test image for RecoverAI — not a real app or transaction.</div></div></body></html>"""

MY_HTML = """<html><head><meta charset='utf-8'><style>%s</style></head><body><div class='phone'>
<div class='top'><div class='badge'>DemoBank Online · SAMPLE</div><div class='tick'>✓</div>
<div>DuitNow Transfer Successful</div><div class='amt'>RM 4,800.00</div><div>17 Oct 2026, 10:15 AM</div></div>
<div class='card'>
<div class='row'><span>Recipient</span><b>PUSAT KASTAM PARCEL</b></div>
<div class='row'><span>Account no.</span><b>5140 1234 5678</b></div>
<div class='row'><span>Recipient bank</span><b>Bank Contoh Berhad</b></div>
<div class='row'><span>From account</span><b>Bank Demo Malaysia ••7730</b></div>
<div class='row'><span>Reference no.</span><b>DN202610170042</b></div>
<div class='row'><span>Payment details</span><b>Duti kastam MY-PKG-77812</b></div>
<div class='row'><span>Date / time</span><b>17/10/2026 10:15 MYT</b></div>
</div><div class='foot'>Synthetic test image for RecoverAI — not a real bank or transaction.</div></div></body></html>"""

VOICE_TEXT_HI = ("आज दोपहर मुझे एक फ़ोन आया। उसने कहा कि वह सीबीआई से है और मेरे नाम पर ड्रग्स का पार्सल पकड़ा गया है। "
                 "उसने कहा कि मैं डिजिटल अरेस्ट में हूँ और जाँच के लिए पैसे भेजने होंगे। मैंने यूपीआई से एक लाख पचानवे हज़ार रुपये भेज दिए।")


def render(html: str, out: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "page.html"
        f.write_text(html, encoding="utf-8")
        try:
            from playwright.sync_api import sync_playwright  # type: ignore

            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_page(viewport={"width": 380, "height": 820}, device_scale_factor=2)
                pg.goto(f.as_uri())
                pg.screenshot(path=str(out), full_page=True)
                b.close()
                return
        except ImportError:
            pass
        chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)), None)
        if not chrome:
            sys.exit("Need Playwright or Chrome/Chromium to render fixtures")
        subprocess.run([chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", "--window-size=380,820", f"--screenshot={out}", f.as_uri()],
                       check=True, capture_output=True)


def make_voice(out: Path) -> bool:
    try:
        from google.cloud import texttospeech  # type: ignore

        client = texttospeech.TextToSpeechClient()
        resp = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=VOICE_TEXT_HI),
            voice=texttospeech.VoiceSelectionParams(language_code="hi-IN", name="hi-IN-Standard-A"),
            audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3),
        )
        out.write_bytes(resp.audio_content)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Cloud TTS unavailable ({type(e).__name__}); trying gTTS")
    try:
        from gtts import gTTS  # type: ignore

        gTTS(VOICE_TEXT_HI, lang="hi").save(str(out))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"gTTS unavailable ({type(e).__name__}); skipping voice note")
        return False


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> None:
    render(UPI_HTML % (CSS % {"accent": "#2b5ea7"}), FIX / "in_upi_success.png")
    render(MY_HTML % (CSS % {"accent": "#1f7a5a"}), FIX / "my_bank_transfer.png")
    voice = FIX / "in_voice_note.mp3"
    if not voice.exists():
        make_voice(voice)
    (FIX / "in_voice_note.txt").write_text(VOICE_TEXT_HI + "\n", encoding="utf-8")
    manifest = {
        "images": {
            sha(FIX / "in_upi_success.png"): {"file": "in_upi_success.png", "case": "in_case"},
            sha(FIX / "my_bank_transfer.png"): {"file": "my_bank_transfer.png", "case": "my_case"},
        },
        "audio": {},
    }
    if voice.exists():
        manifest["audio"][sha(voice)] = {"file": voice.name, "case": "in_case", "transcript_file": "in_voice_note.txt"}
    (FIX / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("fixtures written:", ", ".join(sorted(p.name for p in FIX.iterdir() if p.is_file())))


if __name__ == "__main__":
    main()
