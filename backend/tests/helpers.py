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
