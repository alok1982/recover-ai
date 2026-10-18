"""Case actions shared by REST card buttons, directed chat triggers and the co-pilot's tools.

Every action persists its result in Firestore (source of truth) and appends messages/cards to the
conversation. Streaming actions are async generators of SSE event dicts.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import timedelta
from typing import AsyncIterator

from fastapi import HTTPException

from .agents import bank_receiver, filing, guard, intake, playbook
from . import demobank
from .agents import post_check
from .analytics import bq
from .analytics.synthetic import beneficiary_hash
from .bank.rules import HOLD_NOTE
from .config import get_settings
from .events import pubsub
from .i18n import t
from .rules.engine import compute_plan, evaluate_clocks, explain_rule, get_playbook, mark_step
from .rules.formatting import format_amount, format_dt, parse_local_datetime
from .services import append_message, card, jsonable, system_event, update_case
from .storage import get_blobs
from .store import get_store
from .timeutil import effective_now, ensure_utc, parse_iso, to_iso, utcnow

log = logging.getLogger("recoverai.actions")

CONSENT_VERSION = "v1"
CONSENT_TEXT = {
    "en": "Share this case and evidence with my bank's fraud team for fraud investigation and fund recovery. I can withdraw this consent at any time.",
    "hi": "धोखाधड़ी की जाँच और पैसे की वसूली के लिए यह केस और सबूत मेरे बैंक की फ्रॉड टीम से साझा करें। मैं यह सहमति कभी भी वापस ले सकता/सकती हूँ।",
    "ms": "Kongsi kes dan bukti ini dengan pasukan penipuan bank saya untuk siasatan penipuan dan pemulihan dana. Saya boleh menarik balik persetujuan ini pada bila-bila masa.",
}
COMING_SOON = [
    {"code": "SG", "name": "Singapore", "text": "Police report + bank; Shared Responsibility Framework payouts for covered phishing scams (since 16 Dec 2024)."},
    {"code": "ID", "name": "Indonesia", "text": "Report to Indonesia Anti-Scam Centre (iasc.ojk.go.id) or your bank; accounts can be blocked and funds returned."},
    {"code": "PH", "name": "Philippines", "text": "Bank dispute triggers a temporary hold of disputed funds for up to 30 days under AFASA."},
    {"code": "AU", "name": "Australia", "text": "Your bank + ReportCyber/Scamwatch; Scams Prevention Framework duties."},
    {"code": "JP", "name": "Japan", "text": "Police and your bank; frozen account balances can be distributed to victims."},
    {"code": "KR", "name": "Korea", "text": "Bank or FSS 1332 for payment suspension; refund without a lawsuit under the Refund Act."},
]


def load(case_id: str) -> dict:
    c = get_store().get_case(case_id)
    if not c:
        raise HTTPException(404, "case not found")
    return c


def pb_for(case: dict) -> dict:
    return get_playbook(case["country"])


def msg_event(msg: dict) -> dict:
    return {"type": "card" if msg.get("card") else "message", "message": jsonable(msg), "card": msg.get("card")}


# ------------------------------------------------------------------ card data (all values computed in code)
def facts_card_data(case: dict) -> dict:
    ex = case.get("extraction") or {}
    pb = pb_for(case)
    conf = ex.get("confidence") or {}
    edited = set(ex.get("edited_fields") or [])
    fields = []
    for f in ["amount", "currency", "reference_id", "occurred_at", "payment_method", "payer_bank", "beneficiary.name",
              "beneficiary.account_or_vpa", "beneficiary.bank", "beneficiary.ifsc_or_code", "scammer_contacts", "urls", "scam_type"]:
        v = intake.get_field(ex, f)
        c = 1.0 if f in edited else conf.get(f)
        display = v
        if f == "amount":
            display = format_amount(v, ex.get("currency"))
        elif f == "occurred_at" and v:
            display = format_dt(case.get("incidentAt"), pb["timezone"])
        elif isinstance(v, list):
            display = ", ".join(v)
        fields.append({"key": f, "value": v, "display": display, "confidence": c,
                       "level": "green" if f in edited else intake.confidence_level(c if v not in (None, "", []) else None),
                       "source": "user" if f in edited else "model", "missing": v in (None, "", [])})
    low = [x["key"] for x in fields if x["level"] == "red" and not x["missing"]]
    return {"fields": fields, "lowConfidence": low, "missing": ex.get("missing_fields") or [],
            "narrative": ex.get("narrative_local") or ex.get("narrative_en"), "confirmed": case.get("status") not in ("draft", "extracted"),
            "scamType": ex.get("scam_type")}


def plan_card_data(case: dict) -> dict:
    plan = case.get("plan") or {}
    return {"steps": plan.get("steps", []), "clocks": case.get("clocks") or [], "playbookVersion": plan.get("playbook_version"),
            "lastVerified": plan.get("last_verified"), "sources": plan.get("sources", []), "country": case["country"],
            "explanation": (case.get("explanation") or {}).get("text")}


def drafts_card_data(case: dict) -> dict:
    return {"drafts": list((case.get("drafts") or {}).values()), "evidencePackAvailable": bool(case.get("evidencePackPath")),
            "stale": case.get("draftsStale")}


def consent_card_data(case: dict) -> dict:
    from . import handoff

    lang = case.get("language", "en")
    ex = case.get("extraction") or {}
    b = ex.get("beneficiary") or {}
    return {"version": CONSENT_VERSION, "text": CONSENT_TEXT.get(lang, CONSENT_TEXT["en"]),
            "purpose": "Fraud investigation and fund recovery", "withdrawable": True,
            "items": ["Confirmed transaction facts (amount, reference, date, receiver)", "Evidence files with SHA-256 hashes",
                      "Scammer contacts and links", "Your incident summary"],
            "amount": format_amount(ex.get("amount"), ex.get("currency")), "given": bool(case.get("consentGivenAt")),
            # CR-01 / F8.2: the destination and who receives it; the button only opens the confirmation sheet
            "destination": handoff.destination(case), "liveAllowed": handoff.live_allowed(),
            "bankName": _receiving_bank_name(case), "receivingBank": demobank.receiving_bank(case.get("country")),
            "beneficiaryMasked": handoff._mask(b.get("account_or_vpa")), "customerName": _profile_name(case)}


def _receiving_bank_name(case: dict) -> str | None:
    """Who receives the shared case. DEMO_MODE: always the fictional demo bank, never the victim's real bank."""
    if demobank.active():
        return demobank.name(case.get("country"))
    ex = case.get("extraction") or {}
    return ex.get("payer_bank") or _profile_bank(case)


def _profile_name(case: dict) -> str | None:
    from . import gate
    return gate.owner_profile(case).get("fullName") or None


def _profile_bank(case: dict) -> str | None:
    from . import gate, profile as P
    return P.bank_name(gate.owner_profile(case))


def timeline_card_data(case: dict) -> dict:
    return {"clocks": case.get("clocks") or [], "steps": (case.get("plan") or {}).get("steps", []),
            "bankStatus": case.get("bankStatus"), "effectiveNow": effective_now(case), "clockOffsetDays": case.get("clockOffsetDays", 0),
            "publicRef": case.get("publicRef")}


def upload_card_data(lang: str, prompt: str | None = None) -> dict:
    return {"prompt": prompt, "accept": {"image": ["image/png", "image/jpeg", "image/webp"],
                                         "audio": ["audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/webm"]},
            "limits": {"images": 5, "imageMB": 10, "audioMinutes": 2}}


def add_card(case_id: str, kind: str, data: dict, lang: str, text: str | None = None, msg_id: str | None = None) -> dict:
    return append_message(case_id, role="assistant", text=text, card=card(kind, data), lang=lang, msg_id=msg_id)


# ------------------------------------------------------------------ deadlines (lazy evaluation)
async def evaluate(case_id: str, now=None) -> list[dict]:
    """Evaluate clocks with the demo-shifted clock; post each newly overdue clock's message exactly once."""
    case = load(case_id)
    if not case.get("plan"):
        return []
    pb = pb_for(case)
    eff = effective_now(case, now)
    clocks, newly = evaluate_clocks(case, pb, eff)
    update_case(case_id, {"clocks": clocks})
    msgs = []
    lang = case.get("language", "en")
    for c in newly:
        if c.get("escalationTemplate"):
            case = load(case_id)
            draft = await filing.escalation_draft(case, pb, c)
            from .handoff import watermark_draft
            draft = watermark_draft(case, draft) if isinstance(draft, dict) else draft
            at = filing.bank_complaint_at(case)  # QA BUG-01: report_bank done time, else the bank-handoff time
            refs = filing.escalation_refs(case, pb)
            data = {"clockId": c["id"], "label": c.get("labelLocal") or c["label"], "title": c.get("escalationTitleLocal") or c.get("escalationTitle"), "contact": c.get("contact"),
                    "dueDisplay": c["dueDisplay"], "draft": draft,
                    "bankComplaintDate": format_dt(at, pb["timezone"]) if at else None,
                    "bankReference": refs["bank_reference"], "publicRef": case.get("publicRef")}
            update_case(case_id, {"status": "escalated", "escalation": data})
            msgs.append(add_card(case_id, "escalation", data, lang, text=t("escalation", lang)))
        elif c.get("urgencyOnly"):
            msgs.append(append_message(case_id, role="assistant", lang=lang,
                                       text=t("reminder_urgent", lang, label=c.get("labelLocal") or c["label"])))
        else:
            msgs.append(append_message(case_id, role="assistant", lang=lang,
                                       text=t("deadline_passed", lang, label=c.get("labelLocal") or c["label"])))
        log.info("clock_overdue_notified", extra={"caseId": case_id, "step": "deadline", "clockId": c["id"]})
    return msgs


# ------------------------------------------------------------------ extraction
def victim_texts(case_id: str) -> list[str]:
    return [m["text"] for m in get_store().list_messages(case_id, limit=30) if m["role"] == "user" and m.get("text")]


async def extract(case_id: str) -> AsyncIterator[dict]:
    case = load(case_id)
    evidence = get_store().list_evidence(case_id)
    lang = case.get("language", "en")
    if not evidence:
        m = add_card(case_id, "upload", upload_card_data(lang), lang, text=t("ask_evidence", lang))
        yield msg_event(m)
        return
    yield {"type": "tool_status", "name": "extract_facts", "state": "running", "label": t("reading", lang)}
    t0 = time.perf_counter()
    ex, source = await intake.extract(case, evidence, victim_texts(case_id))
    latency = int((time.perf_counter() - t0) * 1000)
    pb = pb_for(case)
    exd = ex.model_dump()
    exd["edited_fields"] = []
    exd["source"] = source
    incident = parse_local_datetime(exd.get("occurred_at"), pb["timezone"]) or case.get("createdAt")
    update_case(case_id, {"extraction": exd, "incidentAt": incident, "status": "extracted"})
    case = load(case_id)
    log.info("extraction_done", extra={"caseId": case_id, "step": "extract", "latencyMs": latency, "source": source})
    yield {"type": "tool_status", "name": "extract_facts", "state": "done", "latencyMs": latency}
    m = append_message(case_id, role="assistant", text=t("facts_ready", lang), card=card("facts", facts_card_data(case)),
                       lang=lang, tool_calls=[{"name": "extract_facts", "ok": True, "latencyMs": latency}])
    yield msg_event(m)


def patch_extraction(case_id: str, fields: dict, confirm: bool) -> dict:
    case = load(case_id)
    ex = case.get("extraction")
    if not ex:
        raise HTTPException(409, "nothing extracted yet")
    pb = pb_for(case)
    edited = set(ex.get("edited_fields") or [])
    patch: dict = {}
    for key, value in fields.items():
        if key not in {"reference_id", "amount", "currency", "occurred_at", "payment_method", "payer_bank", "beneficiary.name",
                       "beneficiary.account_or_vpa", "beneficiary.bank", "beneficiary.ifsc_or_code", "scammer_contacts", "urls", "scam_type"}:
            raise HTTPException(400, f"unknown field {key}")
        if key == "amount" and value not in (None, ""):
            try:
                value = float(str(post_check.normalize_digits(str(value))).replace(",", "").replace("₹", "").replace("RM", "").strip())
            except ValueError as e:
                raise HTTPException(400, "amount must be a number") from e
        if key in ("scammer_contacts", "urls") and isinstance(value, str):
            value = [v.strip() for v in value.split(",") if v.strip()]
        intake.set_field(ex, key, value)
        edited.add(key)
        if key in (ex.get("missing_fields") or []) and value not in (None, "", []):
            ex["missing_fields"] = [m for m in ex["missing_fields"] if m != key]
    ex["edited_fields"] = sorted(edited)
    patch["extraction"] = ex
    if "occurred_at" in fields:
        patch["incidentAt"] = parse_local_datetime(ex.get("occurred_at"), pb["timezone"]) or case.get("incidentAt")
    if confirm and case.get("status") in ("draft", "extracted"):
        patch["status"] = "confirmed"
        patch["confirmedAt"] = utcnow()
    update_case(case_id, patch)
    case = load(case_id)
    if case.get("plan"):  # facts changed after planning: deadlines are recomputed in code
        recompute_plan(case_id)
    if fields:
        system_event(case_id, f"User edited fields: {', '.join(sorted(fields))}", case.get("language", "en"))
    if confirm:
        system_event(case_id, "User confirmed facts", case.get("language", "en"))
        if patch.get("status") == "confirmed":
            record_confirmed_event(load(case_id))
    return load(case_id)


def record_confirmed_event(case: dict) -> None:
    """F14: anonymised row in BigQuery case_events (no names/phones; beneficiary only as SHA-256)."""
    ex = case.get("extraction") or {}
    bq.record_case_event({
        "event_id": f"{case['id']}-confirmed", "case_id": case["id"], "event_type": "case_confirmed", "country": case["country"],
        "scam_type": ex.get("scam_type"), "amount": ex.get("amount"), "currency": ex.get("currency"),
        "beneficiary_hash": beneficiary_hash((ex.get("beneficiary") or {}).get("account_or_vpa")),
        "risk_level": None, "decision": None, "sandbox": case.get("sandbox", True) or not get_settings().allow_live_submission,
        "event_time": case.get("confirmedAt") or utcnow()})


# ------------------------------------------------------------------ plan
def recompute_plan(case_id: str) -> dict:
    case = load(case_id)
    pb = pb_for(case)
    if case.get("plan") and case["plan"].get("country") != case["country"]:
        case["plan"] = None  # country switched: different steps
        case["clocks"] = []
    plan = compute_plan(case, pb)
    case["plan"] = plan
    clocks, _ = evaluate_clocks(case, pb, effective_now(case))
    update_case(case_id, {"plan": plan, "clocks": clocks})
    return load(case_id)


async def plan_stream(case_id: str) -> AsyncIterator[dict]:
    case = load(case_id)
    lang = case.get("language", "en")
    if not case.get("extraction"):
        async for ev in extract(case_id):
            yield ev
        return
    if case.get("status") == "extracted":
        update_case(case_id, {"status": "confirmed", "confirmedAt": utcnow()})
    yield {"type": "tool_status", "name": "build_plan", "state": "running"}
    case = recompute_plan(case_id)
    pb = pb_for(case)
    m = append_message(case_id, role="assistant", text=None, card=card("plan", plan_card_data(case)), lang=lang,
                       tool_calls=[{"name": "build_plan", "ok": True, "latencyMs": 0}])
    yield msg_event(m)
    allowed = allowed_values(case)
    gate = post_check.StreamGate(allowed)
    async for chunk in playbook.stream_explanation(case, case["plan"], case.get("clocks") or []):
        for piece in gate.feed(chunk):
            yield {"type": "token", "text": piece}
    for piece in gate.flush():
        yield {"type": "token", "text": piece}
    text = gate.text
    if gate.dropped:
        log.warning("post_check_dropped", extra={"caseId": case_id, "step": "plan_explain",
                                                 "values": [f.raw for f in gate.dropped]})
    update_case(case_id, {"explanation": {"lang": lang, "text": text}})
    final = append_message(case_id, role="assistant", text=text, lang=lang, meta={"kind": "plan_explanation"})
    yield {"type": "done", "messageId": final["id"], "message": jsonable(final)}


def allowed_values(case: dict, *extra) -> post_check.Allowed:
    pb = pb_for(case)
    state = {k: case.get(k) for k in ("extraction", "plan", "clocks", "incidentAt", "createdAt", "bankStatus", "drafts",
                                       "escalation", "consentGivenAt", "bankCaseId", "publicRef")}
    return post_check.build_allowed(state, pb, *extra, tz_names=[pb["timezone"]])


# ------------------------------------------------------------------ drafts + PDF
async def drafts_stream(case_id: str) -> AsyncIterator[dict]:
    case = load(case_id)
    lang = case.get("language", "en")
    if not case.get("plan"):
        async for ev in plan_stream(case_id):
            yield ev
        case = load(case_id)
    yield {"type": "tool_status", "name": "generate_drafts", "state": "running"}
    t0 = time.perf_counter()
    drafts = await filing.generate_all(case, pb_for(case), case["plan"])
    from .handoff import watermark_draft  # CR-01: sandbox drafts carry "SANDBOX — NOT SUBMITTED"
    drafts = {k: watermark_draft(case, d) for k, d in drafts.items()}
    latency = int((time.perf_counter() - t0) * 1000)
    update_case(case_id, {"drafts": drafts, "draftsStale": None, "status": "filed" if case.get("status") in ("confirmed", "extracted") else case.get("status")})
    try:
        await build_evidence_pack(case_id)
    except Exception:  # noqa: BLE001 - drafts are still useful without the PDF
        log.exception("evidence pack failed", extra={"caseId": case_id})
    case = load(case_id)
    log.info("drafts_done", extra={"caseId": case_id, "step": "drafts", "latencyMs": latency})
    yield {"type": "tool_status", "name": "generate_drafts", "state": "done", "latencyMs": latency}
    yield msg_event(append_message(case_id, role="assistant", text=t("drafts_ready", lang), card=card("drafts", drafts_card_data(case)),
                                   lang=lang, tool_calls=[{"name": "generate_drafts", "ok": True, "latencyMs": latency}]))
    if case.get("bankStatus") in (None, "NONE"):
        yield msg_event(add_card(case_id, "consent", consent_card_data(case), lang, text=t("consent_ask", lang)))


async def build_evidence_pack(case_id: str) -> str:
    from .pdf.evidence_pack import render_pdf

    case = load(case_id)
    evidence = get_store().list_evidence(case_id)
    blobs = get_blobs()
    images = {}
    for e in evidence:
        if e["type"] == "image":
            try:
                images[e["id"]] = blobs.read_bytes(e["gcsPath"])
            except Exception:  # noqa: BLE001
                log.warning("thumbnail missing", extra={"caseId": case_id, "evidenceId": e["id"]})
    t0 = time.perf_counter()
    pdf = render_pdf(case, pb_for(case), evidence, images)
    path = f"cases/{case_id}/evidence-pack.pdf"
    blobs.write_bytes(path, pdf, "application/pdf")
    update_case(case_id, {"evidencePackPath": path, "evidencePackAt": utcnow()})
    log.info("evidence_pack_built", extra={"caseId": case_id, "step": "pdf", "latencyMs": int((time.perf_counter() - t0) * 1000), "bytes": len(pdf)})
    return path


def evidence_pack_url(case_id: str) -> str:
    case = load(case_id)
    if not case.get("evidencePackPath"):
        raise HTTPException(409, "evidence pack not built")
    return get_blobs().read_url(case["evidencePackPath"], f"RecoverAI-evidence-{case_id}.pdf")


# ------------------------------------------------------------------ steps + time travel
def set_step(case_id: str, step_id: str, status: str, reference: str | None) -> dict:
    case = load(case_id)
    if not case.get("plan"):
        raise HTTPException(409, "no plan yet")
    try:
        plan = mark_step(case["plan"], step_id, status, reference, effective_now(case))
    except KeyError as e:
        raise HTTPException(404, "unknown step") from e
    update_case(case_id, {"plan": plan})
    case = load(case_id)
    clocks, _ = evaluate_clocks(case, pb_for(case), effective_now(case))
    update_case(case_id, {"clocks": clocks})
    system_event(case_id, f"User marked step {step_id} as {status}" + (f" (reference {reference})" if reference else ""),
                 case.get("language", "en"))
    return load(case_id)


async def time_travel(case_id: str, add_days: float | None, jump_to_day: int | None, reset: bool) -> tuple[dict, list[dict]]:
    if not get_settings().demo_mode:
        raise HTTPException(403, "time travel is only available in DEMO_MODE")
    case = load(case_id)
    offset = float(case.get("clockOffsetDays") or 0)
    if reset:
        offset = 0.0
    if add_days:
        offset += float(add_days)
    if jump_to_day is not None:
        steps = {s["id"]: s for s in (case.get("plan") or {}).get("steps", [])}
        anchor = (steps.get("report_bank") or {}).get("doneAt") or case.get("incidentAt") or case.get("createdAt")
        target = ensure_utc(anchor) + timedelta(days=jump_to_day, minutes=1)
        offset = max(offset, (target - utcnow()).total_seconds() / 86400)
    update_case(case_id, {"clockOffsetDays": round(offset, 4)})
    system_event(case_id, f"Demo clock moved: offset {offset:.2f} days", case.get("language", "en"))
    msgs = await evaluate(case_id)
    return load(case_id), msgs


# ------------------------------------------------------------------ guard
async def guard_text(case_id: str, text: str, lang: str) -> list[dict]:
    return (await guard_turn(case_id, text, lang))[0]


async def guard_turn(case_id: str, text: str, lang: str) -> tuple[list[dict], dict]:
    """Guard one text; returns (warning messages, raw guard result incl. the F17 "route" label)."""
    res = await guard.check(text, case_id)
    if not res["is_recovery_scam"]:
        return [], res
    update_case(case_id, {"flags": {"recovery_scam_detected": True}})
    log.info("recovery_scam_flagged", extra={"caseId": case_id, "step": "guard", "source": res["source"]})
    return [add_card(case_id, "warning", {"message": t("warning", lang), "followUp": t("warning_followup", lang),
                                          "reason": res["reason"], "source": res["source"]}, lang)], res


# ------------------------------------------------------------------ bank handoff
async def send_to_bank(case_id: str, consent: bool, version: str, token: str | None = None,
                       confirmed: bool = False) -> tuple[dict, list[dict]]:
    """Consent card answer. "Not now" records the decline; a send needs the confirmation sheet (CR-01 / F8.2):
    a confirmationToken from /send-to-bank/preview plus confirmed=true — see handoff.send."""
    from . import handoff

    case = load(case_id)
    lang = case.get("language", "en")
    if not consent:
        system_event(case_id, "User declined to share with bank", lang)
        return case, [append_message(case_id, role="assistant", text=t("consent_declined", lang), lang=lang)]
    return await handoff.send(case_id, token, confirmed)


DECISION_STATUS = {"APPROVE_HOLD": "HOLD_APPROVED", "REQUEST_INFO": "INFO_REQUESTED", "REJECT": "REJECTED"}


def desk_agent(country: str) -> str:
    """A2A name of the receiving bank desk (DEMO_MODE: the fictional demo bank's desk)."""
    rb = demobank.receiving_bank(country)
    return f"bank.{rb['bankId']}.fraud_case_receiver.{country.lower()}" if rb else f"bank.fraud_case_receiver.{country.lower()}"


def _desk_fields(bc: dict) -> dict:
    rb = demobank.receiving_bank(bc.get("country"))
    if not rb:
        return {}
    return {"receivingBankId": rb["bankId"], "receivingBankName": rb["name"]}


async def bank_decision(bank_case_id: str, decision: str, note: str | None, analyst: str) -> dict:
    """Bank side: record the decision + audit, publish `bank-decision` (F9/F15), log an anonymised case_event (F14)."""
    store = get_store()
    bc = store.get_bank_case(bank_case_id)
    if not bc:
        raise HTTPException(404, "bank case not found")
    if bc.get("status") == "WITHDRAWN_BY_CUSTOMER":
        raise HTTPException(409, "The customer withdrew consent for this case")
    status = DECISION_STATUS[decision]
    decided_at = utcnow()
    store.update_bank_case(bank_case_id, {"status": status, "decidedAt": decided_at, "decidedBy": analyst, "decisionNote": note})
    from .bank.connectors import connector_for  # CR-01: sandbox cases never reach a real bank system

    connector_for(bc).record(bank_case_id, decision, {"holdLimitAmount": bc.get("holdLimitAmount"), "note": note})
    store.add_audit({"actor": analyst, "action": decision, "bankCaseId": bank_case_id, "caseId": bc["caseId"],
                     **_desk_fields(bc),
                     "details": {"note": note, "holdLimitAmount": bc.get("holdLimitAmount") if decision == "APPROVE_HOLD" else None}})
    event_id = pubsub.stable_key("bank-decision", bank_case_id, decision, to_iso(decided_at))
    event = {"eventId": event_id, "bankCaseId": bank_case_id, "caseId": bc["caseId"], "decision": decision, "status": status,
             "note": note, "decidedAt": to_iso(decided_at), "from_agent": desk_agent(bc["country"]), **_desk_fields(bc),
             "to_agent": "recoverai.victim_copilot", "intent": "fraud_case.decision"}
    settings = get_settings()
    try:
        mid = await pubsub.publish(settings.topic_bank_decision, event, {"eventTopic": settings.topic_bank_decision, "caseId": bc["caseId"]})
        store.update_bank_case(bank_case_id, {"decisionEvent": {"eventId": event_id, "messageId": mid}})
    except Exception as e:  # noqa: BLE001
        log.exception("publish bank-decision failed", extra={"bankCaseId": bank_case_id})
        raise HTTPException(503, "decision saved but could not notify the victim; retry") from e
    log.info("bank_decision", extra={"bankCaseId": bank_case_id, "caseId": bc["caseId"], "step": "decision", "decision": decision})
    # F14 analytics row after the publish, so BigQuery never sits on the decision → victim path.
    await asyncio.to_thread(bq.record_case_event, {
        "event_id": f"{bc['caseId']}-decision-{event_id[:8]}", "case_id": bc["caseId"], "event_type": "bank_decision",
        "country": bc.get("country"), "scam_type": bc.get("scam_type"), "amount": bc.get("amount"), "currency": bc.get("currency"),
        "beneficiary_hash": bc.get("beneficiaryHash"), "risk_level": bc.get("riskLevel"), "decision": decision,
        "sandbox": bool(bc.get("sandbox")), "event_time": decided_at})
    return store.get_bank_case(bank_case_id)


async def apply_bank_decision(event: dict) -> dict:
    """Victim side (push from `bank-decision`): update the case and post the co-pilot message, idempotently."""
    store = get_store()
    case = store.get_case(event["caseId"])
    if not case:
        log.warning("bank decision for unknown case", extra={"caseId": event["caseId"]})
        return {"applied": False, "reason": "case not found"}
    if case.get("bankStatus") == "WITHDRAWN" and event.get("bankCaseId") == case.get("bankCaseId"):
        log.info("decision after withdrawal ignored", extra={"caseId": case["id"], "bankCaseId": event.get("bankCaseId")})
        return {"applied": False, "reason": "consent withdrawn"}
    decision, note = event["decision"], event.get("note")
    status = DECISION_STATUS[decision]
    lang = case.get("language", "en")
    mid = f"m_dec_{event['eventId'][:20]}"
    update_case(case["id"], {"bankStatus": status, "bankDecisionAt": parse_iso(event.get("decidedAt")) or utcnow()})
    system_event(case["id"], f"Bank decision: {decision}" + (f" — {note}" if note else ""), lang, msg_id=mid + "_sys")
    case = load(case["id"])
    if decision == "APPROVE_HOLD":
        m = add_card(case["id"], "timeline", timeline_card_data(case), lang, text=t("bank_hold", lang), msg_id=mid)
    elif decision == "REQUEST_INFO":
        q = note or "Please share any other screenshot or message about this payment."
        m = add_card(case["id"], "upload", upload_card_data(lang, q), lang, text=t("bank_info", lang, question=q), msg_id=mid)
    else:
        m = add_card(case["id"], "timeline", timeline_card_data(case), lang, text=t("bank_reject", lang), msg_id=mid)
    return {"applied": True, "messageId": m["id"], "status": status}


# ------------------------------------------------------------------ evidence
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def explain(case: dict, topic: str) -> dict:
    return explain_rule(pb_for(case), topic)


__all__ = ["HOLD_NOTE", "COMING_SOON"]
