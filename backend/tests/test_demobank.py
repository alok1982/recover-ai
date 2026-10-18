"""DEMO_MODE: the bank side is always the fictional RecoverAI Demo Bank; real bank names stay on the victim's side."""
import re

from conftest import BANK, H
from helpers import confirmed_send, ready_india_case, sse

from app import demobank
from app.events import pubsub
from app.store import get_store

DEMO = "RecoverAI Demo Bank (fictional)"
REAL = re.compile(r"HDFC|ICICI|State Bank|SBI\b|Maybank|CIMB|Axis|Kotak|Public Bank|RHB", re.I)


def test_consent_card_and_preview_name_the_demo_bank_as_receiver(client):
    cid = ready_india_case(client)  # victim profile bank: HDFC Bank (their own bank)
    pv = client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=H()).json()["summary"]
    assert pv["bankName"] == DEMO and pv["receivingBank"] == {"bankId": "demo-recoverai-bank", "name": DEMO}
    ev = sse(client, cid, {"text": "send it to the bank"})
    consent = [e["card"]["data"] for e in ev if e.get("type") == "card" and e["card"]["kind"] == "consent"]
    assert consent and consent[0]["bankName"] == DEMO and consent[0]["receivingBank"]["bankId"] == "demo-recoverai-bank"


def test_handoff_bank_case_audit_and_decision_use_the_demo_bank(client):
    cid = ready_india_case(client)
    confirmed_send(client, cid)
    sub = [d for d in pubsub.get_bus().delivered if (d["message"].get("attributes") or {}).get("intent") == "fraud_case.submit"][-1]
    import base64, json
    env = json.loads(base64.b64decode(sub["message"]["data"])) if isinstance(sub["message"].get("data"), str) else sub["message"]["data"]
    assert env["to_agent"] == "bank.demo-recoverai-bank.fraud_case_receiver.in"
    assert env["payload"]["receivingBank"]["name"] == DEMO
    lst = client.get("/api/bank/cases", headers=BANK).json()["cases"]
    assert lst[0]["receivingBankId"] == "demo-recoverai-bank" and lst[0]["receivingBankName"] == DEMO
    bid = lst[0]["id"]
    d = client.get(f"/api/bank/cases/{bid}", headers=BANK).json()
    assert d["case"]["receivingBankName"] == DEMO
    assert all(a.get("receivingBankId") == "demo-recoverai-bank" for a in d["audit"])
    client.post(f"/api/bank/cases/{bid}/decision", json={"decision": "APPROVE_HOLD"}, headers=BANK)
    dec = [x for x in pubsub.get_bus().delivered if "bank-decision" in json.dumps(x.get("message", {}).get("attributes") or {})
           or "fraud_case.decision" in json.dumps(x)][-1]
    dec_env = json.loads(base64.b64decode(dec["message"]["data"]))
    assert dec_env["from_agent"] == "bank.demo-recoverai-bank.fraud_case_receiver.in" and dec_env["receivingBankName"] == DEMO
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    bank_msgs = [m.get("text") or "" for m in msgs if "Demo Bank" in (m.get("text") or "")]
    assert bank_msgs, "victim messages name the demo bank"
    assert not any(REAL.search(t) for t in bank_msgs)


def test_evidence_pack_names_the_demo_bank_desk():
    from app.pdf.evidence_pack import _desk_line
    line = _desk_line({"country": "MY"})
    assert DEMO in line and "no real bank" in line


def test_bank_desk_fallback_for_legacy_cases(client):
    get_store().put_bank_case("b_legacy", {"caseId": "c_x", "country": "IN", "receivedAt": None, "status": "NEW", "sandbox": True})
    lst = client.get("/api/bank/cases", headers=BANK).json()["cases"]
    assert next(r for r in lst if r["id"] == "b_legacy")["receivingBankName"] == DEMO


def test_outside_demo_mode_the_victims_bank_is_used(client, monkeypatch):
    cid = ready_india_case(client)
    monkeypatch.setattr(demobank, "active", lambda: False)
    pv = client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=H()).json()["summary"]
    assert pv["receivingBank"] is None and pv["bankName"] != DEMO
