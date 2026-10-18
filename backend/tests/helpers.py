import json

from conftest import FIX, H


def sse(client, case_id, body, uid="victim1"):
    r = client.post(f"/api/cases/{case_id}/chat", json=body, headers=H(uid))
    assert r.status_code == 200, r.text
    events = []
    for line in r.text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def cards(events):
    return [e["card"]["kind"] for e in events if e.get("type") == "card"]


def text_of(events):
    return "".join(e["text"] for e in events if e.get("type") == "token")


def upload(client, case_id, fname, mime, uid="victim1"):
    data = (FIX / fname).read_bytes()
    u = client.post(f"/api/cases/{case_id}/evidence/upload-url", json={"mimeType": mime, "sizeBytes": len(data)}, headers=H(uid)).json()
    r = client.put(u["url"], content=data, headers={"Content-Type": mime})
    assert r.status_code == 200, r.text
    r = client.post(f"/api/cases/{case_id}/evidence", json={"type": "image" if mime.startswith("image") else "audio",
                                                           "gcsPath": u["path"], "mimeType": mime, "fileName": fname}, headers=H(uid))
    assert r.status_code == 200, r.text
    return r.json()


def paste(client, case_id, fname, uid="victim1"):
    r = client.post(f"/api/cases/{case_id}/evidence", json={"type": "text", "textContent": (FIX / fname).read_text()}, headers=H(uid))
    assert r.status_code == 200, r.text
    return r.json()


def ready_india_case(client, uid="victim1"):
    """IN case with evidence, confirmed facts, plan and drafts — ready for the consent step."""
    from conftest import H

    cid = client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=H(uid)).json()["caseId"]
    upload(client, cid, "in_upi_success.png", "image/png", uid=uid)
    paste(client, cid, "in_whatsapp_scam.txt", uid=uid)
    sse(client, cid, {"trigger": "evidence_added"}, uid=uid)
    client.patch(f"/api/cases/{cid}/extraction", json={"confirm": True}, headers=H(uid))
    sse(client, cid, {"trigger": "facts_confirmed"}, uid=uid)
    sse(client, cid, {"trigger": "generate_all"}, uid=uid)
    return cid


def confirmed_send(client, case_id, uid="victim1"):
    """CR-01: preview → confirmationToken → confirmed send (what the confirmation sheet does after the 10 s undo)."""
    pv = client.post(f"/api/cases/{case_id}/send-to-bank/preview", headers=H(uid))
    assert pv.status_code == 200, pv.text
    r = client.post(f"/api/cases/{case_id}/send-to-bank",
                    json={"confirmationToken": pv.json()["confirmationToken"], "confirmed": True}, headers=H(uid))
    assert r.status_code == 200, r.text
    return r
