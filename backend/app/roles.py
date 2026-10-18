"""CR-04: staff roles. Bank staff apply with a work email; an admin approves (custom claim role=bank + bankId),
rejects (with a reason) or revokes. Clients never set roles: claims are written here (Admin SDK) or, in mock
mode, in the local store. Every admin action is written to admin_audit."""
from __future__ import annotations

import logging
import re

from .config import get_settings
from .store import get_store
from .timeutil import utcnow

log = logging.getLogger("recoverai.roles")

REQ_COL = "bank_access_requests"
AUDIT_COL = "admin_audit"
MOCK_CLAIMS_COL = "mock_claims"  # mock mode only: stands in for Firebase custom claims
PENDING, APPROVED, REJECTED, REVOKED = "PENDING", "APPROVED", "REJECTED", "REVOKED"
STATUSES = (PENDING, APPROVED, REJECTED, REVOKED)
PHONE_DOMAIN = "@phone.recoverai.app"


def is_phone_email(email: str | None) -> bool:
    return bool(email) and email.lower().endswith(PHONE_DOMAIN)


def is_staff_email(email: str | None) -> bool:
    """A work-email account (bank applicant, analyst or admin), as opposed to a victim's phone account."""
    return bool(email) and not is_phone_email(email)


def mock_claims(uid: str) -> dict:
    return (get_store().get_doc(MOCK_CLAIMS_COL, uid) or {}).get("claims") or {}


def mock_uid_for_email(email: str) -> str:
    return "st-" + re.sub(r"[^a-z0-9]+", "-", email.lower()).strip("-")


def get_claims(uid: str) -> dict:
    if get_settings().effective_auth_mode == "mock":
        return mock_claims(uid)
    from firebase_admin import auth as fb_auth
    from .auth import _init_firebase
    _init_firebase()
    return dict(fb_auth.get_user(uid).custom_claims or {})


def set_claims(uid: str, claims: dict | None, revoke_sessions: bool = False) -> None:
    """Replace the user's custom claims. Live: needs firebaseauth.users.update on the runtime service account."""
    if get_settings().effective_auth_mode == "mock":
        get_store().set_doc(MOCK_CLAIMS_COL, uid, {"claims": claims or {}})
        return
    from firebase_admin import auth as fb_auth
    from .auth import _init_firebase
    _init_firebase()
    fb_auth.set_custom_user_claims(uid, claims or None)
    if revoke_sessions:  # existing refresh tokens stop working; the request status check blocks the current ID token
        fb_auth.revoke_refresh_tokens(uid)


def get_request(uid: str) -> dict | None:
    return get_store().get_doc(REQ_COL, uid)


def request_blocks_bank(uid: str) -> bool:
    """A bank role is honoured only while its access request (if the account has one) is APPROVED. The seeded demo
    analyst has no request and keeps working. This makes revoke immediate, even before the ID token expires."""
    r = get_request(uid)
    return bool(r) and r.get("status") != APPROVED


def audit(actor, action: str, target_uid: str, reason: str | None = None, **extra) -> dict:
    from .store import new_id
    aid = new_id("aa_")
    entry = {"at": utcnow(), "actorUid": actor.uid, "actorEmail": actor.email, "actorRole": actor.role,
             "action": action, "targetUid": target_uid, "reason": reason, **extra}
    get_store().set_doc(AUDIT_COL, aid, entry)
    log.info("admin_audit", extra={"step": "roles", "action": action})
    return {**entry, "id": aid}


def bank_id_for(bank_name: str, country: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (bank_name or "other").lower()).strip("-")[:40] or "other"
    return f"{country.lower()}-{slug}"
