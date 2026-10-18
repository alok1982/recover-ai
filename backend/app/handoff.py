"""CR-01 / PRD v2.4 F8 — safe bank handoff: sandbox mode, preview + confirmation token, send, withdraw, publicRef.

Nothing reaches a bank queue without consent, an explicit confirmation by the person (a valid confirmationToken from
the preview, `confirmed: true`) and a destination they saw (Sandbox or Live). The co-pilot has no send tool.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import random
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from . import actions
from .config import REPO_DIR, get_settings
from .events import pubsub
from .i18n import t
from .rules.formatting import format_amount, to_local
from .services import append_message, system_event, update_case
from .store import get_store
from .timeutil import effective_now, to_iso, utcnow

log = logging.getLogger("recoverai.handoff")

SANDBOX_WATERMARK = "SANDBOX — NOT SUBMITTED"
DETAILS_CHANGED = "Details changed — please review again"


# ---------------------------------------------------------------- sandbox (F8.1)
def live_allowed() -> bool:
    return get_settings().allow_live_submission


def initial_sandbox(requested: bool | None) -> bool:
    if not live_allowed():
        return True
    return get_settings().sandbox_default if requested is None else bool(requested)


def is_sandbox(case: dict) -> bool:
    """Effective destination: always sandbox when live submission is off; legacy cases without the field too."""
    if not live_allowed():
        return True
    return bool(case.get("sandbox", True))


def destination(case: dict) -> str:
    return "SANDBOX" if is_sandbox(case) else "LIVE"


@lru_cache
def demo_hashes() -> dict[str, str]:
    s = get_settings()
    for p in (REPO_DIR / "fixtures" / "hashes.json", Path(s.knowledge_dir) / "fixture_hashes.json"):
        if p.exists():
            return json.loads(p.read_text())["sha256"]
    log.warning("fixtures/hashes.json not found; demo-evidence detection off")
    return {}


def on_evidence(case: dict, sha256: str | None) -> list[dict]:
    """Demo evidence → force sandbox, lock it, and say so once."""
    if not sha256 or sha256 not in demo_hashes():
        return []
    patch: dict = {"sandbox": True, "sandboxLocked": True}
    flags = dict(case.get("flags") or {})
    msgs = []
    if not flags.get("demoEvidenceNotice"):
        flags["demoEvidenceNotice"] = True
        msgs.append(append_message(case["id"], role="assistant", text=t("demo_sandbox", case.get("language", "en")),
                                   lang=case.get("language", "en")))
    patch["flags"] = flags
    update_case(case["id"], patch)
    log.info("demo_evidence_sandbox", extra={"caseId": case["id"], "step": "sandbox", "fixture": demo_hashes()[sha256]})
    return msgs


def set_sandbox(case: dict, sandbox: bool) -> dict:
    if (case.get("submission") or {}).get("status") == "SENT":
        raise HTTPException(409, "The case was already sent; sandbox mode is locked")
    if not sandbox and not live_allowed():
        raise HTTPException(403, "Live submission is disabled in this prototype; cases always run in sandbox")
    if not sandbox and case.get("sandboxLocked"):
        raise HTTPException(409, "This case uses RecoverAI demo evidence, so it stays in sandbox mode")
    update_case(case["id"], {"sandbox": bool(sandbox)})
    return actions.load(case["id"])


# ---------------------------------------------------------------- publicRef (F8.5)
def new_public_ref(country: str, case_id: str, now=None) -> str:
    tz = "Asia/Kolkata" if country == "IN" else "Asia/Kuala_Lumpur"
    day = to_local(now or utcnow(), tz).strftime("%Y%m%d")
    store = get_store()
    rng = random.SystemRandom()
    for _ in range(50):
        ref = f"RAI-{country}-{day}-{rng.randint(0, 9999):04d}"
        if store.claim_public_ref(ref, case_id):
            return ref
    raise HTTPException(503, "could not allocate a case reference; try again")


def ensure_public_ref(case: dict) -> str:
    if case.get("publicRef"):
        return case["publicRef"]
    ref = new_public_ref(case["country"], case["id"], case.get("createdAt"))
    update_case(case["id"], {"publicRef": ref})
    case["publicRef"] = ref
    return ref


# ---------------------------------------------------------------- confirmation token (F8.2)
def _key() -> bytes:
    s = get_settings()
    if s.confirm_secret:
        return s.confirm_secret.encode()
    # No secret configured (local/mock): derive a stable per-project key so tokens survive across instances.
    return hashlib.sha256(f"recoverai-confirm::{s.project_id or 'local'}".encode()).digest()


def payload_digest(case: dict, evidence: list[dict], dest: str) -> str:
    """Hash of exactly what will be shared (facts, contacts, evidence hashes) plus the destination."""
    ex = case.get("extraction") or {}
    body = {
        "caseId": case["id"], "country": case["country"], "destination": dest,
        "facts": {k: ex.get(k) for k in ("amount", "currency", "reference_id", "occurred_at", "payment_method", "payer_bank",
                                          "beneficiary", "scammer_contacts", "urls", "scam_type", "narrative_en")},
        "incidentAt": to_iso(case.get("incidentAt")),
        "evidence": sorted((e["id"], e.get("sha256") or "") for e in evidence),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def make_token(case_id: str, digest: str, dest: str, now: float | None = None) -> tuple[str, int]:
    exp = int((now or time.time()) + get_settings().confirm_ttl_s)
    body = base64.urlsafe_b64encode(json.dumps({"c": case_id, "h": digest, "d": dest, "e": exp}, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}", exp


def check_token(token: str | None, case_id: str, digest: str, dest: str) -> None:
    try:
        body, sig = (token or "").rsplit(".", 1)
        if not hmac.compare_digest(hmac.new(_key(), body.encode(), hashlib.sha256).hexdigest(), sig):
            raise ValueError("bad signature")
        claims = json.loads(base64.urlsafe_b64decode(body.encode()))
    except Exception:  # noqa: BLE001
        raise HTTPException(409, "Confirmation missing or invalid — please review again") from None
    if claims.get("c") != case_id:
        raise HTTPException(409, "Confirmation is for another case — please review again")
    if claims.get("e", 0) < time.time():
        raise HTTPException(409, "Confirmation expired — please review again")
    if claims.get("d") != dest or claims.get("h") != digest:
        raise HTTPException(409, DETAILS_CHANGED)


def _mask(acct: str | None) -> str | None:
    if not acct:
        return None
    if "@" in acct:
        user, dom = acct.split("@", 1)
        return (user[:2] + "•" * max(1, len(user) - 2)) + "@" + dom
    return "•" * max(0, len(acct) - 4) + acct[-4:]


def summary(case: dict, evidence: list[dict]) -> dict:
    ex = case.get("extraction") or {}
    b = ex.get("beneficiary") or {}
    dest = destination(case)
    return {
        "publicRef": case.get("publicRef"), "destination": dest, "sandbox": dest == "SANDBOX", "liveAllowed": live_allowed(),
        "bankName": ex.get("payer_bank") or ("your bank"), "amount": format_amount(ex.get("amount"), ex.get("currency")),
        "reference_id": ex.get("reference_id"),
        "beneficiary": {"name": b.get("name"), "account": _mask(b.get("account_or_vpa")), "bank": b.get("bank")},
        "scammerContacts": ex.get("scammer_contacts") or [], "urls": ex.get("urls") or [],
        "evidence": [{"id": e["id"], "type": e["type"], "fileName": e.get("fileName"), "sha256": e.get("sha256")} for e in evidence],
        "narrative": ex.get("narrative_local") or ex.get("narrative_en"),
        "consentVersion": actions.CONSENT_VERSION,
    }


def active_submission(case: dict) -> bool:
    sub = case.get("submission") or {}
    if sub:
        return sub.get("status") == "SENT"
    return bool(case.get("bankCaseId")) and case.get("bankStatus") not in (None, "NONE", "WITHDRAWN")  # pre-CR-01 cases


def preview(case_id: str) -> dict:
    case = actions.load(case_id)
    if not case.get("extraction"):
        raise HTTPException(409, "confirm the facts first")
    if active_submission(case):
        raise HTTPException(409, "Already sent to the bank. Withdraw consent first to send again.")
    if destination(case) == "LIVE" and not live_allowed():
        raise HTTPException(403, "Live submission is disabled")
    ensure_public_ref(case)
    case = actions.load(case_id)
    evidence = get_store().list_evidence(case_id)
    dest = destination(case)
    token, exp = make_token(case_id, payload_digest(case, evidence, dest), dest)
    return {"summary": summary(case, evidence), "confirmationToken": token, "expiresAt": to_iso(datetime.fromtimestamp(exp, tz=timezone.utc))}


async def send(case_id: str, token: str | None, confirmed: bool) -> tuple[dict, list[dict]]:
    """Confirmed send → publish fraud_case.submit with attribute env=sandbox|live (F8.3)."""
    from .agents import bank_receiver

    if not confirmed:
        raise HTTPException(400, "Please tick the confirmation box first")
    case = actions.load(case_id)
    lang = case.get("language", "en")
    if active_submission(case):
        raise HTTPException(409, "Already sent to the bank. Withdraw consent first to send again.")
    if not case.get("extraction"):
        raise HTTPException(409, "confirm the facts first")
    dest = destination(case)
    if dest == "LIVE" and not live_allowed():
        raise HTTPException(403, "Live submission is disabled")
    evidence = get_store().list_evidence(case_id)
    check_token(token, case_id, payload_digest(case, evidence, dest), dest)
    if not case.get("plan"):
        case = actions.recompute_plan(case_id)
    ref = ensure_public_ref(case)
    sandbox = dest == "SANDBOX"
    now = utcnow()
    update_case(case_id, {"consentGivenAt": now, "consentVersion": actions.CONSENT_VERSION, "consentWithdrawnAt": None,
                          "sandbox": sandbox, "sandboxLocked": True})
    case = actions.load(case_id)
    envelope = bank_receiver.build_envelope(case, evidence, effective_now(case))
    envelope["payload"].update({"publicRef": ref, "sandbox": sandbox})
    bank_case_id = bank_receiver.bank_case_id_for(envelope)
    s = get_settings()
    env = "sandbox" if sandbox else "live"
    try:
        message_id = await pubsub.publish(s.topic_case_submitted, envelope, {"eventTopic": s.topic_case_submitted, "caseId": case_id,
                                                                             "intent": "fraud_case.submit", "env": env})
    except Exception as e:  # noqa: BLE001
        log.exception("publish fraud-case-submitted failed", extra={"caseId": case_id})
        raise HTTPException(503, "could not send to the bank right now; please try again") from e
    update_case(case_id, {"bankCaseId": bank_case_id, "bankStatus": "SENT", "status": "sent_to_bank",
                          "bankHandoff": {"topic": s.topic_case_submitted, "messageId": message_id, "sentAt": envelope["sent_at"], "env": env},
                          "submission": {"status": "SENT", "destination": dest, "confirmedAt": now, "publicRef": ref}})
    case = actions.load(case_id)
    steps = {st["id"]: st for st in (case.get("plan") or {}).get("steps", [])}
    bank_step = "report_bank" if "report_bank" in steps else ("call_bank" if "call_bank" in steps else None)
    if bank_step and steps[bank_step].get("status") != "done":
        actions.set_step(case_id, bank_step, "done", f"{ref} (sandbox)" if sandbox else ref)
    system_event(case_id, f"Case sent to {'the sandbox (test)' if sandbox else 'the bank'} — reference {ref}", lang)
    log.info("bank_submission", extra={"caseId": case_id, "step": "send", "destination": dest, "publicRef": ref})
    case = actions.load(case_id)
    text = t("sent_to_sandbox" if sandbox else "sent_to_bank_ref", lang, ref=ref)
    msgs = [actions.add_card(case_id, "timeline", actions.timeline_card_data(case), lang, text=text)]
    return case, msgs


# ---------------------------------------------------------------- withdraw (F8.4)
def withdraw_card_data(case: dict) -> dict:
    return {"publicRef": case.get("publicRef"), "sandbox": is_sandbox(case), "bankStatus": case.get("bankStatus"),
            "holdPlaced": case.get("bankStatus") == "HOLD_APPROVED"}


async def withdraw(case_id: str, confirmed: bool) -> tuple[dict, list[dict]]:
    if not confirmed:
        raise HTTPException(400, "Please tick the confirmation box first")
    case = actions.load(case_id)
    lang = case.get("language", "en")
    if not active_submission(case):
        raise HTTPException(409, "Nothing to withdraw: the case is not shared with a bank")
    ref = ensure_public_ref(case)
    sandbox = is_sandbox(case) if not case.get("submission") else case["submission"].get("destination") == "SANDBOX"
    now = utcnow()
    envelope = {"from_agent": "recoverai.victim_copilot", "to_agent": f"bank.fraud_case_receiver.{case['country'].lower()}",
                "intent": "fraud_case.withdraw", "sent_at": to_iso(now),
                "payload": {"caseId": case_id, "bankCaseId": case.get("bankCaseId"), "publicRef": ref, "withdrawnAt": to_iso(now)}}
    s = get_settings()
    try:
        await pubsub.publish(s.topic_case_submitted, envelope, {"eventTopic": s.topic_case_submitted, "caseId": case_id,
                                                                "intent": "fraud_case.withdraw", "env": "sandbox" if sandbox else "live"})
    except Exception as e:  # noqa: BLE001
        log.exception("publish fraud_case.withdraw failed", extra={"caseId": case_id})
        raise HTTPException(503, "could not reach the bank right now; please try again") from e
    sub = dict(case.get("submission") or {"destination": "SANDBOX" if sandbox else "LIVE", "publicRef": ref})
    sub.update({"status": "WITHDRAWN", "withdrawnAt": now})
    update_case(case_id, {"consentWithdrawnAt": now, "bankStatus": "WITHDRAWN", "submission": sub})
    system_event(case_id, f"Consent withdrawn — reference {ref}", lang)
    log.info("consent_withdrawn", extra={"caseId": case_id, "step": "withdraw", "publicRef": ref})
    case = actions.load(case_id)
    return case, [append_message(case_id, role="assistant", text=t("withdrawn", lang, ref=ref), lang=lang)]


def watermark_text(case: dict, text: str | None) -> str | None:
    if text is None or not is_sandbox(case) or text.startswith(SANDBOX_WATERMARK):
        return text
    return f"{SANDBOX_WATERMARK}\n\n{text}"


def watermark_draft(case: dict, d: dict) -> dict:
    return {**d, "en": watermark_text(case, d.get("en")), "local": watermark_text(case, d.get("local")), "sandbox": is_sandbox(case)}
