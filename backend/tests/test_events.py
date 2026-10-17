"""F15 Pub/Sub backbone: push auth, decode, idempotent redelivery; F14 fallbacks and case_events."""
import pytest

from conftest import BANK, PUSH, H
from helpers import ready_india_case

from app.analytics import bq
from app.analytics.synthetic import beneficiary_hash
from app.config import reset_settings_cache
from app.events import pubsub


def _send(client, cid):
    r = client.post(f"/api/cases/{cid}/send-to-bank", json={"consent": True}, headers=H())
    assert r.status_code == 200, r.text
    return r.json()["case"]


def test_consent_publishes_to_fraud_case_topic_and_push_creates_bank_case(client):
    cid = ready_india_case(client)
    case = _send(client, cid)
    bus = pubsub.get_bus()
    body = bus.delivered[-1]
    assert body["message"]["attributes"]["topic"] == "fraud-case-submitted"
    data, meta = pubsub.decode_push(body)
    assert data["intent"] == "fraud_case.submit" and data["payload"]["caseId"] == cid and meta["messageId"]
    bc = client.get(f"/api/bank/cases/{case['bankCaseId']}", headers=BANK).json()["case"]
    assert bc["txnStatus"] == "ok" and bc["txnFeatures"]["credits_24h"] == 9 and bc["riskLevel"] == "HIGH"
    assert bc["beneficiaryHash"] == beneficiary_hash("cbi.verify.desk@okdemo")


def test_redelivery_and_duplicate_publish_do_not_duplicate_bank_case(client):
    cid = ready_india_case(client)
    case = _send(client, cid)
    bus = pubsub.get_bus()
    body = bus.delivered[-1]
    # 1) Pub/Sub redelivers the same message over HTTP
    r = client.post("/bank/a2a/inbox", json=body, headers=PUSH)
    assert r.status_code == 200 and r.json()["duplicate"] is True
    # 2) a publisher retry produces a new messageId for the same envelope
    data, _ = pubsub.decode_push(body)
    r = client.post("/api/bank/a2a/inbox", json=pubsub.push_body("fraud-case-submitted", data, "other-id"), headers=PUSH)
    assert r.status_code == 200 and r.json()["bankCaseId"] == case["bankCaseId"]
    cases = [b for b in client.get("/api/bank/cases", headers=BANK).json()["cases"] if b["caseId"] == cid]
    assert len(cases) == 1
    audit = client.get(f"/api/bank/cases/{case['bankCaseId']}", headers=BANK).json()["audit"]
    assert [a["action"] for a in audit] == ["CASE_RECEIVED"]


def test_bank_decision_event_round_trip_is_idempotent(client):
    cid = ready_india_case(client)
    case = _send(client, cid)
    client.post(f"/api/bank/cases/{case['bankCaseId']}/decision", json={"decision": "APPROVE_HOLD"}, headers=BANK)
    bus = pubsub.get_bus()
    body = bus.delivered[-1]
    assert body["message"]["attributes"]["topic"] == "bank-decision"
    for _ in range(2):  # redelivered twice
        r = client.post("/api/events/bank-decision", json=body, headers=PUSH)
        assert r.status_code == 200
    msgs = client.get(f"/api/cases/{cid}/messages", headers=H()).json()["messages"]
    decision_msgs = [m for m in msgs if m["id"].startswith("m_dec_")]
    assert len(decision_msgs) == 2  # one system event + one co-pilot message, despite two redeliveries
    assert sum(m["role"] == "assistant" and "अस्थायी रोक" in (m.get("text") or "") for m in decision_msgs) == 1
    assert client.get(f"/api/cases/{cid}", headers=H()).json()["case"]["bankStatus"] == "HOLD_APPROVED"


@pytest.mark.parametrize("path", ["/bank/a2a/inbox", "/api/bank/a2a/inbox", "/api/events/bank-decision"])
def test_push_endpoints_require_push_token(client, path):
    body = pubsub.push_body("x", {"a": 1}, "m1")
    assert client.post(path, json=body).status_code == 401
    assert client.post(path, json=body, headers=H()).status_code == 401  # a victim token is not a push token
    assert client.post(path, json={"message": {"data": "%%%"}}, headers=PUSH).status_code == 400
    assert client.post(path, json=body, headers=PUSH).status_code == 400  # decodes, but not a valid event


def test_oidc_verification_in_production_mode(monkeypatch):
    from fastapi import HTTPException
    from google.oauth2 import id_token

    monkeypatch.setenv("AUTH_MODE", "firebase")
    monkeypatch.setenv("PUSH_AUDIENCE", "https://recoverai-api-123.asia-south1.run.app")
    monkeypatch.setenv("PUSH_SA_EMAIL", "pubsub-push@recoverai-511917.iam.gserviceaccount.com")
    reset_settings_cache()
    seen = {}

    def fake_verify(token, request, audience):
        seen["aud"] = audience
        if token == "bad":
            raise ValueError("signature")
        return {"email": token, "email_verified": True}

    monkeypatch.setattr(id_token, "verify_oauth2_token", fake_verify)
    try:
        ok = pubsub.verify_push_auth("Bearer pubsub-push@recoverai-511917.iam.gserviceaccount.com")
        assert ok["email"].startswith("pubsub-push@") and seen["aud"] == "https://recoverai-api-123.asia-south1.run.app"
        with pytest.raises(HTTPException) as e:
            pubsub.verify_push_auth("Bearer someone-else@evil.iam.gserviceaccount.com")
        assert e.value.status_code == 403
        with pytest.raises(HTTPException) as e:
            pubsub.verify_push_auth("Bearer bad")
        assert e.value.status_code == 401
        with pytest.raises(HTTPException) as e:
            pubsub.verify_push_auth("Bearer mock-push")  # the offline token is useless in production
        assert e.value.status_code == 403
        monkeypatch.setenv("PUSH_AUDIENCE", "")
        reset_settings_cache()
        with pytest.raises(HTTPException) as e:
            pubsub.verify_push_auth("Bearer x")
        assert e.value.status_code == 503
    finally:
        reset_settings_cache()


class _Broken:
    name = "bigquery"

    def features(self, *a):
        raise RuntimeError("BigQuery is down")

    def insert_case_event(self, *a):
        raise RuntimeError("BigQuery is down")

    def ml_score(self, *a):
        raise RuntimeError("BigQuery is down")

    def scam_intelligence(self, *a):
        raise RuntimeError("BigQuery is down")


def test_bigquery_failure_still_creates_bank_case_with_case_signals(client):
    cid = ready_india_case(client)
    bq.set_analytics(_Broken())
    case = _send(client, cid)
    bc = client.get(f"/api/bank/cases/{case['bankCaseId']}", headers=BANK).json()["case"]
    assert bc["txnStatus"] == "unavailable" and bc["txnFeatures"] is None
    assert "unavailable" in bc["txnNote"]
    codes = {s["code"] for s in bc["signals"]}
    assert codes <= {"VICTIM_REPORT", "RECENT_TXN", "FLAGGED_NUMBER"} and "VICTIM_REPORT" in codes
    # analytics outage never blocks the decision either
    r = client.post(f"/api/bank/cases/{case['bankCaseId']}/decision", json={"decision": "REJECT"}, headers=BANK)
    assert r.status_code == 200
    assert client.get("/api/bank/analytics", headers=BANK).status_code == 503


def test_case_events_are_anonymised(client):
    cid = ready_india_case(client)
    case = _send(client, cid)
    client.post(f"/api/bank/cases/{case['bankCaseId']}/decision", json={"decision": "APPROVE_HOLD"}, headers=BANK)
    ev = [e for e in bq.get_analytics().case_events() if e["case_id"] == cid]
    assert [e["event_type"] for e in ev] == ["case_confirmed", "bank_decision"]
    assert ev[1]["decision"] == "APPROVE_HOLD" and ev[1]["risk_level"] == "HIGH"
    blob = repr(ev)
    for raw in ("cbi.verify.desk", "90000", "Priya", "612345678901"):
        assert raw not in blob
    assert ev[0]["beneficiary_hash"] == beneficiary_hash("cbi.verify.desk@okdemo")
    si = client.get("/api/bank/analytics", headers=BANK).json()
    rep = {r["beneficiary_hash"]: r["cases"] for r in si["repeat_beneficiaries"]}
    assert rep[beneficiary_hash("cbi.verify.desk@okdemo")] >= 3  # 2 seeded earlier cases + this one


def test_ml_score_is_advisory_and_flagged(client, monkeypatch):
    monkeypatch.setenv("ENABLE_ML_SCORE", "true")
    reset_settings_cache()
    try:
        cid = ready_india_case(client)
        case = _send(client, cid)
        bc = client.get(f"/api/bank/cases/{case['bankCaseId']}", headers=BANK).json()["case"]
        assert bc["mlRiskScore"] > 0.8 and bc["recommendedAction"] == "TEMPORARY_HOLD"
    finally:
        reset_settings_cache()
