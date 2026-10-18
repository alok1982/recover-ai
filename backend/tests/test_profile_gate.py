"""CR-03 C: profile gate (412 + co-pilot hotline → profile card), prefill, drafts use the profile."""
from app import gate
from conftest import H
from helpers import ready_india_case, sse

U2, U1 = "phone:+919000000002", "phone:+919000000001"
P2, P1 = H(U2), H(U1)


def cards(events):
    return [e["card"] for e in events if e.get("type") == "card"]
FULL = {"fullName": "Asha Verma", "country": "IN", "language": "hi", "state": "Uttar Pradesh", "district": "Lucknow",
        "postalCode": "226001", "primaryBank": "HDFC Bank"}
PARTIAL = {k: v for k, v in FULL.items() if k not in ("postalCode", "primaryBank")} | {"fullName": "Ravi Kumar"}
HINDI = "मेरे साथ अभी 1,95,000 का फ्रॉड हुआ"


def _user(client, h, prof):
    client.post("/api/me/terms", json={"version": "2026-10-cr03"}, headers=h)
    assert client.put("/api/me/profile", json={"profile": prof}, headers=h).status_code == 200
    return client.post("/api/cases", json={"country": "IN", "language": "hi"}, headers=h).json()["caseId"]


def test_incomplete_profile_hotline_then_profile_card_then_evidence(client):
    cid = _user(client, P2, PARTIAL)
    ev = sse(client, cid, {"text": HINDI}, uid=U2)
    kinds = [c["kind"] for c in cards(ev)]
    assert kinds[:2] == ["hotline", "profile"], kinds
    assert "upload" not in kinds
    prof = next(c for c in cards(ev) if c["kind"] == "profile")["data"]
    assert prof["missing"] == ["postalCode", "primaryBank"]
    assert set(prof["prefill"]) <= {"postalCode", "primaryBank", "primaryBankOther"}
    hot = next(c for c in cards(ev) if c["kind"] == "hotline")["data"]
    assert hot["number"] == "1930" and "cybercrime.gov.in" in hot["web"]
    for path in ("drafts", "send-to-bank/preview", "extract", "plan", "evidence-pack"):
        r = client.post(f"/api/cases/{cid}/{path}", headers=P2)
        assert r.status_code == 412, path
        assert r.json()["detail"] == {"code": "PROFILE_INCOMPLETE", "missing": ["postalCode", "primaryBank"],
                                      "message": "Please complete your profile first."}
    r = client.post(f"/api/cases/{cid}/send-to-bank", json={"consent": True, "consentVersion": "x"}, headers=P2)
    assert r.status_code == 412
    # a second turn: still gated, the hotline card is not repeated
    ev = sse(client, cid, {"text": "ठीक है"}, uid=U2)
    assert [c["kind"] for c in cards(ev)] == ["profile"]
    # the victim saves the card → the co-pilot moves on to evidence
    assert client.put("/api/me/profile", json={"profile": {"postalCode": "226010", "primaryBank": "State Bank of India"}},
                      headers=P2).json()["profileStatus"]["complete"]
    ev = sse(client, cid, {"trigger": "profile_saved"}, uid=U2)
    assert "upload" in [c["kind"] for c in cards(ev)]
    assert client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=P2).status_code != 412


def test_complete_profile_goes_straight_to_evidence(client):
    cid = _user(client, P1, FULL)
    ev = sse(client, cid, {"text": HINDI}, uid=U1)
    kinds = [c["kind"] for c in cards(ev)]
    assert "upload" in kinds and "profile" not in kinds and "hotline" not in kinds


def test_directed_triggers_wait_for_profile(client):
    cid = _user(client, P2, PARTIAL)
    ev = sse(client, cid, {"trigger": "generate_all"}, uid=U2)
    assert "profile" in [c["kind"] for c in cards(ev)] and "drafts" not in [c["kind"] for c in cards(ev)]


def test_prefill_from_chat():
    pre = gate.prefill_from_text(["My name is Ravi Kumar, I live in Lucknow and bank with SBI"], "IN")
    assert pre["fullName"] == "Ravi Kumar" and pre["district"] == "Lucknow"
    assert gate.prefill_from_text(["मेरा खाता HDFC Bank में है"], "IN")["primaryBank"] == "HDFC Bank"
    assert gate.prefill_from_text(["akaun Maybank saya"], "MY")["primaryBank"] == "Maybank"


def test_drafts_use_profile_and_go_stale_on_change(client):
    _user(client, P1, FULL)
    cid = ready_india_case(client, uid=U1)
    case = client.get(f"/api/cases/{cid}", headers=P1).json()["case"]
    letter = next(d for d in case["drafts"].values() if d["templateId"] == "bank_dispute_letter")
    assert "Asha Verma" in letter["en"] and "Lucknow" in letter["en"] and "226001" in letter["en"]
    assert "9000000001" not in letter["en"]
    consent = client.post(f"/api/cases/{cid}/send-to-bank/preview", headers=P1).json()
    assert consent["summary"]["customerName"] == "Asha Verma"
    client.put("/api/me/profile", json={"profile": {"district": "Kanpur"}}, headers=P1)
    case = client.get(f"/api/cases/{cid}", headers=P1).json()["case"]
    assert case["draftsStale"] == "profile_changed"
    client.post(f"/api/cases/{cid}/drafts", headers=P1)
    case = client.get(f"/api/cases/{cid}", headers=P1).json()["case"]
    assert case["draftsStale"] is None
    letter = next(d for d in case["drafts"].values() if d["templateId"] == "bank_dispute_letter")
    assert "Kanpur" in letter["en"]


def test_profile_not_in_analytics(client):
    from app.analytics import bq
    cid = _user(client, P1, FULL)
    sse(client, cid, {"text": HINDI}, uid=U1)
    blob = str(bq.get_analytics().data.get("case_events"))
    assert "Asha" not in blob and "226001" not in blob
