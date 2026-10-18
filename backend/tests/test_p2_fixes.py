"""Regression tests for the QA P2 fixes (BUG-06, BUG-09 API CSP, BUG-11), docs/qa/test-results-2026-10-18.md."""
import asyncio

import pytest
from conftest import H

from app import actions
from app import profile as P
from app.routers import cases as cases_router
from app.services import close_turn_scope, open_turn_scope
from app.store import get_store


# BUG-06 / A9 / A10: per-country mobile rules after normalising +91 / 0 / spaces / dashes
@pytest.mark.parametrize("raw,cc,want", [
    ("9000001107", "IN", "+919000001107"), ("+91 90000 01107", "IN", "+919000001107"),
    ("09000001107", "IN", "+919000001107"), ("+91-90000-01107", "IN", "+919000001107"),
    ("919000001107", "IN", "+919000001107"), ("9123456789", "IN", "+919123456789"),
    ("+91 98993 19892", "IN", "+919899319892"), ("+91 90000 00001", "IN", "+919000000001"),
    ("90000 00002", "IN", "+919000000002"), ("6000000000", "IN", "+916000000000"),
    ("+60 10000 0001", "MY", "+60100000001"), ("012-345 6789", "MY", "+60123456789"),
    ("011-1234 5678", "MY", "+601112345678"), ("60123456789", "MY", "+60123456789"),
    ("+60 12 345 6789", "IN", "+60123456789"),  # an explicit +60 picks Malaysia's rules
])
def test_valid_mobiles(raw, cc, want):
    assert P.normalize_phone(raw, cc) == want


@pytest.mark.parametrize("raw,cc", [
    ("10000 0001", "IN"), ("+91 100000001", "IN"), ("5000000000", "IN"), ("900000110", "IN"), ("90000011077", "IN"),
    ("90000", "IN"), ("abcdefghij", "IN"), ("+44 7700 900000", "IN"), ("+1 202 555 0100", "MY"),
    ("+60 3 1234 5678", "MY"), ("12345678", "MY"), ("1234567890123", "MY"), ("9000001107", "MY"), ("+91 12345 67890", "MY"),
])
def test_invalid_mobiles(raw, cc):
    assert P.normalize_phone(raw, cc) is None


def test_server_rejects_a_new_account_with_an_invalid_number(client):
    bad = {"Authorization": "Bearer mock:phone:+91100000001"}
    r = client.get("/api/me", headers=bad)
    assert r.status_code == 400 and r.json()["detail"]["code"] == "INVALID_PHONE"
    assert client.get("/api/me", headers={"Authorization": "Bearer mock:phone:+60100000001"}).status_code == 200
    assert client.get("/api/me", headers={"Authorization": "Bearer mock:phone:+919899319892"}).status_code == 200


# BUG-09: JSON / SSE API responses carry a deny-all CSP; nosniff + no-store stay
def test_api_json_has_csp(client):
    r = client.get("/api/health")
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "private, no-store"


# BUG-11 / C14: one card per kind+key per turn
def test_turn_scope_stores_a_repeat_card_once(client):
    cid = client.post("/api/cases", json={"country": "IN", "language": "en"}, headers=H()).json()["caseId"]
    before = len(get_store().list_messages(cid, limit=500))
    tok = open_turn_scope()
    try:
        a = actions.add_card(cid, "warning", {"message": "x", "reason": "a"}, "en")
        b = actions.add_card(cid, "warning", {"message": "x", "reason": "b"}, "en")
        c = actions.add_card(cid, "consent", {"x": 1}, "en")
    finally:
        close_turn_scope(tok)
    assert a["id"] == b["id"] and c["id"] != a["id"]
    assert len(get_store().list_messages(cid, limit=500)) == before + 2
    # outside a turn nothing is deduplicated (e.g. the next turn may show a warning again)
    d = actions.add_card(cid, "warning", {"message": "x"}, "en")
    assert d["id"] != a["id"]


def test_chat_stream_drops_repeated_cards(monkeypatch):
    async def fake(case_id, req):
        yield {"type": "card", "message": {"id": "m1"}, "card": {"kind": "consent", "data": {}}}
        yield {"type": "card", "message": {"id": "m1"}, "card": {"kind": "consent", "data": {}}}
        yield {"type": "card", "message": {"id": "m2"}, "card": {"kind": "consent", "data": {}}}
        yield {"type": "card", "message": {"id": "m3"}, "card": {"kind": "escalation", "data": {"clockId": "a"}}}
        yield {"type": "card", "message": {"id": "m4"}, "card": {"kind": "escalation", "data": {"clockId": "b"}}}
        yield {"type": "token", "text": "hi"}
        yield {"type": "done"}
    monkeypatch.setattr(cases_router, "_chat_events", fake)

    async def go():
        return [e async for e in cases_router.chat_events("c", cases_router.ChatReq(text="x"))]
    evs = asyncio.run(go())
    assert [e["message"]["id"] for e in evs if e["type"] == "card"] == ["m1", "m3", "m4"]
    assert [e["type"] for e in evs][-2:] == ["token", "done"]
