"""CR-04: bank-staff access requests and the admin console APIs.

  POST /api/bank-access/request                     work-email account → bank_access_requests/{uid} = PENDING
  GET  /api/admin/bank-requests?status=             admin only
  POST /api/admin/bank-requests/{uid}/approve       admin only → custom claim role=bank + bankId
  POST /api/admin/bank-requests/{uid}/reject        admin only, reason required
  POST /api/admin/users/{uid}/revoke-bank           admin only → claim removed, sessions revoked
  GET  /api/admin/audit                             admin only
Roles are never taken from the request body. Every admin action writes admin_audit."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import profile as P
from .. import roles as R
from ..auth import User, admin_user, current_user
from ..services import jsonable
from ..store import get_store
from ..timeutil import utcnow

log = logging.getLogger("recoverai.api")
router = APIRouter(prefix="/api/bank-access", tags=["bank-access"])
admin = APIRouter(prefix="/api/admin", tags=["admin"])


class AccessReq(BaseModel):
    fullName: str = Field(min_length=2, max_length=80)
    country: str = Field(pattern="^(IN|MY)$")
    bankName: str = Field(min_length=2, max_length=80)
    bankOther: str | None = Field(default=None, max_length=80)
    employeeId: str = Field(min_length=1, max_length=40)
    designation: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class ApproveReq(BaseModel):
    bankId: str | None = Field(default=None, max_length=60, pattern=r"^[a-z0-9-]+$")


class ReasonReq(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class RevokeReq(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


def _public(r: dict) -> dict:
    return {k: jsonable(v) for k, v in r.items()}


@router.post("/request")
def request_access(req: AccessReq, user: User = Depends(current_user)) -> dict:
    if user.anonymous:
        raise HTTPException(401, {"code": "SIGN_IN_REQUIRED", "message": "Please sign in."})
    if not R.is_staff_email(user.email):
        # A victim's phone account never becomes a bank account (same uid would mix victim cases with bank access).
        raise HTTPException(409, {"code": "USE_WORK_EMAIL",
                                  "message": "Bank staff apply with a separate work-email account, not a victim phone account."})
    if user.role in ("bank", "admin") and not R.request_blocks_bank(user.uid):
        raise HTTPException(409, {"code": "ALREADY_STAFF", "message": "This account already has a staff role."})
    bank = req.bankName.strip()
    if bank != P.OTHER_BANK and bank not in P.BANKS.get(req.country, []):
        raise HTTPException(422, {"code": "BANK_REQUEST_INVALID", "errors": {"bankName": "Pick a bank from the list or Other."}})
    if bank == P.OTHER_BANK and not (req.bankOther or "").strip():
        raise HTTPException(422, {"code": "BANK_REQUEST_INVALID", "errors": {"bankOther": "Enter the bank name."}})
    old = R.get_request(user.uid) or {}
    if old.get("status") == R.APPROVED and user.role == "bank":
        raise HTTPException(409, {"code": "ALREADY_STAFF", "message": "This account already has bank access."})
    now = utcnow()
    doc = {"uid": user.uid, "email": user.email, "fullName": req.fullName.strip(), "country": req.country,
           "bankName": bank, "bankOther": (req.bankOther or "").strip() or None, "employeeId": req.employeeId.strip(),
           "designation": req.designation.strip(), "note": (req.note or "").strip() or None, "status": R.PENDING,
           "createdAt": old.get("createdAt") or now, "updatedAt": now, "decidedBy": None, "decidedAt": None,
           "reason": None, "bankId": None}
    get_store().set_doc(R.REQ_COL, user.uid, doc)
    R.audit(user, "request_submitted", user.uid, previousStatus=old.get("status"))
    return _public({**doc, "id": user.uid})


def _need(uid: str) -> dict:
    r = R.get_request(uid)
    if not r:
        raise HTTPException(404, "no access request for this user")
    return r


@admin.get("/bank-requests")
def list_requests(status: str | None = Query(default=None), user: User = Depends(admin_user)) -> dict:
    if status and status.upper() not in R.STATUSES:
        raise HTTPException(422, "status must be one of " + ", ".join(R.STATUSES))
    rows = get_store().list_docs(R.REQ_COL, ("status", status.upper()) if status else None)
    rows.sort(key=lambda r: str(r.get("updatedAt") or r.get("createdAt") or ""), reverse=True)
    counts: dict[str, int] = {s: 0 for s in R.STATUSES}
    for r in get_store().list_docs(R.REQ_COL):
        counts[r.get("status", R.PENDING)] = counts.get(r.get("status", R.PENDING), 0) + 1
    return {"requests": [_public(r) for r in rows], "counts": counts}


@admin.post("/bank-requests/{uid}/approve")
def approve(uid: str, req: ApproveReq | None = None, user: User = Depends(admin_user)) -> dict:
    r = _need(uid)
    if r.get("status") == R.APPROVED:
        raise HTTPException(409, "already approved")
    bank = r.get("bankOther") if r.get("bankName") == P.OTHER_BANK else r.get("bankName")
    bank_id = (req.bankId if req and req.bankId else None) or R.bank_id_for(bank or "other", r.get("country", "IN"))
    try:
        claims = R.get_claims(uid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, "user not found") from e
    if claims.get("role") == "admin":
        raise HTTPException(409, "admins cannot be given the bank role")
    R.set_claims(uid, {**claims, "role": "bank", "bankId": bank_id, "name": r.get("fullName")})
    now = utcnow()
    upd = {**r, "status": R.APPROVED, "bankId": bank_id, "decidedBy": user.email or user.uid, "decidedAt": now,
           "updatedAt": now, "reason": None}
    get_store().set_doc(R.REQ_COL, uid, upd)
    R.audit(user, "approve", uid, bankId=bank_id, previousStatus=r.get("status"))
    return _public(upd)


@admin.post("/bank-requests/{uid}/reject")
def reject(uid: str, req: ReasonReq, user: User = Depends(admin_user)) -> dict:
    r = _need(uid)
    if r.get("status") != R.PENDING:
        raise HTTPException(409, "only pending requests can be rejected (use revoke for approved access)")
    now = utcnow()
    upd = {**r, "status": R.REJECTED, "reason": req.reason.strip(), "decidedBy": user.email or user.uid,
           "decidedAt": now, "updatedAt": now}
    get_store().set_doc(R.REQ_COL, uid, upd)
    R.audit(user, "reject", uid, reason=req.reason.strip(), previousStatus=r.get("status"))
    return _public(upd)


@admin.post("/users/{uid}/revoke-bank")
def revoke(uid: str, req: RevokeReq | None = None, user: User = Depends(admin_user)) -> dict:
    if uid == user.uid:
        raise HTTPException(409, "you cannot revoke your own access")
    try:
        claims = R.get_claims(uid)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, "user not found") from e
    if claims.get("role") == "admin":
        raise HTTPException(409, "admin accounts are not revoked here")
    reason = ((req.reason or "").strip() or None) if req else None
    R.set_claims(uid, {k: v for k, v in claims.items() if k not in ("role", "bankId")}, revoke_sessions=True)
    now = utcnow()
    r = R.get_request(uid) or {"uid": uid, "createdAt": now, "email": None, "fullName": claims.get("name")}
    upd = {**r, "status": R.REVOKED, "reason": reason, "decidedBy": user.email or user.uid, "decidedAt": now,
           "updatedAt": now}
    get_store().set_doc(R.REQ_COL, uid, upd)
    R.audit(user, "revoke_bank", uid, reason=reason, previousRole=claims.get("role"), previousStatus=r.get("status"))
    return _public(upd)


@admin.get("/audit")
def audit_log(limit: int = Query(default=100, ge=1, le=500), user: User = Depends(admin_user)) -> dict:
    rows = sorted(get_store().list_docs(R.AUDIT_COL), key=lambda a: str(a.get("at")), reverse=True)[:limit]
    return {"entries": [_public(a) for a in rows]}
