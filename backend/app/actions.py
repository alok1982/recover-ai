"""Case actions shared by REST card buttons, directed chat triggers and the co-pilot's tools.

Every action persists its result in Firestore (source of truth) and appends messages/cards to the
conversation. Streaming actions are async generators of SSE event dicts.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import timedelta
from typing import AsyncIterator

from fastapi import HTTPException

from .agents import bank_receiver, filing, guard, intake, playbook
from .agents import post_check
from .bank.rules import HOLD_NOTE
from .config import get_settings
from .i18n import t
from .rules.engine import compute_plan, evaluate_clocks, explain_rule, get_playbook, mark_step
from .rules.formatting import format_amount, format_dt, parse_local_datetime
from .services import append_message, card, jsonable, system_event, update_case
from .storage import get_blobs
from .store import get_store
from .timeutil import effective_now, ensure_utc, utcnow

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
    return {"drafts": list((case.get("drafts") or {}).values()), "evidencePackAvailable": bool(case.get("evidencePackPath"))}


def consent_card_data(case: dict) -> dict:
    lang = case.get("language", "en")
    ex = case.get("extraction") or {}
    return {"version": CONSENT_VERSION, "text": CONSENT_TEXT.get(lang, CONSENT_TEXT["en"]),
            "purpose": "Fraud investigation and fund recovery", "withdrawable": True,
            "items": ["Confirmed transaction facts (amount, reference, date, receiver)", "Evidence files with SHA-256 hashes",
                      "Scammer contacts and links", "Your incident summary"],
            "amount": format_amount(ex.get("amount"), ex.get("currency")), "given": bool(case.get("consentGivenAt"))}


def timeline_card_data(case: dict) -> dict:
    return {"clocks": case.get("clocks") or [], "steps": (case.get("plan") or {}).get("steps", []),
            "bankStatus": case.get("bankStatus"), "effectiveNow": effective_now(case), "clockOffsetDays": case.get("clockOffsetDays", 0)}


def upload_card_data(lang: str, prompt: str | None = None) -> dict:
    return {"prompt": prompt, "accept": {"image": ["image/png", "image/jpeg", "image/webp"],
                                         "audio": ["audio/mpeg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/webm"]},
            "limits": {"images": 5, "imageMB": 10, "audioMinutes": 2}}


def add_card(case_id: str, kind: str, data: dict, lang: str, text: str | None = None) -> dict:
    return append_message(case_id, role="assistant", text=text, card=card(kind, data), lang=lang)


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
            steps = {s["id"]: s for s in case["plan"]["steps"]}
            bank_step = steps.get("report_bank") or {}
            data = {"clockId": c["id"], "label": c.get("labelLocal") or c["label"], "title": c.get("escalationTitleLocal") or c.get("escalationTitle"), "contact": c.get("contact"),
                    "dueDisplay": c["dueDisplay"], "draft": draft,
                    "bankComplaintDate": format_dt(bank_step.get("doneAt"), pb["timezone"]),
                    "bankReference": bank_step.get("user_reference") or case.get("bankCaseId")}
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
    return load(case_id)


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
                                       "escalation", "consentGivenAt", "bankCaseId")}
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
    latency = int((time.perf_counter() - t0) * 1000)
    update_case(case_id, {"drafts": drafts, "status": "filed" if case.get("status") in ("confirmed", "extracted") else case.get("status")})
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
    res = await guard.check(text, case_id)
    if not res["is_recovery_scam"]:
        return []
    update_case(case_id, {"flags": {"recovery_scam_detected": True}})
    log.info("recovery_scam_flagged", extra={"caseId": case_id, "step": "guard", "source": res["source"]})
    return [add_card(case_id, "warning", {"message": t("warning", lang), "followUp": t("warning_followup", lang),
                                          "reason": res["reason"], "source": res["source"]}, lang)]


# ------------------------------------------------------------------ bank handoff
async def send_to_bank(case_id: str, consent: bool, version: str) -> tuple[dict, list[dict]]:
    case = load(case_id)
    lang = case.get("language", "en")
    if not consent:
        system_event(case_id, "User declined to share with bank", lang)
        return case, [append_message(case_id, role="assistant", text=t("consent_declined", lang), lang=lang)]
    if case.get("bankCaseId"):
        return case, []
    if not case.get("extraction"):
        raise HTTPException(409, "confirm the facts first")
    if not case.get("plan"):
        case = recompute_plan(case_id)
    now = utcnow()
    update_case(case_id, {"consentGivenAt": now, "consentVersion": version or CONSENT_VERSION})
    case = load(case_id)
    envelope = bank_receiver.build_envelope(case, get_store().list_evidence(case_id), effective_now(case))
    settings = get_settings()
    if settings.bank_a2a_url:
        import httpx

        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(settings.bank_a2a_url, json=envelope, headers={"X-A2A-Token": settings.a2a_token})
            r.raise_for_status()
            bank_case = r.json()
    else:
        bank_case = await bank_receiver.receive(envelope)
    patch = {"bankCaseId": bank_case["id"], "bankStatus": "SENT", "status": "sent_to_bank"}
    update_case(case_id, patch)
    case = load(case_id)
    steps = {s["id"]: s for s in (case.get("plan") or {}).get("steps", [])}
    bank_step = "report_bank" if "report_bank" in steps else ("call_bank" if "call_bank" in steps else None)
    if bank_step and steps[bank_step].get("status") != "done":
        set_step(case_id, bank_step, "done", bank_case["id"])
    system_event(case_id, f"Case sent to bank (bank case {bank_case['id']})", lang)
    case = load(case_id)
    msgs = [add_card(case_id, "timeline", timeline_card_data(case), lang, text=t("sent_to_bank", lang))]
    return case, msgs


async def bank_decision(bank_case_id: str, decision: str, note: str | None, analyst: str) -> dict:
    store = get_store()
    bc = store.get_bank_case(bank_case_id)
    if not bc:
        raise HTTPException(404, "bank case not found")
    status = {"APPROVE_HOLD": "HOLD_APPROVED", "REQUEST_INFO": "INFO_REQUESTED", "REJECT": "REJECTED"}[decision]
    store.update_bank_case(bank_case_id, {"status": status, "decidedAt": utcnow(), "decidedBy": analyst, "decisionNote": note})
    store.add_audit({"actor": analyst, "action": decision, "bankCaseId": bank_case_id, "caseId": bc["caseId"],
                     "details": {"note": note, "holdLimitAmount": bc.get("holdLimitAmount") if decision == "APPROVE_HOLD" else None}})
    case = store.get_case(bc["caseId"])
    if case:
        lang = case.get("language", "en")
        update_case(case["id"], {"bankStatus": status})
        system_event(case["id"], f"Bank decision: {decision}" + (f" — {note}" if note else ""), lang)
        case = load(case["id"])
        if decision == "APPROVE_HOLD":
            add_card(case["id"], "timeline", timeline_card_data(case), lang, text=t("bank_hold", lang))
        elif decision == "REQUEST_INFO":
            q = note or "Please share any other screenshot or message about this payment."
            add_card(case["id"], "upload", upload_card_data(lang, q), lang, text=t("bank_info", lang, question=q))
        else:
            add_card(case["id"], "timeline", timeline_card_data(case), lang, text=t("bank_reject", lang))
    log.info("bank_decision", extra={"bankCaseId": bank_case_id, "caseId": bc["caseId"], "step": "decision", "decision": decision})
    return store.get_bank_case(bank_case_id)


# ------------------------------------------------------------------ evidence
def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def explain(case: dict, topic: str) -> dict:
    return explain_rule(pb_for(case), topic)


__all__ = ["HOLD_NOTE", "COMING_SOON"]
