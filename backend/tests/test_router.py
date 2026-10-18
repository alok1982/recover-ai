"""F17: light/full routing rules and every Gemma → Gemini fallback path (mock mode, Gemma stubbed)."""
import asyncio

import pytest

from conftest import H
from helpers import cards, ready_india_case, sse, text_of

from app import actions
from app.agents import bank_receiver, guard, router
from app.config import reset_settings_cache
from app.models import GuardResult

GEMMA = "gemma-4-26b-a4b-it-maas"


@pytest.fixture
def light_on(monkeypatch):
    monkeypatch.setenv("CHAT_LIGHT_MODEL", GEMMA)
    reset_settings_cache()
    yield monkeypatch
    reset_settings_cache()


def _stub(monkeypatch, chunks=None, delay=0.0, exc=None):
    seen = {}

    async def fake(system, contents):
        seen["system"], seen["contents"] = system, contents
        if delay:
            await asyncio.sleep(delay)
        if exc:
            raise exc
        for c in chunks or []:
            yield c
    monkeypatch.setattr(router, "GEMMA_STREAM", fake)
    return seen


PLANNED = {"id": "c1", "country": "IN", "plan": {"steps": []}}


# ---------------------------------------------------------------- routing rules
def test_light_model_disabled_routes_everything_full(monkeypatch):
    monkeypatch.delenv("CHAT_LIGHT_MODEL", raising=False)
    reset_settings_cache()
    d = router.decide(PLANNED, "अब मुझे क्या करना है?", guard_route="light", flagged=False)
    assert (d.route, d.reason) == ("full", "light_model_disabled")


@pytest.mark.parametrize("kw,reason", [
    ({"has_attachment": True}, "attachment_or_audio"),
    ({"has_audio": True}, "attachment_or_audio"),
    ({"trigger": "card_action"}, "system_event"),
    ({"flagged": True}, "recovery_scam"),
])
def test_code_overrides_force_full(light_on, kw, reason):
    args = {"guard_route": "light", "flagged": False, **kw}
    assert router.decide(PLANNED, "what's next?", **args).reason == reason


def test_no_plan_yet_forces_full(light_on):
    assert router.decide({"id": "c1", "country": "IN"}, "what's next?", guard_route="light", flagged=False).reason == "no_plan_yet"


@pytest.mark.parametrize("text", [
    "draft my complaint", "send to my bank", "I want to share it with the bank", "please escalate", "the amount is wrong",
    "मेरी शिकायत का ड्राफ्ट बनाओ", "मेरे बैंक को भेजो", "राशि गलत है, बदल दो",
    "tolong draf aduan saya", "hantar kepada bank saya", "jumlah itu salah",
])
def test_action_keywords_force_full(light_on, text):
    assert router.decide(PLANNED, text, guard_route="light", flagged=False).reason == "action_keyword"


@pytest.mark.parametrize("text", [
    "it was actually ₹2,50,000", "it happened on 12 Oct", "it happened 14/10/2026", "his number is +91 98765 43210",
    "the UPI was fraud.desk@okaxis", "account 123456789012", "मैंने १,९५,००० भेजे थे क्या",
])
def test_new_amount_date_or_id_forces_full(light_on, text):
    assert router.decide(PLANNED, text, guard_route="light", flagged=False).reason == "new_fact_value"


def test_outcome_question_stays_on_gemini(light_on):
    assert router.decide(PLANNED, "will I get my money back?", guard_route="light", flagged=False).reason == "outcome_question"


def test_guard_label_decides_when_no_override(light_on):
    assert router.decide(PLANNED, "अब मुझे क्या करना है?", guard_route="light", flagged=False).route == "light"
    assert router.decide(PLANNED, "Ombudsman क्या है?", guard_route="light", flagged=False).route == "light"
    assert router.decide(PLANNED, "hmm", guard_route="full", flagged=False).reason == "guard_full"
    assert router.decide(PLANNED, "hmm", guard_route=None, flagged=False).reason == "guard_full"  # unsure → full


def test_guard_schema_and_mock_label():
    assert GuardResult(is_recovery_scam=False, reason="").route == "full"
    assert "route" in guard.SYSTEM and "When unsure, \"full\"" in guard.SYSTEM
    assert asyncio.run(guard.check("अब मुझे क्या करना है?"))["route"] == "light"
    assert asyncio.run(guard.check("draft my complaint"))["route"] == "full"


# ---------------------------------------------------------------- end-to-end (India demo case, Hindi)
def _done(ev):
    assert ev[-1]["type"] == "done"
    assert not any(e.get("type") == "error" for e in ev)
    return ev[-1]["message"]


def test_light_questions_answered_by_gemma_in_hindi(client, light_on):
    seen = _stub(light_on, ["आपका अगला कदम: 1930 पर ", "कॉल करें। समय-सीमा 22 Oct 2026, 14:02 IST है।"])
    cid = ready_india_case(client)
    for q in ["अब मुझे क्या करना है?", "Ombudsman क्या है?"]:
        ev = sse(client, cid, {"text": q})
        m = _done(ev)
        assert m["model"] == GEMMA and m["route"]["route"] == "light" and m["toolCalls"] == []
        assert "1930" in text_of(ev) and not cards(ev)
    assert "Hindi" in seen["system"] and "[[FULL]]" in seen["system"] and "22 Oct 2026, 14:02 IST" in seen["system"]
    assert seen["contents"][-1].parts[0].text.endswith("Ombudsman क्या है?</user_message>")
    assert [c.role for c in seen["contents"]][::2] == ["user"] * len(seen["contents"][::2])  # alternating, user first


def test_heavy_turns_go_to_gemini(client, light_on):
    _stub(light_on, ["should not be used"])
    cid = ready_india_case(client)
    for q in ["draft my complaint", "send to my bank"]:
        m = _done(sse(client, cid, {"text": q}))
        assert m["model"] != GEMMA and m["route"]["route"] == "full"
    ev = sse(client, cid, {"text": "अब मुझे क्या करना है?", "evidenceIds": ["e_any"]})  # with an attachment
    assert _done(ev)["route"]["reason"] == "attachment_or_audio"


@pytest.mark.parametrize("stub,reason", [
    ({"exc": RuntimeError("503 unavailable")}, "error"),
    ({"chunks": ["[[FULL]]"]}, "handed_back"),
    ({"chunks": ["आपने ₹9,99,999 भेजे थे।"]}, "post_check"),  # invented number
    ({"chunks": ["   "]}, "empty"),
    ({"chunks": []}, "empty"),
    ({"chunks": ["late"], "delay": 0.5}, "first_token_timeout"),
])
def test_every_gemma_failure_falls_back_to_gemini(client, light_on, stub, reason):
    light_on.setenv("LIGHT_FIRST_TOKEN_S", "0.2")
    reset_settings_cache()
    _stub(light_on, **stub)
    cid = ready_india_case(client)
    ev = sse(client, cid, {"text": "अब मुझे क्या करना है?"})
    m = _done(ev)
    assert m["model"] == "gemini-fallback" and m["route"]["fallback"] == reason
    assert text_of(ev).strip() and "9,99,999" not in text_of(ev) and "[[FULL]]" not in text_of(ev)


def test_force_light_fail_switch(client, light_on):
    light_on.setenv("FORCE_LIGHT_FAIL", "true")
    reset_settings_cache()
    _stub(light_on, ["अगला कदम: 1930 पर कॉल करें।"])
    cid = ready_india_case(client)
    for q in ["अब मुझे क्या करना है?", "Ombudsman क्या है?"]:
        m = _done(sse(client, cid, {"text": q}))
        assert m["model"] == "gemini-fallback" and m["route"]["fallback"] == "forced"


def test_mock_gemma_answers_from_summary_without_stub(client, light_on):
    cid = ready_india_case(client)
    ev = sse(client, cid, {"text": "Ombudsman क्या है?"})
    assert _done(ev)["model"] == GEMMA and "30 days" in text_of(ev)


def test_light_summary_has_clock_due_dates_terms_and_next_step(client):
    cid = ready_india_case(client)
    s = router.light_summary(actions.load(cid))
    assert s["next_step"]["contact"] == "1930" and s["clocks"][0]["due"].endswith("IST") and s["clocks"][0]["time_left"]
    assert "Ombudsman" in s["terms"]["ombudsman"] and s["facts"]["amount"] == "₹1,95,000"


# ---------------------------------------------------------------- bank reason budget
def test_bank_reason_budget_stays_inside_ack_deadline():
    assert bank_receiver.REASON_TIMEOUT_S == 25
    assert bank_receiver.enrich_budget(0.5) == 25
    assert bank_receiver.enrich_budget(3.0) == pytest.approx(23.0)  # 30 s ack − 4 s margin − 3 s already spent
    assert bank_receiver.enrich_budget(40) == 1.0
