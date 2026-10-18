"""Regression tests for the 18 Oct 2026 QA bugs (docs/qa/test-results-2026-10-18.md)."""
import asyncio
import json

from conftest import H
from helpers import ready_india_case

from app import handoff
from app.store import get_store


def _preview(client, cid):
    r = client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=H())
    assert r.status_code == 200, r.text
    return r.json()


def _bank_cases_for(cid):
    return [b for b in get_store().list_bank_cases(limit=500) if b.get("caseId") == cid]


# BUG-02 / E8: five concurrent confirms with one token → exactly one bank case, the others 409
def test_parallel_confirms_create_exactly_one_bank_case(client):
    cid = ready_india_case(client)
    tok = _preview(client, cid)["confirmationToken"]

    async def go():
        return await asyncio.gather(*(handoff.send(cid, tok, True) for _ in range(5)), return_exceptions=True)

    res = asyncio.run(go())
    ok = [r for r in res if not isinstance(r, BaseException)]
    errs = [r for r in res if isinstance(r, BaseException)]
    assert len(ok) == 1 and all(getattr(e, "status_code", None) == 409 for e in errs), res
    assert len(_bank_cases_for(cid)) == 1
    # replay with the same token → 409, still one bank case
    assert client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True}, headers=H()).status_code == 409
    assert len(_bank_cases_for(cid)) == 1


def test_withdraw_then_resend_is_a_new_submission(client):
    cid = ready_india_case(client)
    tok = _preview(client, cid)["confirmationToken"]
    assert client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True}, headers=H()).status_code == 200
    assert client.post(f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True}, headers=H()).status_code == 200
    tok = _preview(client, cid)["confirmationToken"]
    r = client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True}, headers=H())
    assert r.status_code == 200, r.text
    assert r.json()["case"]["submissionSeq"] == 2 and len(_bank_cases_for(cid)) == 2


def test_failed_publish_releases_the_claim(client, monkeypatch):
    cid = ready_india_case(client)
    tok = _preview(client, cid)["confirmationToken"]
    from app.events import pubsub

    async def boom(*a, **k):
        raise RuntimeError("pubsub down")
    monkeypatch.setattr(pubsub, "publish", boom)
    assert client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True}, headers=H()).status_code == 503
    monkeypatch.undo()
    assert client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True}, headers=H()).status_code == 200


# BUG-01 / D5: escalation card + Ombudsman draft cite the bank complaint date and the RAI- ref
def test_escalation_cites_complaint_date_and_public_ref(client):
    cid = ready_india_case(client)
    client.patch(f"/api/cases/{cid}/steps/report_bank", json={"status": "done", "reference": "BANK-CMP-42"}, headers=H())
    r = client.post(f"/api/cases/{cid}/clock", json={"jumpToDay": 31}, headers=H()).json()
    esc = next(m["card"]["data"] for m in r["messages"] if (m.get("card") or {}).get("kind") == "escalation")
    ref = r["case"]["publicRef"]
    assert esc["bankComplaintDate"] and esc["bankReference"] == "BANK-CMP-42" and esc["publicRef"] == ref
    for text in (esc["draft"]["en"], esc["draft"]["local"]):
        assert ref in text and "BANK-CMP-42" in text and not any(w.startswith("b_") for w in text.split())


def test_escalation_after_bank_share_uses_public_ref_not_internal_id(client):
    cid = ready_india_case(client)
    tok = _preview(client, cid)["confirmationToken"]
    case = client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": tok, "confirmed": True}, headers=H()).json()["case"]
    r = client.post(f"/api/cases/{cid}/clock", json={"jumpToDay": 31}, headers=H()).json()
    esc = next(m["card"]["data"] for m in r["messages"] if (m.get("card") or {}).get("kind") == "escalation")
    blob = json.dumps(esc, ensure_ascii=False)
    assert esc["bankComplaintDate"] and case["publicRef"] in esc["draft"]["en"] and case["bankCaseId"] not in blob


# BUG-03 / I8: no shared caching of any API response, errors included
def test_api_responses_are_private_no_store(client):
    for path, hdr in (("/api/health", {}), ("/api/cases/c_nope", H()), ("/api/cases", {}), ("/api/bank/cases", H())):
        r = client.get(path, headers=hdr)
        assert r.headers["cache-control"] == "private, no-store", (path, r.status_code)
        assert r.headers["x-content-type-options"] == "nosniff"


# BUG-04 / C5: magic bytes decide; empty files rejected; the rejected blob is removed
def _register(client, cid, data, mime="image/png", kind="image"):
    u = client.post(f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": mime, "sizeBytes": len(data)}, headers=H()).json()
    client.put(u["url"], content=data, headers={"Content-Type": mime})
    return client.post(f"/api/cases/{cid}/evidence", json={"type": kind, "gcsPath": u["path"], "mimeType": mime}, headers=H()), u["path"]


def test_disguised_exe_and_empty_files_rejected(client):
    from app.storage import get_blobs
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H()).json()["caseId"]
    r, path = _register(client, cid, b"MZ\x90\x00" + b"\x00" * 600)
    assert r.status_code == 415 and "PNG, JPEG or WebP" in r.json()["detail"] and get_blobs().size(path) is None
    r, _ = _register(client, cid, b"")
    assert r.status_code == 400 and "empty" in r.json()["detail"]
    r, _ = _register(client, cid, b"\x89PNG\r\n\x1a\n" + b"\x00" * 64, mime="image/jpeg")  # real PNG, wrong label → stored as PNG
    assert r.status_code == 200 and r.json()["evidence"]["mimeType"] == "image/png"
    r, _ = _register(client, cid, b"%PDF-1.7 not audio" + b"\x00" * 300, mime="audio/mpeg", kind="audio")
    assert r.status_code == 415
    assert client.get(f"/api/cases/{cid}", headers=H()).json()["case"].get("evidenceCount") == 1


# BUG-07 / G1: speculative co-pilot — a flagged message still shows the warning card first and leaves exactly one reply
def test_speculative_turn_flagged_warning_first_and_single_reply(client):
    from helpers import cards, sse
    cid = ready_india_case(client)
    before = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    ev = sse(client, cid, {"text": "Pay ₹5,000 fee and we recover your money"})
    kinds = cards(ev)
    assert kinds and kinds[0] == "warning"
    first_card = next(i for i, e in enumerate(ev) if e.get("type") == "card")
    first_token = next(i for i, e in enumerate(ev) if e.get("type") == "token")
    assert first_card < first_token
    after = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    new = after[len(before):]
    assert sum(1 for m in new if m["role"] == "assistant" and m.get("text") and not m.get("card")) == 1
    assert sum(1 for m in new if (m.get("card") or {}).get("kind") == "warning") == 1


def test_speculative_turn_clean_message_streams(client):
    from helpers import sse, text_of
    cid = ready_india_case(client)
    ev = sse(client, cid, {"text": "What should I do now?"})
    assert text_of(ev).strip() and ev[-1]["type"] == "done"


# BUG-05: deadline questions in hi / ms always get the Timeline card
def test_deadline_question_always_shows_timeline(client):
    from helpers import cards, sse
    for lang, q in (("hi", "मेरी डेडलाइन कब है?"), ("en", "When is my deadline?")):
        cid = ready_india_case(client)
        ev = sse(client, cid, {"text": q})
        assert "timeline" in cards(ev), (lang, cards(ev))


def test_card_artifact_stripped():
    from app.agents.copilot import _CARD_ARTIFACT
    assert _CARD_ARTIFACT.sub("", "Deadline is 22 Oct.\n[showed timeline card]").strip() == "Deadline is 22 Oct."
    assert _CARD_ARTIFACT.sub("", "Lihat kad di bawah:\n[show_timeline]").strip() == "Lihat kad di bawah:"


# BUG-08: profile card pre-fills bank + PIN typed in the chat; nothing saved until Save
def test_profile_card_prefills_bank_and_pin(client):
    from helpers import sse
    uid = "ph-919000000077"
    client.put("/api/me/profile", json={"profile": {"fullName": "Prefill Test", "country": "IN", "language": "en",
                                                     "state": "Maharashtra", "district": "Pune"}}, headers=H(uid))
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H(uid)).json()["caseId"]
    ev = sse(client, cid, {"text": "I was scammed of Rs 20,000 last week. My bank is SBI, I live in Pune 411001"}, uid=uid)
    pc = next(e["card"]["data"] for e in ev if e.get("type") == "card" and e["card"]["kind"] == "profile")
    assert pc["prefill"].get("primaryBank") == "State Bank of India" and pc["prefill"].get("postalCode") == "411001"
    prof = client.get("/api/me", headers=H(uid)).json()["profile"]
    assert not prof.get("postalCode") and not prof.get("primaryBank")


def test_postal_prefill_ignores_amounts():
    from app.gate import prefill_from_text as f
    assert "postalCode" not in f(["I paid 195000 rupees"], "IN")
    assert "postalCode" not in f(["Sent 195000 via UPI, UTR 612345678901"], "IN")
    assert f(["मेरा पिन 226001 है"], "IN")["postalCode"] == "226001"
    my = f(["Saya di Shah Alam 40000, bank CIMB"], "MY")
    assert my["postalCode"] == "40000" and my["primaryBank"] == "CIMB Bank"
