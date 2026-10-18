"""CR-03 B/C: the signed-in victim's account and profile (users/{uid}; written only by the backend)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .. import profile as P
from ..auth import User, current_user, victim_user
from .. import roles as R
from .. import demobank
from ..config import get_settings
from ..services import jsonable
from ..storage import get_blobs
from ..store import get_store
from ..timeutil import utcnow

log = logging.getLogger("recoverai.api")
router = APIRouter(prefix="/api/me", tags=["me"])


class ProfileReq(BaseModel):
    profile: dict = Field(default_factory=dict)


class TermsReq(BaseModel):
    version: str = Field(min_length=1, max_length=40)


def ensure_user(user: User) -> dict:
    """users/{uid}, created on first use (phone from the synthetic sign-in email; phoneVerified stays false
    until OTP verification exists)."""
    store = get_store()
    doc = store.get_user(user.uid)
    if doc:
        return doc
    phone = P.phone_from_email(user.email)
    prof = {"country": P.country_of_phone(phone)} if P.country_of_phone(phone) else {}
    doc = {"phoneE164": phone, "phoneVerified": False, "createdAt": utcnow(), "termsAcceptedAt": None, "termsVersion": None,
           "profile": prof, "profileStatus": P.compute_status(prof), "profileUpdatedAt": None}
    store.set_user(user.uid, doc)
    log.info("user_created", extra={"step": "me"})
    return store.get_user(user.uid) or doc


def get_profile(uid: str) -> dict:
    u = get_store().get_user(uid) or {}
    return u.get("profile") or {}


def view(doc: dict) -> dict:
    prof = doc.get("profile") or {}
    return {"uid": doc.get("uid"), "phoneE164": doc.get("phoneE164"), "phoneMasked": P.mask_phone(doc.get("phoneE164")),
            "phoneVerified": bool(doc.get("phoneVerified")), "termsAcceptedAt": jsonable(doc.get("termsAcceptedAt")),
            "termsVersion": doc.get("termsVersion"), "termsCurrent": P.TERMS_VERSION, "profile": prof,
            "profileStatus": P.compute_status(prof), "profileUpdatedAt": jsonable(doc.get("profileUpdatedAt")),
            "firstName": P.first_name(prof)}


def staff_view(user: User) -> dict:
    """CR-04: a work-email account (bank applicant, analyst or admin). No victim profile is created for it."""
    req = R.get_request(user.uid)
    role = user.role
    if role == "bank" and R.request_blocks_bank(user.uid):
        role = None  # revoked: the old ID token may still carry the claim until it expires
    public = {k: jsonable(v) for k, v in (req or {}).items() if k not in ("id",)} if req else None
    return {"uid": user.uid, "accountType": "staff", "email": user.email, "role": role or None,
            "requestStatus": (req or {}).get("status"), "request": public,
            "banks": demobank.staff_banks(), "demo": demobank.active()}


@router.get("")
def me(user: User = Depends(current_user)) -> dict:
    if user.anonymous:
        raise HTTPException(401, {"code": "SIGN_IN_REQUIRED", "message": "Please sign in with your phone number."})
    if user.role in ("bank", "admin") or R.is_staff_email(user.email):
        return staff_view(user)
    return {**view(ensure_user(user)), "accountType": "victim", "role": "victim", "requestStatus": None, "banks": P.BANKS}


@router.post("/terms")
def accept_terms(req: TermsReq, user: User = Depends(victim_user)) -> dict:
    ensure_user(user)
    get_store().update_user(user.uid, {"termsAcceptedAt": utcnow(), "termsVersion": req.version})
    return view(get_store().get_user(user.uid) or {})


@router.put("/profile")
def put_profile(req: ProfileReq, user: User = Depends(victim_user)) -> dict:
    doc = ensure_user(user)
    clean, err = P.validate(req.profile)
    old = doc.get("profile") or {}
    merged = {**old, **clean}
    merged = {k: v for k, v in merged.items() if v not in ("", None)}
    err.update({k: v for k, v in P.check_against_country(merged).items() if k in clean or k == "primaryBankOther"})
    if err:
        raise HTTPException(422, {"code": "PROFILE_INVALID", "errors": err})
    status = P.compute_status(merged)
    get_store().update_user(user.uid, {"profile": merged, "profileStatus": status, "profileUpdatedAt": utcnow()})
    changed = sorted(k for k in set(old) | set(merged) if old.get(k) != merged.get(k))
    if changed and old:
        from ..services import mark_profile_changed
        mark_profile_changed(user.uid)
    log.info("profile_saved", extra={"step": "profile", "complete": status["complete"], "fields": changed})
    return {**view(get_store().get_user(user.uid) or {}), "changed": changed}


@router.delete("")
def delete_me(user: User = Depends(current_user)) -> dict:
    """SHOULD: delete the account, its profile and the cases it owns (evidence files included). Records already
    shared with a bank stay with the bank under the consent given. CR-04: a staff account deletes its bank access
    request (the admin audit log is kept); admins cannot delete themselves here."""
    store = get_store()
    if user.anonymous:
        raise HTTPException(401, {"code": "SIGN_IN_REQUIRED", "message": "Please sign in."})
    if user.role == "admin":
        raise HTTPException(409, {"code": "ADMIN_ACCOUNT", "message": "Admin accounts are managed with scripts/create_admin.py."})
    if user.role == "bank" or R.is_staff_email(user.email):
        had = R.get_request(user.uid)
        if had:
            store.delete_doc(R.REQ_COL, user.uid)
            R.audit(user, "request_deleted_by_applicant", user.uid, previousStatus=had.get("status"))
        log.info("staff_user_deleted", extra={"step": "me"})
        return {"deleted": True, "cases": 0}
    cases = store.list_cases(owner_uid=user.uid)
    for c in cases:
        try:
            get_blobs().delete_prefix(f"cases/{c['id']}/")
        except Exception:  # noqa: BLE001
            log.warning("blob cleanup failed", extra={"caseId": c["id"]})
        store.delete_case(c["id"])
    store.delete_user(user.uid)
    if get_settings().effective_auth_mode != "mock":
        from firebase_admin import auth as fb_auth
        try:
            fb_auth.delete_user(user.uid)
        except Exception as e:  # noqa: BLE001
            log.warning("auth user delete failed", extra={"err": str(e)[:200]})
    log.info("user_deleted", extra={"step": "me", "cases": len(cases)})
    return {"deleted": True, "cases": len(cases)}
