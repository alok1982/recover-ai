"""End-to-end storylines (PRD §4) through the API in offline mock mode."""
import subprocess

from conftest import BANK, H
from helpers import cards, confirmed_send, paste, sse, text_of, upload


def test_india_storyline(client, tmp_path):
    r = client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=H())
    assert r.status_code == 200
    cid = r.json()["caseId"]
    assert "RecoverAI" in r.json()["greeting"]["text"]

    # 1. victim describes the incident -> upload card
    ev = sse(client, cid, {"text": "मैंने CBI वाले को 1,95,000 भेज दिए"})
    assert "upload" in cards(ev)
    assert ev[-1]["type"] == "done"

    # 2. upload screenshot + scammer WhatsApp text -> facts card
    upload(client, cid, "in_upi_success.png", "image/png")
    w = paste(client, cid, "in_whatsapp_scam.txt")
    assert w["messages"] == []  # scam message is not a recovery scam
    ev = sse(client, cid, {"trigger": "evidence_added", "evidenceIds": [w["evidence"]["id"]]})
    assert cards(ev) == ["facts"]
    facts = next(e for e in ev if e.get("type") == "card")["card"]["data"]
    by = {f["key"]: f for f in facts["fields"]}
    assert by["reference_id"]["value"] == "612345678901"
    assert by["amount"]["display"] == "₹1,95,000"
    assert by["beneficiary.account_or_vpa"]["value"] == "cbi.verify.desk@okdemo"
    assert facts["lowConfidence"] == ["beneficiary.bank"]
    assert facts["scamType"] == "digital_arrest"

    # edit the low-confidence field, confirm
    r = client.patch(f"/api/cases/{cid}/extraction", json={"fields": {"beneficiary.bank": "Sample Co-operative Bank"}, "confirm": True}, headers=H())
    assert r.status_code == 200
    assert "beneficiary.bank" in r.json()["case"]["extraction"]["edited_fields"]

    # 3. plan card + streamed explanation
    ev = sse(client, cid, {"trigger": "facts_confirmed"})
    assert cards(ev) == ["plan"]
    plan = next(e for e in ev if e.get("type") == "card")["card"]["data"]
    assert [s["id"] for s in plan["steps"]] == ["call_1930", "file_ncrp", "report_bank"]
    clocks = {c["id"]: c for c in plan["clocks"]}
    assert clocks["dual_report_5d"]["status"] == "recommended"
    assert "1 Jan 2027" in clocks["dual_report_5d"]["note"]
    assert "ombudsman_30d" not in clocks
    assert "1930" in text_of(ev)

    # 4. generate all -> drafts + consent
    ev = sse(client, cid, {"trigger": "generate_all"})
    assert cards(ev) == ["drafts", "consent"]
    drafts = next(e for e in ev if e.get("type") == "card")["card"]["data"]["drafts"]
    assert {d["templateId"] for d in drafts} == {"hotline_script", "ncrp_complaint", "bank_dispute_letter"}
    for d in drafts:
        for txt in (d["en"], d["local"]):
            assert "612345678901" in txt and "1,95,000" in txt and "cbi.verify.desk@okdemo" in txt

    # evidence pack PDF
    ref = client.get(f"/api/cases/{cid}", headers=H()).json()["case"]["publicRef"]
    r = client.post(f"/api/cases/{cid}/evidence-pack", headers=H())
    pdf = client.get(r.json()["url"]).content
    assert pdf[:4] == b"%PDF"
    p = tmp_path / "pack.pdf"
    p.write_bytes(pdf)
    info = subprocess.run(["pdfinfo", str(p)], capture_output=True, text=True).stdout
    pages = int(next(line.split()[-1] for line in info.splitlines() if line.startswith("Pages")))
    assert pages <= 5
    for i in range(1, pages + 1):
        txt = subprocess.run(["pdftotext", "-f", str(i), "-l", str(i), str(p), "-"], capture_output=True, text=True).stdout
        assert ref in txt  # CR-01 / F8.5: the readable reference, never the internal id
        assert "SANDBOX" in txt
    alltxt = subprocess.run(["pdftotext", str(p), "-"], capture_output=True, text=True).stdout
    assert "612345678901" in alltxt
    assert "अरेस्ट" in alltxt  # Devanagari embedded as text, not boxes (visual shaping checked in docs/screenshots)

    # 5. consent -> bank case
    r = confirmed_send(client, cid)  # CR-01: preview + confirmation (sandbox)
    case = r.json()["case"]
    assert case["bankStatus"] == "SENT" and case["consentVersion"] == "v1"
    steps = {s["id"]: s for s in case["plan"]["steps"]}
    assert steps["report_bank"]["status"] == "done" and steps["report_bank"]["user_reference"] == f"{ref} (sandbox)"
    assert any(c["id"] == "ombudsman_30d" for c in case["clocks"])

    # bank dashboard
    assert client.get("/api/bank/cases", headers=H()).status_code == 403
    lst = client.get("/api/bank/cases", headers=BANK).json()["cases"]
    assert lst[0]["caseId"] == cid
    bc = client.get(f"/api/bank/cases/{lst[0]['id']}", headers=BANK).json()["case"]
    assert bc["riskLevel"] == "HIGH" and bc["recommendedAction"] == "TEMPORARY_HOLD"
    assert bc["holdLimitDisplay"] == "₹1,95,000" and len(bc["signals"]) >= 3
    r = client.post(f"/api/bank/cases/{bc['id']}/decision", json={"decision": "APPROVE_HOLD"}, headers=BANK)
    assert r.json()["case"]["status"] == "HOLD_APPROVED"
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    assert any("अस्थायी रोक" in (m.get("text") or "") for m in msgs)
    assert client.get(f"/api/cases/{cid}", headers=H()).json()["case"]["bankStatus"] == "HOLD_APPROVED"
    audit = client.get(f"/api/bank/cases/{bc['id']}", headers=BANK).json()["audit"]
    assert [a["action"] for a in audit] == ["CASE_RECEIVED", "APPROVE_HOLD"]

    # 6. recovery-scam guard on chat
    ev = sse(client, cid, {"text": "Pay ₹5,000 fee and we recover your money"})
    kinds = cards(ev)
    assert kinds[0] == "warning"
    first_token = next(i for i, e in enumerate(ev) if e.get("type") == "token")
    first_warning = next(i for i, e in enumerate(ev) if e.get("type") == "card")
    assert first_warning < first_token

    # 7. honest answer to "will I definitely get my money back?"
    ev = sse(client, cid, {"text": "Will I definitely get my money back?"})
    reply = text_of(ev)
    assert "वादा नहीं" in reply and "25,000" in reply

    # 8. day 31 escalation, exactly once
    r = client.post(f"/api/cases/{cid}/clock", json={"jumpToDay": 31}, headers=H())
    kinds = [m["card"]["kind"] for m in r.json()["messages"] if m.get("card")]
    assert kinds == ["escalation"]
    esc = r.json()["messages"][0]["card"]["data"]
    assert ref in esc["draft"]["en"] and case["bankCaseId"] not in esc["draft"]["en"] and esc["bankComplaintDate"]
    assert r.json()["case"]["status"] == "escalated"
    r = client.post(f"/api/cases/{cid}/clock", json={"addDays": 1}, headers=H())
    assert r.json()["messages"] == []
    client.get(f"/api/cases/{cid}", headers=H())
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    assert sum(1 for m in msgs if (m.get("card") or {}).get("kind") == "escalation") == 1


def test_malaysia_storyline(client):
    cid = client.post("/api/cases", json={"country": "MY", "language": "ms"}, headers=H("aiman")).json()["caseId"]
    upload(client, cid, "my_bank_transfer.png", "image/png", uid="aiman")
    paste(client, cid, "my_sms.txt", uid="aiman")
    ev = sse(client, cid, {"trigger": "evidence_added"}, uid="aiman")
    assert cards(ev) == ["facts"]
    client.patch(f"/api/cases/{cid}/extraction", json={"confirm": True}, headers=H("aiman"))
    ev = sse(client, cid, {"trigger": "facts_confirmed"}, uid="aiman")
    plan = next(e for e in ev if e.get("type") == "card")["card"]["data"]
    assert [s["id"] for s in plan["steps"]] == ["call_997", "call_bank", "keep_reference"]
    assert plan["steps"][0]["contact"] == "997"
    assert any(c["id"] == "report_hours" for c in plan["clocks"])
    ev = sse(client, cid, {"trigger": "generate_all"}, uid="aiman")
    drafts = next(e for e in ev if e.get("type") == "card")["card"]["data"]["drafts"]
    assert any(d["stepId"] == "police_statement" for d in drafts)
    assert all("DN202610170042" in d["en"] for d in drafts if d["templateId"] != "note")
    r = confirmed_send(client, cid, uid="aiman")
    bc = client.get(f"/api/bank/cases/{r.json()['case']['bankCaseId']}", headers=BANK).json()["case"]
    assert bc["holdLimitDisplay"] == "RM 4,800" and bc["riskLevel"] == "HIGH"


def test_ownership_and_limits(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H("a")).json()["caseId"]
    assert client.get(f"/api/cases/{cid}", headers=H("b")).status_code == 404
    assert client.get(f"/api/cases/{cid}").status_code == 401
    for _ in range(2):
        assert client.post("/api/cases", json={"country": "IN"}, headers=H("a")).status_code == 200
    assert client.post("/api/cases", json={"country": "IN"}, headers=H("a")).status_code == 429
    assert client.delete(f"/api/cases/{cid}", headers=H("a")).json()["deleted"]
    assert client.post("/api/cases", json={"country": "IN"}, headers=H("a")).status_code == 200


def test_country_and_language_switch_recomputes_plan(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H()).json()["caseId"]
    upload(client, cid, "in_upi_success.png", "image/png")
    sse(client, cid, {"trigger": "evidence_added"})
    client.patch(f"/api/cases/{cid}/extraction", json={"confirm": True}, headers=H())
    sse(client, cid, {"trigger": "facts_confirmed"})
    r = client.patch(f"/api/cases/{cid}", json={"country": "MY", "language": "ms"}, headers=H()).json()
    assert [s["id"] for s in r["case"]["plan"]["steps"]] == ["call_997", "call_bank", "keep_reference"]
    assert r["case"]["explanation"]["lang"] == "ms"
    assert "pelan" in r["case"]["explanation"]["text"].lower()


def test_voice_turn_shows_transcript(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=H()).json()["caseId"]
    data = (__import__("conftest").FIX / "in_voice_note.mp3").read_bytes()
    u = client.post(f"/api/cases/{cid}/evidence/upload-url", json={"mimeType": "audio/mpeg", "purpose": "voice"}, headers=H()).json()
    client.put(u["url"], content=data, headers={"Content-Type": "audio/mpeg"})
    ev = sse(client, cid, {"audioPath": u["path"]})
    tr = next(e for e in ev if e["type"] == "transcript")
    assert "सीबीआई" in tr["text"]
    um = next(e for e in ev if e["type"] == "user_message")["message"]
    assert um["audioPath"] == u["path"]


def test_time_travel_disabled_without_demo_mode(client, monkeypatch):
    from app import actions
    from app.config import Settings

    cid = client.post("/api/cases", json={"country": "IN"}, headers=H()).json()["caseId"]
    monkeypatch.setattr(actions, "get_settings", lambda: Settings(demo_mode=False, mock_mode=True))
    assert client.post(f"/api/cases/{cid}/clock", json={"addDays": 1}, headers=H()).status_code == 403


def test_every_assistant_chat_turn_has_text(client):
    """Every co-pilot turn writes a non-empty reply alongside any card (mock co-pilot; e2e_demo checks it live)."""
    from helpers import ready_india_case
    cid = ready_india_case(client)
    for q in ["What should I do now?", "What is the Ombudsman?", "send it to my bank", "Will I get my money back?", "ok"]:
        ev = sse(client, cid, {"text": q})
        assert text_of(ev).strip(), q
        assert (ev[-1].get("message") or {}).get("text"), q
