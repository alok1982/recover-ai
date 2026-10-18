"""Firebase ID-token verification.

Victims (CR-03): phone + password accounts on the Email/Password provider (synthetic `<digits>@phone.recoverai.app`).
Anonymous tokens are rejected on victim routes (old anonymous data is left in place). Analysts: email/password
with a `role: bank` custom claim (unchanged)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi import Header, HTTPException

from .config import get_settings

log = logging.getLogger("recoverai.auth")
_firebase_ready = False


@dataclass(frozen=True)
class User:
    uid: str
    role: str | None = None
    name: str | None = None
    email: str | None = None
    anonymous: bool = False

    @property
    def is_bank(self) -> bool:
        return self.role == "bank"


def _init_firebase() -> None:
    global _firebase_ready
    if not _firebase_ready:
        import firebase_admin

        if not firebase_admin._apps:
            opts = {"projectId": get_settings().project_id} if get_settings().project_id else None
            firebase_admin.initialize_app(options=opts)
        _firebase_ready = True


def verify_token(token: str) -> User:
    mode = get_settings().effective_auth_mode
    if mode == "mock":
        # Local/offline only: "mock:<uid>" or "mock:bank:<analyst name>"
        if not token.startswith("mock:"):
            raise HTTPException(401, "invalid mock token")
        parts = token.split(":", 2)
        if len(parts) == 3 and parts[1] == "bank":
            return User(uid=f"bank-{parts[2]}", role="bank", name=parts[2])
        if len(parts) == 3 and parts[1] == "admin":  # CR-04 mock admin: "mock:admin:<name>"
            return User(uid=f"admin-{parts[2]}", role="admin", name=parts[2], email=f"{parts[2].lower()}@admin.mock")
        if len(parts) == 3 and parts[1] == "staff":  # CR-04 mock work-email account; claims live in the local store
            from .roles import mock_claims, mock_uid_for_email
            uid = mock_uid_for_email(parts[2])
            c = mock_claims(uid)
            return User(uid=uid, role=c.get("role"), name=c.get("name"), email=parts[2].lower())
        if len(parts) == 3 and parts[1] == "phone":  # mock phone account: "mock:phone:+919000000001"
            from .profile import phone_email
            digits = parts[2].lstrip("+")
            return User(uid=f"ph-{digits}", email=phone_email("+" + digits))
        uid = parts[1] or "anon"
        return User(uid=uid, anonymous=uid.startswith("anon"))
    _init_firebase()
    from firebase_admin import auth as fb_auth

    try:
        claims = fb_auth.verify_id_token(token, clock_skew_seconds=10)
    except Exception as e:  # noqa: BLE001
        log.info("token rejected", extra={"err": str(e)[:200]})
        raise HTTPException(401, "invalid or expired token") from e
    provider = (claims.get("firebase") or {}).get("sign_in_provider")
    return User(uid=claims["uid"], role=claims.get("role"), name=claims.get("name"), email=claims.get("email"),
                anonymous=provider == "anonymous")


def current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    return verify_token(authorization.split(" ", 1)[1].strip())


def bank_user(authorization: str | None = Header(default=None)) -> User:
    user = current_user(authorization)
    if not user.is_bank:
        raise HTTPException(403, "bank analyst role required")
    from .roles import request_blocks_bank
    if request_blocks_bank(user.uid):  # CR-04: revoked (or not yet approved) access ends at once
        raise HTTPException(403, {"code": "BANK_ACCESS_REVOKED", "message": "Bank access is not active for this account."})
    return user


def admin_user(authorization: str | None = Header(default=None)) -> User:
    """CR-04: the admin console and its APIs need the `role: admin` custom claim."""
    user = current_user(authorization)
    if user.role != "admin":
        raise HTTPException(403, {"code": "ADMIN_REQUIRED", "message": "Admin role required."})
    return user


def victim_user(authorization: str | None = Header(default=None)) -> User:
    """Victim routes: a signed-in phone account (anonymous sessions are no longer accepted, CR-03 B). Staff
    (work-email) accounts — bank applicants, analysts, admins — are not victims (CR-04)."""
    user = current_user(authorization)
    if user.anonymous:
        raise HTTPException(401, {"code": "SIGN_IN_REQUIRED", "message": "Please sign in with your phone number."})
    from .roles import is_staff_email
    if user.role in ("bank", "admin") or is_staff_email(user.email):
        raise HTTPException(403, {"code": "VICTIM_ACCOUNT_REQUIRED",
                                  "message": "This is a staff account. Victims sign in with their phone number."})
    return user
