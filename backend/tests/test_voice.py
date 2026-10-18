"""CR-03 Part D: voice MIME handling, ffmpeg transcode, multipart /voice endpoint, no placeholder bubbles."""
import shutil
import subprocess

import pytest

from app.agents import voice
from conftest import FIX, H
from helpers import sse


def test_mime_normalisation_and_extensions():
    assert voice.normalize_mime("audio/webm;codecs=opus") == "audio/webm"
    assert voice.normalize_mime("audio/mp4") == "audio/m4a"
    assert voice.normalize_mime("audio/ogg; codecs=opus") == "audio/ogg"
    assert voice.mime_for_path("cases/c/voice/x.webm") == "audio/webm"
    assert voice.mime_for_path("cases/c/voice/x.bin") is None


def test_upload_url_keeps_a_real_audio_extension(client):
    """Root cause: audio/webm used to be stored as .bin and sent to Gemini as application/octet-stream."""
    cid = client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=H()).json()["caseId"]
    for mime, ext in (("audio/webm;codecs=opus", ".webm"), ("audio/mp4", ".m4a"), ("audio/ogg;codecs=opus", ".ogg")):
        u = client.post(f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": mime, "purpose": "voice"}, headers=H()).json()
        assert u["path"].endswith(ext), (mime, u["path"])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_to_flac_transcodes_webm_and_mp3(tmp_path):
    webm = tmp_path / "a.webm"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libopus",
                    str(webm)], check=True)
    for data, ext in ((webm.read_bytes(), ".webm"), ((FIX / "in_voice_note.mp3").read_bytes(), ".mp3")):
        out = voice.to_flac(data, ext)
        assert out and out[:4] == b"fLaC"
    assert voice.to_flac(b"not audio", ".webm") is None


def test_voice_endpoint_returns_transcript_then_chat_turn(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=H()).json()["caseId"]
    data = (FIX / "in_voice_note.mp3").read_bytes()
    r = client.post(f"/api/cases/{cid}/voice", files={"file": ("v.mp3", data, "audio/mpeg")}, headers=H())
    assert r.status_code == 200, r.text
    assert r.json()["audioPath"].endswith(".mp3") and "सीबीआई" in r.json()["transcript"]
    ev = sse(client, cid, {"text": r.json()["transcript"], "audioPath": r.json()["audioPath"]})
    um = next(e for e in ev if e["type"] == "user_message")["message"]
    assert um["audioPath"] == r.json()["audioPath"] and "सीबीआई" in um["text"]


def test_unclear_voice_never_posts_a_placeholder_bubble(client, monkeypatch):
    async def none(*a, **k):
        return None
    monkeypatch.setattr(voice, "transcribe", none)
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H()).json()["caseId"]
    r = client.post(f"/api/cases/{cid}/voice", files={"file": ("v.webm", b"\x1aE\xdf\xa3" + b"0" * 400, "audio/webm;codecs=opus")},
                    headers=H())
    assert r.status_code == 422 and r.json()["code"] == "VOICE_UNCLEAR" and "type your message" in r.json()["message"]
    u = client.post(f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": "audio/webm", "purpose": "voice"}, headers=H()).json()
    client.put(u["url"], content=b"x" * 400, headers={"Content-Type": "audio/webm"})
    ev = sse(client, cid, {"audioPath": u["path"]})
    assert any(e["type"] == "voice_error" for e in ev) and not any(e["type"] == "user_message" for e in ev)
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    assert not any("could not be transcribed" in (m.get("text") or "") for m in msgs)


def test_voice_disabled_switch(client, monkeypatch):
    monkeypatch.setenv("VOICE_ENABLED", "false")
    from app.config import reset_settings_cache
    reset_settings_cache()
    assert client.get("/api/health").json()["voiceEnabled"] is False
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H()).json()["caseId"]
    r = client.post(f"/api/cases/{cid}/voice", files={"file": ("v.mp3", b"x" * 500, "audio/mpeg")}, headers=H())
    assert r.status_code == 404
    monkeypatch.delenv("VOICE_ENABLED")
    reset_settings_cache()
