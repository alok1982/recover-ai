"""CR-01 (PRD v2.4 F8): sandbox, preview + confirmation token, 10 s undo (client), withdraw consent, publicRef."""
import re
import time

import pytest

from conftest import BANK, H
from helpers import cards, confirmed_send, ready_india_case, sse, text_of, upload

from app import handoff
from app.agents import copilot, router
from app.config import reset_settings_cache
from app.events import pubsub

REF = re.compile(r"^RAI-IN-\d{8}-\d{4}$")


@pytest.fixture
def live_allowed(monkeypatch):
    monkeypatch.setenv("ALLOW_LIVE_SUBMISSION", "true")
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


def _case(client, cid, uid="victim1"):
    return client.get(f"/api/cases/{cid}", headers=H(uid)).json()["case"]


def _preview(client, cid, uid="victim1"):
    r = client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=H(uid))
    assert r.status_code == 200, r.text
    return r.json()


def _send(client, cid, token, confirmed=True, uid="victim1"):
    return client.post(f"/api/cases/{cid}/send-to-bank", json={"confirmationToken": token, "confirmed": confirmed}, headers=H(uid))


# ---------------------------------------------------------------- F8.1 sandbox
def test_live_submission_off_forces_sandbox_everywhere(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en", "sandbox": False}, headers=H()).json()["caseId"]
    c = _case(client, cid)
    assert c["sandbox"] is True and REF.match(c["publicRef"])
    assert client.patch(f"/api/cases/{cid}/sandbox", json={"sandbox": False}, headers=H()).status_code == 403
    h = client.get("/api/health").json()
    assert h["allowLiveSubmission"] is False and h["sandboxDefault"] is True


def test_demo_evidence_forces_and_locks_sandbox_once(client, live_allowed):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en", "sandbox": False}, headers=H()).json()["caseId"]
    assert _case(client, cid)["sandbox"] is False
    r1 = upload(client, cid, "in_upi_success.png", "image/png")
    assert any("demo evidence" in (m.get("text") or "") for m in r1["messages"])
    c = _case(client, cid)
    assert c["sandbox"] is True and c["sandboxLocked"] is True
    r2 = client.post(f"/api/cases/{cid}/evidence", json={"type": "text", "textContent": open(
        "../fixtures/in_whatsapp_scam.txt").read()}, headers=H()).json()
    assert not any("demo evidence" in (m.get("text") or "") for m in r2["messages"])  # said once
    assert client.patch(f"/api/cases/{cid}/sandbox", json={"sandbox": False}, headers=H()).status_code == 409


def test_sandbox_toggle_when_live_allowed(client, live_allowed):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H()).json()["caseId"]
    assert _case(client, cid)["sandbox"] is True  # SANDBOX_DEFAULT=true
    r = client.patch(f"/api/cases/{cid}/sandbox", json={"sandbox": False}, headers=H())
    assert r.status_code == 200 and r.json()["case"]["sandbox"] is False


# ---------------------------------------------------------------- F8.2 preview + confirmation
def test_preview_publishes_nothing_and_send_needs_token_and_checkbox(client):
    cid = ready_india_case(client)
    bus = pubsub.get_bus()
    n = len(bus.delivered)
    pv = _preview(client, cid)
    s = pv["summary"]
    assert s["destination"] == "SANDBOX" and REF.match(s["publicRef"]) and s["beneficiary"]["account"].endswith("@okdemo")
    assert "cbi.verify.desk" not in s["beneficiary"]["account"] and len(s["evidence"]) == 2
    assert len(bus.delivered) == n  # preview (and an undo, which is just not calling send) publishes nothing
    assert _send(client, cid, pv["confirmationToken"], confirmed=False).status_code == 400
    assert _send(client, cid, None).status_code == 409
    assert _send(client, cid, pv["confirmationToken"][:-2] + "00").status_code == 409  # tampered
    assert len(bus.delivered) == n and _case(client, cid)["bankStatus"] == "NONE"
    assert client.get("/api/bank/cases", headers=BANK).json()["cases"] == []


def test_editing_a_fact_after_preview_returns_409(client):
    cid = ready_india_case(client)
    pv = _preview(client, cid)
    client.patch(f"/api/cases/{cid}/extraction", json={"fields": {"amount": "200000"}}, headers=H())
    r = _send(client, cid, pv["confirmationToken"])
    assert r.status_code == 409 and r.json()["detail"] == "Details changed — please review again"
    assert _send(client, cid, _preview(client, cid)["confirmationToken"]).status_code == 200  # fresh review works


def test_expired_token_returns_409(client, monkeypatch):
    cid = ready_india_case(client)
    tok = _preview(client, cid)["confirmationToken"]
    real = time.time
    monkeypatch.setattr(handoff.time, "time", lambda: real() + 301)
    r = _send(client, cid, tok)
    assert r.status_code == 409 and "expired" in r.json()["detail"]


def test_confirmed_send_goes_to_sandbox_with_env_attribute(client):
    cid = ready_india_case(client)
    case = confirmed_send(client, cid).json()["case"]
    ref = case["publicRef"]
    assert case["submission"]["status"] == "SENT" and case["submission"]["destination"] == "SANDBOX" and case["sandboxLocked"]
    attrs = pubsub.get_bus().delivered[-1]["message"]["attributes"]
    assert attrs["env"] == "sandbox" and attrs["intent"] == "fraud_case.submit"
    lst = client.get("/api/bank/cases", headers=BANK).json()["cases"]
    assert [r["sandbox"] for r in lst] == [True] and lst[0]["publicRef"] == ref
    assert [r for r in lst if not r["sandbox"]] == []  # the live queue stays empty
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    assert any("sandbox (test)" in (m.get("text") or "") and ref in m["text"] for m in msgs)
    drafts = case["drafts"]
    assert all(d["en"].startswith(handoff.SANDBOX_WATERMARK) for d in drafts.values())
    # one active submission per case
    assert client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=H()).status_code == 409
    assert client.patch(f"/api/cases/{cid}/sandbox", json={"sandbox": True}, headers=H()).status_code == 409


def test_send_it_in_chat_only_shows_the_consent_card(client):
    cid = ready_india_case(client)
    n = len(pubsub.get_bus().delivered)
    ev = sse(client, cid, {"text": "send it to my bank"})
    assert "consent" in cards(ev)
    assert len(pubsub.get_bus().delivered) == n and _case(client, cid)["bankStatus"] == "NONE"
    assert "request_bank_consent" in [t.__name__ for t in copilot.Toolbox(cid).adk_tools()]
    assert not any("send" in t.__name__ for t in copilot.Toolbox(cid).adk_tools())  # no send tool exists
    assert "You cannot send anything to a bank" in copilot.SYSTEM_PROMPT
    assert "never say withdrawal is impossible" in copilot.SYSTEM_PROMPT


def test_live_send_rejected_when_not_allowed(client, live_allowed):
    cid = ready_india_case(client)
    client.patch(f"/api/cases/{cid}/sandbox", json={"sandbox": False}, headers=H())  # demo evidence → 409 (locked)
    assert _case(client, cid)["sandbox"] is True
    live_allowed.setenv("ALLOW_LIVE_SUBMISSION", "false")
    reset_settings_cache()
    case = handoff.actions.load(cid)
    case["sandbox"] = False
    assert handoff.destination(case) == "SANDBOX"  # forced: a live destination cannot exist


# ---------------------------------------------------------------- F8.4 withdraw + F8.5 publicRef
def test_withdraw_from_chat_and_endpoint(client):
    cid = ready_india_case(client)
    case = confirmed_send(client, cid).json()["case"]
    ref, bcid = case["publicRef"], case["bankCaseId"]
    assert router.decide(case, "Reverse the consent which has sent to bank", guard_route="light", flagged=False).route == "full"
    ev = sse(client, cid, {"text": "Reverse the consent which has sent to bank"})
    assert "withdraw" in cards(ev)
    assert "impossible" not in text_of(ev).lower() and "cannot be withdrawn" not in text_of(ev).lower()
    assert client.post(f"/api/cases/{cid}/withdraw-consent", json={}, headers=H()).status_code == 400
    t0 = time.time()
    r = client.post(f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True}, headers=H())
    assert r.status_code == 200
    assert r.json()["case"]["bankStatus"] == "WITHDRAWN" and r.json()["case"]["consentWithdrawnAt"]
    assert ref in r.json()["messages"][0]["text"]
    d = client.get(f"/api/bank/cases/{bcid}", headers=BANK).json()
    assert d["case"]["status"] == "WITHDRAWN_BY_CUSTOMER" and time.time() - t0 < 3
    assert d["case"]["evidence"] == [] and d["case"]["scammer_contacts"] == [] and d["case"]["dataHidden"]
    assert d["case"]["amountDisplay"] == "₹1,95,000"  # metadata kept
    assert [a["action"] for a in d["audit"]] == ["CASE_RECEIVED", "CONSENT_WITHDRAWN"]
    assert pubsub.get_bus().delivered[-1]["message"]["attributes"]["intent"] == "fraud_case.withdraw"
    assert client.post(f"/api/bank/cases/{bcid}/decision", json={"decision": "APPROVE_HOLD"}, headers=BANK).status_code == 409
    assert client.post(f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True}, headers=H()).status_code == 409
    # share again later: fresh consent + confirmation → a new bank case
    again = confirmed_send(client, cid).json()["case"]
    assert again["bankCaseId"] != bcid and again["submission"]["status"] == "SENT"


def test_no_internal_ids_in_victim_messages(client):
    cid = ready_india_case(client)
    case = confirmed_send(client, cid).json()["case"]
    client.post(f"/api/bank/cases/{case['bankCaseId']}/decision", json={"decision": "APPROVE_HOLD"}, headers=BANK)
    sse(client, cid, {"text": "Reverse the consent which has sent to bank"})
    client.post(f"/api/cases/{cid}/withdraw-consent", json={"confirmed": True}, headers=H())
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    shown = " ".join((m.get("text") or "") for m in msgs if m["role"] != "system_event")
    assert case["bankCaseId"] not in shown and not re.search(r"\bb_[0-9a-f]{8,}", shown)
    steps = {s["id"]: s for s in _case(client, cid)["plan"]["steps"]}
    assert steps["report_bank"]["user_reference"] == f"{case['publicRef']} (sandbox)"


def test_public_refs_are_unique():
    from app.store import get_store

    refs = {handoff.new_public_ref("IN", f"c{i}") for i in range(200)}
    assert len(refs) == 200 and all(REF.match(r) for r in refs)
    assert get_store().claim_public_ref(next(iter(refs)), "other") is False
