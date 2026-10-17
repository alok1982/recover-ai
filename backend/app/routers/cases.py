"""Victim API: cases, evidence, card actions and the SSE co-pilot chat."""
from __future__ import annotations

import logging
import mimetypes
from datetime import timedelta
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException

from .. import actions
from ..agents import copilot, voice
from ..auth import User, current_user
from ..config import get_settings
from ..i18n import t
from ..models import (ChatReq, ClockReq, CreateCaseReq, ExtractionPatch, GuardReq, RegisterEvidenceReq, SendToBankReq,
                      StepPatch, UpdateCaseReq, UploadUrlReq)
from ..services import append_message, get_owned_case, jsonable, system_event, update_case
from ..sse import sse_response
from ..storage import get_blobs
from ..store import get_store, new_id
from ..timeutil import utcnow

log = logging.getLogger("recoverai.api")
router = APIRouter(prefix="/api/cases", tags=["cases"])

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/mp4", "audio/x-m4a", "audio/m4a", "audio/aac", "audio/wav", "audio/x-wav",
               "audio/webm", "audio/ogg"}


def _view(case: dict) -> dict:
    v = jsonable({k: val for k, val in case.items() if k not in ("turnTimes",)})
    v["demoMode"] = get_settings().demo_mode
    return v


@router.post("")
async def create_case(req: CreateCaseReq, user: User = Depends(current_user)) -> dict:
    store = get_store()
    s = get_settings()
    open_cases = [c for c in store.list_cases(owner_uid=user.uid) if c.get("status") != "closed"]
    if len(open_cases) >= s.max_open_cases_per_user:
        raise HTTPException(429, f"You already have {s.max_open_cases_per_user} open cases. Continue or delete one first.")
    now = utcnow()
    case_id = store.create_case({
        "ownerUid": user.uid, "country": req.country, "language": req.language,
        "consentGivenAt": None, "consentVersion": None, "bankStatus": "NONE", "clocks": [], "status": "draft",
        "createdAt": now, "updatedAt": now, "incidentAt": None, "clockOffsetDays": 0, "extraction": None, "plan": None,
        "explanation": None, "drafts": {}, "evidencePackPath": None, "flags": {"recovery_scam_detected": False},
        "bankCaseId": None, "evidenceCount": 0, "turnTimes": [],
    })
    greeting = append_message(case_id, role="assistant", text=t("greeting", req.language), lang=req.language)
    log.info("case_created", extra={"caseId": case_id, "step": "create", "country": req.country, "lang": req.language})
    return {"caseId": case_id, "greeting": jsonable(greeting)}


@router.get("")
def list_my_cases(user: User = Depends(current_user)) -> dict:
    return {"cases": [{"id": c["id"], "country": c["country"], "status": c.get("status"), "createdAt": jsonable(c.get("createdAt"))}
                      for c in get_store().list_cases(owner_uid=user.uid)]}


@router.get("/{case_id}")
async def get_case(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    await actions.evaluate(case_id)  # lazy deadline evaluation on load
    return {"case": _view(actions.load(case_id))}


@router.patch("/{case_id}")
async def patch_case(case_id: str, req: UpdateCaseReq, user: User = Depends(current_user)) -> dict:
    case = get_owned_case(user, case_id)
    patch = {}
    if req.country and req.country != case["country"]:
        patch["country"] = req.country
    if req.language and req.language != case.get("language"):
        patch["language"] = req.language
    if not patch:
        return {"case": _view(case), "messages": []}
    update_case(case_id, patch)
    system_event(case_id, f"User changed settings: {patch}", patch.get("language", case.get("language", "en")))
    msgs = []
    if case.get("plan") or (req.country and case.get("status") not in ("draft", "extracted")):
        # Re-compute the plan (country switch) and re-explain it in the new language (language switch).
        async for ev in actions.plan_stream(case_id):
            if ev["type"] in ("card", "message"):
                msgs.append(ev["message"])
            elif ev["type"] == "done":
                msgs.append(ev["message"])
    return {"case": _view(actions.load(case_id)), "messages": msgs}


@router.delete("/{case_id}")
def delete_case(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    try:
        get_blobs().delete_prefix(f"cases/{case_id}/")
    except Exception:  # noqa: BLE001
        log.warning("blob cleanup failed", extra={"caseId": case_id})
    get_store().delete_case(case_id)
    log.info("case_deleted", extra={"caseId": case_id, "step": "delete"})
    return {"deleted": True}


@router.get("/{case_id}/messages")
def messages(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    return {"messages": jsonable(get_store().list_messages(case_id))}


# ------------------------------------------------------------------ evidence
@router.post("/{case_id}/evidence/upload-url")
def upload_url(case_id: str, req: UploadUrlReq, user: User = Depends(current_user)) -> dict:
    case = get_owned_case(user, case_id)
    s = get_settings()
    mime = req.mimeType.split(";")[0].strip().lower()
    if mime in IMAGE_TYPES:
        limit = s.max_image_bytes
    elif mime in AUDIO_TYPES:
        limit = s.max_audio_bytes
    else:
        raise HTTPException(415, "unsupported file type")
    if req.sizeBytes and req.sizeBytes > limit:
        raise HTTPException(413, "file too large")
    if req.purpose == "evidence" and (case.get("evidenceCount") or 0) >= s.max_evidence_per_case:
        raise HTTPException(429, "evidence limit reached for this case")
    ext = mimetypes.guess_extension(mime) or ".bin"
    folder = "voice" if req.purpose == "voice" else "evidence"
    path = f"cases/{case_id}/{folder}/{new_id()}{ext}"
    return get_blobs().upload_url(path, mime, limit)


@router.post("/{case_id}/evidence")
async def register_evidence(case_id: str, req: RegisterEvidenceReq, user: User = Depends(current_user)) -> dict:
    case = get_owned_case(user, case_id)
    s = get_settings()
    if (case.get("evidenceCount") or 0) >= s.max_evidence_per_case:
        raise HTTPException(429, "evidence limit reached for this case")
    store, blobs = get_store(), get_blobs()
    rec = {"type": req.type, "uploadedAt": utcnow(), "fileName": req.fileName}
    if req.type == "text":
        if not (req.textContent or "").strip():
            raise HTTPException(400, "text is empty")
        txt = req.textContent.strip()[: s.max_text_chars]
        rec.update(textContent=txt, mimeType="text/plain", gcsPath=None, sha256=actions.sha256_hex(txt.encode("utf-8")))
    else:
        if not req.gcsPath or not req.gcsPath.startswith(f"cases/{case_id}/evidence/"):
            raise HTTPException(400, "invalid path")
        size = blobs.size(req.gcsPath)
        limit = s.max_image_bytes if req.type == "image" else s.max_audio_bytes
        if size is None:
            raise HTTPException(400, "upload not found")
        if size > limit:
            raise HTTPException(413, "file too large")
        data = blobs.read_bytes(req.gcsPath)
        rec.update(gcsPath=req.gcsPath, mimeType=req.mimeType, sha256=actions.sha256_hex(data), sizeBytes=size)
    ev = store.add_evidence(case_id, rec)
    update_case(case_id, {"evidenceCount": (case.get("evidenceCount") or 0) + 1})
    system_event(case_id, f"User added {req.type} evidence ({ev['id']})", case.get("language", "en"))
    warnings = []
    if req.type == "text":  # F10: pasted/uploaded text is checked automatically
        warnings = await actions.guard_text(case_id, rec["textContent"], case.get("language", "en"))
    return {"evidence": jsonable(_evidence_view(ev)), "messages": jsonable(warnings)}


def _evidence_view(e: dict) -> dict:
    v = dict(e)
    if e.get("gcsPath") and e["type"] in ("image", "audio"):
        try:
            v["previewUrl"] = get_blobs().read_url(e["gcsPath"])
        except Exception:  # noqa: BLE001
            v["previewUrl"] = None
    return v


@router.get("/{case_id}/evidence")
def list_evidence(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    return {"evidence": jsonable([_evidence_view(e) for e in get_store().list_evidence(case_id)])}


# ------------------------------------------------------------------ card actions (REST)
async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    out = []
    async for ev in gen:
        if ev["type"] in ("card", "message", "done") and ev.get("message"):
            out.append(ev["message"])
    return out


@router.post("/{case_id}/extract")
async def run_extract(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    msgs = await _collect(actions.extract(case_id))
    return {"case": _view(actions.load(case_id)), "messages": msgs}


@router.patch("/{case_id}/extraction")
def patch_extraction(case_id: str, req: ExtractionPatch, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    case = actions.patch_extraction(case_id, req.fields, req.confirm)
    return {"case": _view(case), "facts": jsonable(actions.facts_card_data(case))}


@router.post("/{case_id}/plan")
async def run_plan(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    msgs = await _collect(actions.plan_stream(case_id))
    return {"case": _view(actions.load(case_id)), "messages": msgs}


@router.post("/{case_id}/drafts")
async def run_drafts(case_id: str, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    msgs = await _collect(actions.drafts_stream(case_id))
    return {"case": _view(actions.load(case_id)), "messages": msgs}


@router.post("/{case_id}/evidence-pack")
async def evidence_pack(case_id: str, rebuild: bool = False, user: User = Depends(current_user)) -> dict:
    case = get_owned_case(user, case_id)
    if rebuild or not case.get("evidencePackPath"):
        await actions.build_evidence_pack(case_id)
    return {"url": actions.evidence_pack_url(case_id), "expiresInSeconds": 900}


@router.patch("/{case_id}/steps/{step_id}")
async def patch_step(case_id: str, step_id: str, req: StepPatch, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    actions.set_step(case_id, step_id, req.status, req.reference)
    msgs = await actions.evaluate(case_id)
    return {"case": _view(actions.load(case_id)), "messages": jsonable(msgs)}


@router.post("/{case_id}/clock")
async def time_travel(case_id: str, req: ClockReq, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    case, msgs = await actions.time_travel(case_id, req.addDays, req.jumpToDay, req.reset)
    return {"case": _view(case), "messages": jsonable(msgs)}


@router.post("/{case_id}/guard")
async def run_guard(case_id: str, req: GuardReq, user: User = Depends(current_user)) -> dict:
    case = get_owned_case(user, case_id)
    msgs = await actions.guard_text(case_id, req.text, case.get("language", "en"))
    return {"is_recovery_scam": bool(msgs), "messages": jsonable(msgs)}


@router.post("/{case_id}/send-to-bank")
async def send_to_bank(case_id: str, req: SendToBankReq, user: User = Depends(current_user)) -> dict:
    get_owned_case(user, case_id)
    case, msgs = await actions.send_to_bank(case_id, req.consent, req.consentVersion)
    return {"case": _view(case), "messages": jsonable(msgs)}


# ------------------------------------------------------------------ chat (SSE)
DIRECTED = {"evidence_added": actions.extract, "facts_confirmed": actions.plan_stream, "generate_all": actions.drafts_stream}


def _rate_limit(case: dict) -> None:
    s = get_settings()
    now = utcnow()
    times = [x for x in (case.get("turnTimes") or []) if x > now - timedelta(hours=1)]
    if len(times) >= s.max_turns_per_hour:
        raise HTTPException(429, "Too many messages for this case in the last hour. Please wait a little.")
    update_case(case["id"], {"turnTimes": times + [now]})


async def chat_events(case_id: str, req: ChatReq) -> AsyncIterator[dict]:
    store = get_store()
    case = actions.load(case_id)
    lang = case.get("language", "en")
    text = (req.text or "").strip() or None
    if req.audioPath:
        if not req.audioPath.startswith(f"cases/{case_id}/voice/"):
            yield {"type": "error", "message": "invalid audio path"}
            return
        yield {"type": "tool_status", "name": "transcribe", "state": "running"}
        mime = mimetypes.guess_type(req.audioPath)[0] or "audio/webm"
        text = await voice.transcribe(req.audioPath, mime, lang, case_id)
        yield {"type": "transcript", "text": text}
    if text:
        um = append_message(case_id, role="user", text=text, lang=lang, audio_path=req.audioPath)
        yield {"type": "user_message", "message": jsonable(um)}
    elif req.trigger:
        system_event(case_id, f"Card action: {req.trigger}", lang)

    for m in await actions.evaluate(case_id):  # lazy clocks on every turn
        yield actions.msg_event(m)

    # F10: guard runs on every user message and on newly attached text evidence — before the co-pilot.
    flagged = False
    texts = [text] if text else []
    for eid in req.evidenceIds:
        ev = store.get_evidence(case_id, eid)
        if ev and ev.get("type") == "text":
            texts.append(ev.get("textContent") or "")
    for tx in texts:
        for m in await actions.guard_text(case_id, tx, lang):
            flagged = True
            yield actions.msg_event(m)

    if req.trigger in DIRECTED and not text:
        last = None
        async for ev in DIRECTED[req.trigger](case_id):
            last = ev
            yield ev
        if not last or last.get("type") != "done":
            yield {"type": "done", "messageId": None}
        return
    async for ev in copilot.run_turn(case_id, text, flagged):
        yield ev


@router.post("/{case_id}/chat")
async def chat(case_id: str, req: ChatReq, user: User = Depends(current_user)):
    case = get_owned_case(user, case_id)
    if not (req.text or req.audioPath or req.trigger):
        raise HTTPException(400, "empty turn")
    _rate_limit(case)
    return sse_response(chat_events(case_id, req))
